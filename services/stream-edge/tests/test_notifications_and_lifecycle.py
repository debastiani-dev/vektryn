import asyncio
from datetime import UTC, datetime
from unittest.mock import MagicMock
import uuid

from psycopg._queries import PostgresQuery
from psycopg.adapt import Transformer

from stream_edge.api.alerts_sse import _format_alert_sse
from stream_edge.clients import notifications as notif_client
from stream_edge.workers import lifecycle, matcher
from vektryn_contracts import (
    ATSSource,
    JobEnrichedEvent,
    JobMatchAlertEvent,
    NotificationKind,
)


def test_insert_notification_sql_writes_explicit_is_deleted_false() -> None:
    sql_lower = notif_client.INSERT_NOTIFICATION_SQL.lower()
    assert "insert into base_notification" in sql_lower
    assert "is_deleted" in sql_lower
    assert "false" in sql_lower
    assert "created_at" in sql_lower
    assert "modified_at" in sql_lower


def test_matcher_claim_alert_is_atomic_and_inserts_notification() -> None:
    now = datetime(2026, 11, 25, 12, 0, tzinfo=UTC)
    match_uuid = uuid.uuid4()
    job = matcher._JobCandidate(
        uuid=uuid.uuid4(),
        title="Staff Python Engineer",
        company_name="Acme",
        apply_url="https://acme.test/jobs/1",
        description_clean="Python and Kafka",
        seniority="staff",
        contract_type="pj",
        region_eligibility=["brazil"],
        tech_stack=["python", "kafka"],
        ats_source="greenhouse",
    )
    outcome = matcher._EvaluationOutcome(
        fit_score=91,
        matched_skills=["python"],
        missing_keywords=["go"],
    )

    # Case 1: atomic UPDATE claims alert_sent_at IS NULL -> inserts notification + returns event
    cur = MagicMock()
    cur.fetchone.return_value = (match_uuid,)
    event = matcher._claim_and_persist_match_alert(
        cur,
        now=now,
        trace_id="a" * 32,
        job=job,
        resume_uuid=uuid.uuid4(),
        user_id=7,
        match_score_uuid=match_uuid,
        cosine_val=0.88,
        outcome=outcome,
    )
    assert event is not None
    assert event.notification_uuid is not None
    assert cur.execute.call_count == 2
    claim_sql = cur.execute.call_args_list[0].args[0]
    insert_sql = cur.execute.call_args_list[1].args[0]
    insert_params = cur.execute.call_args_list[1].args[1]
    assert "alert_sent_at IS NULL" in claim_sql
    assert "RETURNING uuid" in claim_sql
    assert "INSERT INTO base_notification" in insert_sql
    assert insert_params[0] == event.notification_uuid
    assert insert_params[4] == NotificationKind.MATCH_ALERT.value

    # Case 2: concurrent worker already claimed -> fetchone() is None -> no notification/event
    cur_lost = MagicMock()
    cur_lost.fetchone.return_value = None
    event_lost = matcher._claim_and_persist_match_alert(
        cur_lost,
        now=now,
        trace_id="a" * 32,
        job=job,
        resume_uuid=uuid.uuid4(),
        user_id=7,
        match_score_uuid=match_uuid,
        cosine_val=0.88,
        outcome=outcome,
    )
    assert event_lost is None
    assert cur_lost.execute.call_count == 1


def test_matcher_commits_before_publishing_alerts(monkeypatch) -> None:
    call_order: list[str] = []
    job_uuid = uuid.uuid4()
    resume_uuid = uuid.uuid4()
    match_uuid = uuid.uuid4()

    class _FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, sql, params=None):
            self._last_sql = sql

        def fetchall(self):
            return [
                (
                    resume_uuid,
                    11,
                    "Backend",
                    "Python resume",
                    "h" * 64,
                    ["python"],
                    ["senior"],
                    ["pj"],
                    ["brazil"],
                    75,
                    0.9,
                )
            ]

    class _FakeConn:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def cursor(self):
            return _FakeCursor()

        def commit(self):
            call_order.append("commit")

    alert_event = JobMatchAlertEvent(
        notification_uuid=uuid.uuid4(),
        user_id=11,
        job_posting_uuid=job_uuid,
        resume_profile_uuid=resume_uuid,
        match_score_uuid=match_uuid,
        title="Senior Python",
        company_name="Acme",
        fit_score=90,
        cosine_similarity=0.9,
        apply_url="https://acme.test/jobs/1",
    )

    monkeypatch.setattr(matcher.psycopg, "connect", lambda *_a, **_kw: _FakeConn())
    monkeypatch.setattr(matcher, "register_vector", lambda _c: None)
    monkeypatch.setattr(matcher, "_upsert_job_posting", lambda *_a, **_kw: job_uuid)
    monkeypatch.setattr(
        matcher,
        "_score_and_persist_pair",
        lambda *_a, **_kw: matcher._PairScoreResult(alert=alert_event, scored=True),
    )

    producer = MagicMock()
    producer._publish_sync.side_effect = lambda **_kw: call_order.append("publish")
    producer.flush.side_effect = lambda _t: call_order.append("flush")

    enriched = JobEnrichedEvent(
        ats_source=ATSSource.GREENHOUSE,
        external_id="gh-1",
        content_hash="b" * 64,
        title="Senior Python",
        company_name="Acme",
        apply_url="https://acme.test/jobs/1",
        raw_html_gcs_uri="gs://bucket/1.html",
        description_clean="Build Python APIs",
        embedding=[0.1] * 768,
    )

    matcher._upsert_job_and_score_sync(
        enriched=enriched,
        scoring_manager=MagicMock(),
        producer=producer,
        byok_encryption_key="",
    )
    assert call_order == ["commit", "publish", "flush"]


def test_lifecycle_sql_queries_parse_with_psycopg_placeholders() -> None:
    now = datetime(2026, 11, 27, 3, 0, tzinfo=UTC)
    sample_uuid = str(uuid.uuid4())

    fetch_query = PostgresQuery(Transformer())
    fetch_query.convert(lifecycle._FETCH_ACTIVE_SQL, (200,))
    assert b"apply_url ILIKE 'http://%'" in fetch_query.query
    assert b"apply_url ILIKE 'https://%'" in fetch_query.query
    assert b"LIMIT $1" in fetch_query.query

    PostgresQuery(Transformer()).convert(
        lifecycle._MARK_CLOSED_SQL, (now, now, [sample_uuid])
    )
    PostgresQuery(Transformer()).convert(
        lifecycle._ACTIVE_LEADS_FOR_JOBS_SQL, ([sample_uuid],)
    )
    PostgresQuery(Transformer()).convert(
        lifecycle._CLAIM_DUE_FOLLOWUPS_SQL, (now, now, now)
    )


def test_lifecycle_notifies_active_leads_and_always_runs_retention(monkeypatch) -> None:
    job_uuid = uuid.uuid4()
    lead_uuid = uuid.uuid4()
    executed: list[tuple[str, tuple]] = []

    class _FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, sql, params=None):
            executed.append((sql, params or ()))
            self._sql = sql

        def fetchall(self):
            if "RETURNING uuid, title" in self._sql:
                return [
                    (job_uuid, "Senior Django Dev", "Beta Co", "https://beta.test/1")
                ]
            if "FROM tracker_applicationlead" in self._sql:
                return [(lead_uuid, 42, job_uuid, "applied")]
            return []

    class _FakeConn:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def cursor(self):
            return _FakeCursor()

        def commit(self):
            # In-memory test double: transaction commit is a no-op
            return None

    monkeypatch.setattr(lifecycle.psycopg, "connect", lambda *_a, **_kw: _FakeConn())
    closed, notified = lifecycle._mark_closed_and_notify_sync(
        [str(job_uuid)],
        datetime(2026, 11, 25, 3, 0, tzinfo=UTC),
    )
    assert (closed, notified) == (1, 1)
    assert any("AND is_active = TRUE" in sql for sql, _ in executed)
    assert any("status NOT IN ('rejected', 'withdrawn')" in sql for sql, _ in executed)
    notif_inserts = [
        params for sql, params in executed if "INSERT INTO base_notification" in sql
    ]
    assert len(notif_inserts) == 1
    assert notif_inserts[0][3] == 42
    assert notif_inserts[0][4] == NotificationKind.TRACKED_JOB_CLOSED.value

    # Even with zero active postings, retention sweep must still run
    prune_calls: list[int] = []

    class _EmptyCursor(_FakeCursor):
        def fetchall(self):
            return []

    class _EmptyConn(_FakeConn):
        def cursor(self):
            return _EmptyCursor()

    monkeypatch.setattr(lifecycle.psycopg, "connect", lambda *_a, **_kw: _EmptyConn())
    followup_calls: list[int] = []
    monkeypatch.setattr(
        lifecycle,
        "_run_due_followups_sync",
        lambda _now: followup_calls.append(1) or 0,
    )
    monkeypatch.setattr(
        lifecycle,
        "_run_notification_retention_sync",
        lambda _now: prune_calls.append(1) or 0,
    )
    assert asyncio.run(lifecycle.run_lifecycle_check(batch_size=10)) == 0
    assert followup_calls == [1]
    assert prune_calls == [1]


def test_lifecycle_notifies_due_followups_and_isolates_failures(monkeypatch) -> None:
    lead_uuid = uuid.uuid4()
    job_uuid = uuid.uuid4()
    due_at = datetime(2026, 11, 24, 15, 0, tzinfo=UTC)
    now = datetime(2026, 11, 25, 3, 0, tzinfo=UTC)
    executed: list[tuple[str, tuple]] = []

    class _DueCursor:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, sql, params=None):
            executed.append((sql, params or ()))
            self._sql = sql

        def fetchall(self):
            if "UPDATE tracker_applicationlead" in self._sql:
                return [
                    (
                        lead_uuid,
                        42,
                        job_uuid,
                        "interviewing",
                        due_at,
                        "Staff Python Engineer",
                        "Acme",
                        "https://acme.test/jobs/1",
                    )
                ]
            return []

    class _DueConn:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def cursor(self):
            return _DueCursor()

        def commit(self):
            # In-memory test double: transaction commit is a no-op
            return None

    monkeypatch.setattr(lifecycle.psycopg, "connect", lambda *_a, **_kw: _DueConn())
    emitted = lifecycle._notify_due_followups_sync(now)
    assert emitted == 1
    assert any("SET followup_notified_at = %s" in sql for sql, _ in executed)
    assert any("l.next_action_at <= %s" in sql for sql, _ in executed)
    notif_inserts = [
        params for sql, params in executed if "INSERT INTO base_notification" in sql
    ]
    assert len(notif_inserts) == 1
    assert notif_inserts[0][3] == 42
    assert notif_inserts[0][4] == NotificationKind.LEAD_FOLLOWUP_DUE.value

    # Failure in _notify_due_followups_sync must not prevent retention sweep in run_lifecycle_check
    class _EmptyCursor:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, sql, params=None):
            return None

        def fetchall(self):
            return []

    class _EmptyConn:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def cursor(self):
            return _EmptyCursor()

    def _raise_db_blip(_now):
        raise RuntimeError("DB blip")

    prune_ran: list[int] = []
    monkeypatch.setattr(lifecycle.psycopg, "connect", lambda *_a, **_kw: _EmptyConn())
    monkeypatch.setattr(lifecycle, "_notify_due_followups_sync", _raise_db_blip)
    monkeypatch.setattr(
        lifecycle,
        "_run_notification_retention_sync",
        lambda _now: prune_ran.append(1) or 0,
    )
    assert asyncio.run(lifecycle.run_lifecycle_check(batch_size=5)) == 0
    assert prune_ran == [1]


def test_sse_frame_uses_notification_uuid_with_event_id_fallback() -> None:
    notif_uuid = uuid.uuid4()
    alert_with_notif = JobMatchAlertEvent(
        notification_uuid=notif_uuid,
        user_id=5,
        job_posting_uuid=uuid.uuid4(),
        resume_profile_uuid=uuid.uuid4(),
        match_score_uuid=uuid.uuid4(),
        title="Backend Engineer",
        company_name="Acme",
        fit_score=85,
        cosine_similarity=0.81,
        apply_url="https://acme.test/jobs/2",
    )
    msg = MagicMock()
    msg.error.return_value = None
    msg.value.return_value = alert_with_notif.model_dump_json().encode("utf-8")
    frame = _format_alert_sse(msg, user_id="5")
    assert frame is not None
    assert frame.startswith(f"id: {notif_uuid}\nevent: match_alert\n")

    legacy = alert_with_notif.model_copy(update={"notification_uuid": None})
    msg.value.return_value = legacy.model_dump_json().encode("utf-8")
    legacy_frame = _format_alert_sse(msg, user_id="5")
    assert legacy_frame is not None
    assert legacy_frame.startswith(f"id: {legacy.event_id}\nevent: match_alert\n")


def test_pipeline_error_notifications_use_connect_timeout_and_throttle(
    monkeypatch,
) -> None:
    captured_connect_kwargs: list[dict] = []
    inserted_users: list[int] = []

    class _FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, sql, params=None):
            if "INSERT INTO base_notification" in sql and params:
                inserted_users.append(params[3])

        def fetchall(self):
            return [(1,), (2,)]

    class _FakeConn:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def cursor(self):
            return _FakeCursor()

        def commit(self):
            # In-memory test double: transaction commit is a no-op
            return None

    def _fake_connect(*_args, **kwargs):
        captured_connect_kwargs.append(kwargs)
        return _FakeConn()

    monkeypatch.setattr(notif_client.psycopg, "connect", _fake_connect)
    monkeypatch.setattr(
        notif_client, "_acquire_pipeline_error_throttle", lambda *_a: True
    )

    count = notif_client.persist_pipeline_error_notifications(
        source="enrichment-worker",
        error_type="RuntimeError",
        error_message="Gemini 503",
    )
    assert count == 2
    assert inserted_users == [1, 2]
    assert captured_connect_kwargs[0]["connect_timeout"] == 3

    # When throttled, zero DB calls occur
    monkeypatch.setattr(
        notif_client, "_acquire_pipeline_error_throttle", lambda *_a: False
    )
    assert (
        notif_client.persist_pipeline_error_notifications(
            source="enrichment-worker",
            error_type="RuntimeError",
            error_message="Gemini 503",
        )
        == 0
    )
    assert len(captured_connect_kwargs) == 1


def test_manual_import_ready_and_rescore_completed_and_collector_sync(
    monkeypatch,
) -> None:
    now = datetime(2026, 11, 25, 12, 0, tzinfo=UTC)
    job = matcher._JobCandidate(
        uuid=uuid.uuid4(),
        title="Staff Python Engineer",
        company_name="Acme",
        apply_url="https://acme.test/jobs/manual-1",
        description_clean="Python and Kafka",
        seniority="staff",
        contract_type="pj",
        region_eligibility=["brazil"],
        tech_stack=["python"],
        ats_source="manual",
        submitted_by_user_id=7,
    )
    outcome = matcher._EvaluationOutcome(
        fit_score=64,
        matched_skills=["python"],
        missing_keywords=["go"],
    )

    # Matching submitter gets manual_import_ready notification
    cur = MagicMock()
    matcher._persist_manual_import_ready(
        cur,
        now=now,
        job=job,
        resume_uuid=uuid.uuid4(),
        user_id=7,
        match_score_uuid=uuid.uuid4(),
        cosine_val=0.72,
        outcome=outcome,
    )
    assert cur.execute.call_count == 1
    assert (
        cur.execute.call_args.args[1][4] == NotificationKind.MANUAL_IMPORT_READY.value
    )

    # Other user does NOT receive another user's manual import notification
    cur_other = MagicMock()
    matcher._persist_manual_import_ready(
        cur_other,
        now=now,
        job=job,
        resume_uuid=uuid.uuid4(),
        user_id=99,
        match_score_uuid=uuid.uuid4(),
        cosine_val=0.72,
        outcome=outcome,
    )
    assert cur_other.execute.call_count == 0

    # rescore_completed persists summary for user
    cur_rescore = MagicMock()
    matcher._persist_rescore_completed(
        cur_rescore,
        now=now,
        user_id=7,
        resume_uuid=uuid.uuid4(),
        resume_label="Backend Python",
        processed_count=12,
        scored_count=8,
        alerts_count=2,
        force=False,
    )
    assert cur_rescore.execute.call_count == 1
    assert (
        cur_rescore.execute.call_args.args[1][4]
        == NotificationKind.RESCORE_COMPLETED.value
    )

    # collector_sync_completed skips silent 0-new/0-error runs and notifies staff when ingested > 0
    assert (
        notif_client.persist_collector_sync_notifications(
            fetched_count=30,
            ingested_count=0,
            deduped_count=30,
            error_count=0,
            sources_count=12,
        )
        == 0
    )

    inserted_kinds: list[str] = []

    class _SyncCursor:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, sql, params=None):
            if "INSERT INTO base_notification" in sql and params:
                inserted_kinds.append(params[4])

        def fetchall(self):
            return [(1,)]

    class _SyncConn:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def cursor(self):
            return _SyncCursor()

        def commit(self):
            # In-memory test double: transaction commit is a no-op
            return None

    monkeypatch.setattr(notif_client.psycopg, "connect", lambda *_a, **_kw: _SyncConn())
    sent = notif_client.persist_collector_sync_notifications(
        fetched_count=40,
        ingested_count=5,
        deduped_count=35,
        error_count=0,
        sources_count=12,
    )
    assert sent == 1
    assert inserted_kinds == [NotificationKind.COLLECTOR_SYNC_COMPLETED.value]
