import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from fastapi import HTTPException
import httpx
import pytest

from stream_edge import telemetry as edge_telemetry
from stream_edge.api.alerts_sse import _resolve_stream_user_id
from stream_edge.clients.kafka import (
    KafkaEventProducer,
    _kafka_base_config,
    create_kafka_consumer,
)
from stream_edge.collectors.ats_boards import BreezyCollector
from stream_edge.collectors.base import CollectedJob, push_jobs_to_edge
from stream_edge.config import StreamEdgeSettings, settings as edge_settings
from stream_edge.main import app
from stream_edge.workers.dlq_replay import replay_dlq
from stream_edge.workers.lifecycle import _MARK_CLOSED_SQL, _is_posting_closed
from stream_edge.workers.matcher import (
    _rescore_resume_sync,
    _upsert_job_and_score_sync,
)
from vektryn_contracts import (
    ATSSource,
    DeadLetterEvent,
    EMBEDDING_DIMENSIONS,
    JobEnrichedEvent,
    JobRescoreEvent,
    KafkaTopic,
    sign_stream_token,
)


def test_stream_edge_settings_env_aliases(monkeypatch):
    monkeypatch.delenv("GCS_BUCKET_NAME", raising=False)
    monkeypatch.setenv("GCS_SNAPSHOTS_BUCKET", "vektryn-snapshots-prod")
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql://user:pass@10.1.2.3:5432/vektryn_prod",
    )
    monkeypatch.setenv(
        "CORS_ALLOWED_ORIGINS",
        "https://vektryn.debastiani.dev, http://localhost:3000",
    )

    cfg = StreamEdgeSettings(_env_file=None)
    assert cfg.gcs_bucket_name == "vektryn-snapshots-prod"
    assert cfg.postgres_dsn == "postgresql://user:pass@10.1.2.3:5432/vektryn_prod"
    assert cfg.cors_allowed_origins_list == [
        "https://vektryn.debastiani.dev",
        "http://localhost:3000",
    ]


async def test_healthcheck_endpoint():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "stream-edge"}


async def test_kafka_producer_publish_raw_and_dlq_replay_execute():
    fake_confluent_producer = MagicMock()
    with patch(
        "stream_edge.clients.kafka.Producer", return_value=fake_confluent_producer
    ):
        producer = KafkaEventProducer(bootstrap_servers="localhost:9092")
        await producer.publish_raw(
            topic=KafkaTopic.JOBS_RAW,
            key="greenhouse:123",
            payload={"ats_source": "greenhouse", "external_id": "123"},
        )
        producer.close()

    fake_confluent_producer.produce.assert_called_once()
    kwargs = fake_confluent_producer.produce.call_args.kwargs
    assert kwargs["topic"] == KafkaTopic.JOBS_RAW.value
    assert kwargs["key"] == b"greenhouse:123"
    assert json.loads(kwargs["value"].decode("utf-8"))["external_id"] == "123"
    fake_confluent_producer.flush.assert_called_once()

    dlq_item = DeadLetterEvent(
        original_topic=KafkaTopic.JOBS_RAW.value,
        partition=0,
        offset=1,
        error_type="ValueError",
        error_message="transient failure",
        retry_count=1,
        raw_payload={"ats_source": "greenhouse", "external_id": "456"},
    )
    replay_producer = MagicMock()
    with (
        patch(
            "stream_edge.workers.dlq_replay._collect_dlq_events",
            return_value=[dlq_item],
        ),
        patch("stream_edge.clients.kafka.Producer", return_value=replay_producer),
    ):
        replayed = await replay_dlq(max_messages=10, execute=True)

    assert replayed == 1
    replay_producer.produce.assert_called_once()
    replay_producer.flush.assert_called_once()


async def test_lifecycle_closed_detection_and_uuid_cast_sql():
    assert "ANY(%s::uuid[])" in _MARK_CLOSED_SQL

    def handler(request: httpx.Request) -> httpx.Response:
        if "gone" in str(request.url):
            return httpx.Response(410)
        if "filled" in str(request.url):
            return httpx.Response(
                200, text="<html>This position has been filled.</html>"
            )
        return httpx.Response(
            200, text="<html>Senior Python Engineer — Apply now</html>"
        )

    transport = httpx.MockTransport(handler)
    semaphore = asyncio.Semaphore(4)
    async with httpx.AsyncClient(transport=transport) as client:
        assert (
            await _is_posting_closed(client, semaphore, "u1", "https://ex.com/gone")
            == "u1"
        )
        assert (
            await _is_posting_closed(client, semaphore, "u2", "https://ex.com/filled")
            == "u2"
        )
        assert (
            await _is_posting_closed(client, semaphore, "u3", "https://ex.com/open")
            is None
        )


def test_matcher_handles_zero_active_resumes_without_unbound_local_error():
    enriched = JobEnrichedEvent(
        ats_source=ATSSource.GREENHOUSE,
        external_id="gh-999",
        content_hash="a" * 64,
        title="Backend Engineer",
        company_name="Delta",
        apply_url="https://example.com/jobs/999",
        raw_html_gcs_uri="file:///tmp/999.html",
        description_clean="Python Django Kafka",
        embedding=[0.01] * EMBEDDING_DIMENSIONS,
    )

    fake_cursor = MagicMock()
    fake_cursor.__enter__.return_value = fake_cursor
    fake_cursor.fetchone.return_value = (uuid4(),)
    fake_cursor.fetchall.return_value = []

    fake_conn = MagicMock()
    fake_conn.__enter__.return_value = fake_conn
    fake_conn.cursor.return_value = fake_cursor

    fake_gemini = MagicMock()
    fake_producer = MagicMock()

    with (
        patch("stream_edge.workers.matcher.psycopg.connect", return_value=fake_conn),
        patch("stream_edge.workers.matcher.register_vector"),
    ):
        _upsert_job_and_score_sync(
            enriched=enriched,
            gemini=fake_gemini,
            producer=fake_producer,
        )

    fake_conn.commit.assert_called_once()
    fake_producer.flush.assert_called_once()


async def test_ingest_requires_api_key_when_configured(monkeypatch):
    monkeypatch.setattr(edge_settings, "ingest_api_key", "secret-ingest-key")

    app.state.kafka_producer = MagicMock(publish=AsyncMock())
    app.state.snapshot_storage = MagicMock(
        save_raw_html=AsyncMock(return_value="file:///tmp/job.html")
    )

    sample_payload = {
        "ats_source": "greenhouse",
        "external_id": "gh-1",
        "title": "Senior Backend Engineer",
        "company_name": "Acme",
        "apply_url": "https://example.com/jobs/1",
        "raw_html": "<p>Python</p>",
        "description_clean": "Python Django",
    }

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        missing_key = await client.post("/ingest/jobs", json=sample_payload)
        wrong_key = await client.post(
            "/ingest/jobs",
            json=sample_payload,
            headers={"X-Ingest-API-Key": "wrong"},
        )
        valid_key = await client.post(
            "/ingest/jobs",
            json=sample_payload,
            headers={"X-Ingest-API-Key": "secret-ingest-key"},
        )

    assert missing_key.status_code == 401
    assert wrong_key.status_code == 401
    assert valid_key.status_code == 202


async def test_push_jobs_to_edge_attaches_ingest_api_key():
    captured_headers: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured_headers.update(dict(request.headers))
        return httpx.Response(202, json={"status": "accepted"})

    job = CollectedJob(
        ats_source=ATSSource.GREENHOUSE,
        external_id="gh-77",
        title="Backend Engineer",
        company_name="Acme",
        apply_url="https://example.com/jobs/77",
        raw_html="<p>Hello</p>",
        description_clean="Hello",
    )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        accepted = await push_jobs_to_edge(
            http_client=client,
            edge_base_url="http://edge",
            jobs=[job],
            ingest_api_key="collector-secret",
        )

    assert accepted == 1
    assert captured_headers.get("x-ingest-api-key") == "collector-secret"


def test_stream_alerts_enforces_signed_token_and_blocks_spoofing(monkeypatch):
    monkeypatch.setattr(edge_settings, "stream_auth_secret", "stream-secret-xyz")
    valid_token = sign_stream_token("42", "stream-secret-xyz", ttl_seconds=300)

    assert _resolve_stream_user_id(token=valid_token, user_id="999") == "42"

    with pytest.raises(HTTPException) as missing_exc:
        _resolve_stream_user_id(token=None, user_id="42")
    assert missing_exc.value.status_code == 401

    with pytest.raises(HTTPException) as invalid_exc:
        _resolve_stream_user_id(token="42.9999999999.bad", user_id="42")
    assert invalid_exc.value.status_code == 401


async def test_breezy_collector_fetches_full_description_html():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/json":
            return httpx.Response(
                200,
                json=[
                    {
                        "id": "bz-42",
                        "name": "Senior Backend Engineer",
                        "url": "https://acme.breezy.hr/p/bz-42",
                        "location": {"name": "Remote", "is_remote": True},
                        "company": {"name": "Acme"},
                        "published_date": "2026-03-01T12:00:00Z",
                    }
                ],
            )
        return httpx.Response(
            200,
            text="<html><body><div class='description'><p>Python, Django, Kafka, PostgreSQL.</p></div></body></html>",
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        collector = BreezyCollector(http_client=client)
        jobs = await collector.fetch_board("acme", "Acme")

    assert len(jobs) == 1
    assert jobs[0].external_id == "bz-42"
    assert "Django" in jobs[0].description_clean
    assert "Kafka" in jobs[0].description_clean


async def test_metrics_endpoint_exposes_custom_vektryn_counters():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test", follow_redirects=True
    ) as client:
        response = await client.get("/metrics")

    assert response.status_code == 200
    body = response.text
    assert "vektryn_ingest_jobs_total" in body
    assert "vektryn_sse_active_clients" in body


def test_kafka_base_config_supports_optional_sasl_ssl(monkeypatch):
    monkeypatch.setattr(edge_settings, "kafka_security_protocol", "SASL_SSL")
    monkeypatch.setattr(edge_settings, "kafka_sasl_mechanism", "SCRAM-SHA-256")
    monkeypatch.setattr(edge_settings, "kafka_sasl_username", "redpanda-user")
    monkeypatch.setattr(edge_settings, "kafka_sasl_password", "redpanda-pass")

    cfg = _kafka_base_config("seed.redpanda.cloud:9092")
    assert cfg == {
        "bootstrap.servers": "seed.redpanda.cloud:9092",
        "security.protocol": "SASL_SSL",
        "sasl.mechanism": "SCRAM-SHA-256",
        "sasl.username": "redpanda-user",
        "sasl.password": "redpanda-pass",
    }


def test_stream_edge_sentry_gated_by_dsn(monkeypatch):
    monkeypatch.setattr(edge_telemetry, "_SENTRY_CONFIGURED", False)
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    with patch.object(edge_telemetry.sentry_sdk, "init") as mock_init:
        assert edge_telemetry.configure_sentry("vektryn-stream-edge") is False
        mock_init.assert_not_called()

        monkeypatch.setenv("SENTRY_DSN", "https://public@example.ingest.sentry.io/2")
        with patch.object(edge_telemetry.sentry_sdk, "set_tag") as mock_tag:
            assert edge_telemetry.configure_sentry("vektryn-stream-edge") is True
            mock_init.assert_called_once()
            mock_tag.assert_called_once_with("service", "vektryn-stream-edge")


def test_matcher_rescore_uses_hnsw_stale_first_selection_and_commits_per_job():
    resume_uuid = uuid4()
    stale_job_uuid = uuid4()
    unscored_job_uuid = uuid4()
    event = JobRescoreEvent(
        resume_profile_uuid=resume_uuid,
        user_id=42,
        max_jobs=10,
        force=False,
    )

    executed_sql: list[str] = []
    fake_cursor = MagicMock()
    fake_cursor.__enter__.return_value = fake_cursor

    def _capture_execute(sql, params=None):
        executed_sql.append(sql)

    fake_cursor.execute.side_effect = _capture_execute
    # Sequence of fetchone/fetchall calls:
    # 1. fetchone() -> ResumeProfile
    # 2. fetchall() -> stale MatchScore candidate (1 row)
    # 3. fetchall() -> unscored active JobPosting candidate (1 row)
    # 4. fetchone() -> upsert returning (match_uuid, alert_sent_at) for stale job
    # 5. fetchone() -> upsert returning (match_uuid, alert_sent_at) for unscored job
    fake_cursor.fetchone.side_effect = [
        (
            resume_uuid,
            42,
            "Senior Python Django Engineer",
            "new-hash" + "0" * 56,
            ["python", "django"],
            ["senior"],
            ["pj"],
            ["brazil"],
            70,
            [0.01] * EMBEDDING_DIMENSIONS,
        ),
        (uuid4(), None),
        (uuid4(), None),
    ]
    fake_cursor.fetchall.side_effect = [
        [
            (
                stale_job_uuid,
                "Staff Python Engineer",
                "Acme",
                "https://example.com/jobs/stale",
                "Python Django",
                "junior",  # Fails target_seniority=["senior"] -> should downgrade to None
                "pj",
                ["brazil"],
                ["python", "django"],
                0.78,
            )
        ],
        [
            (
                unscored_job_uuid,
                "Senior Python Engineer",
                "Beta",
                "https://example.com/jobs/unscored",
                "Python Django Kafka",
                "senior",
                "pj",
                ["brazil"],
                ["python", "django", "kafka"],
                0.86,
            )
        ],
    ]

    fake_conn = MagicMock()
    fake_conn.__enter__.return_value = fake_conn
    fake_conn.cursor.return_value = fake_cursor

    eval_result = MagicMock(
        fit_score=88,
        matched_skills=["python", "django"],
        missing_keywords=["kafka"],
        talking_points=["Highlight Django scale."],
        gap_summary="Strong fit.",
    )
    fake_gemini = MagicMock()
    fake_gemini.evaluate_resume_fit = AsyncMock(
        return_value=(eval_result, "gemini-4-hydrogen")
    )
    fake_producer = MagicMock()

    with (
        patch("stream_edge.workers.matcher.psycopg.connect", return_value=fake_conn),
        patch("stream_edge.workers.matcher.register_vector"),
    ):
        processed = _rescore_resume_sync(
            event=event,
            gemini=fake_gemini,
            producer=fake_producer,
        )

    assert processed == 2
    assert fake_conn.commit.call_count == 2
    fake_producer.flush.assert_called_once()
    # Only the qualifying unscored job should trigger Gemini & emit an alert
    fake_gemini.evaluate_resume_fit.assert_awaited_once()
    fake_producer._publish_sync.assert_called_once()

    # Verify both candidate queries use HNSW-compatible ORDER BY distance ASC
    candidate_queries = [s for s in executed_sql if "FROM jobs_jobposting j" in s]
    assert len(candidate_queries) == 2
    assert "m.resume_content_hash <> %s" in candidate_queries[0]
    assert "NOT EXISTS" in candidate_queries[1]
    for query in candidate_queries:
        assert "ORDER BY j.embedding <=> %s::vector ASC" in query
        assert "ORDER BY 1 -" not in query


def test_matcher_rescore_force_watermark_and_consumer_poll_interval():
    resume_uuid = uuid4()
    event = JobRescoreEvent(
        resume_profile_uuid=resume_uuid,
        user_id=42,
        max_jobs=25,
        force=True,
    )

    executed_sql: list[str] = []
    fake_cursor = MagicMock()
    fake_cursor.__enter__.return_value = fake_cursor
    fake_cursor.execute.side_effect = lambda sql, params=None: executed_sql.append(sql)
    fake_cursor.fetchone.return_value = (
        resume_uuid,
        42,
        "Python Engineer",
        "hash" + "0" * 60,
        ["python"],
        [],
        [],
        [],
        70,
        [0.01] * EMBEDDING_DIMENSIONS,
    )
    fake_cursor.fetchall.return_value = []

    fake_conn = MagicMock()
    fake_conn.__enter__.return_value = fake_conn
    fake_conn.cursor.return_value = fake_cursor

    with (
        patch("stream_edge.workers.matcher.psycopg.connect", return_value=fake_conn),
        patch("stream_edge.workers.matcher.register_vector"),
    ):
        assert (
            _rescore_resume_sync(event=event, gemini=MagicMock(), producer=MagicMock())
            == 0
        )

    force_queries = [s for s in executed_sql if "FROM jobs_jobposting j" in s]
    assert len(force_queries) == 1
    assert "m.modified_at < %s" in force_queries[0]
    assert "ORDER BY j.embedding <=> %s::vector ASC" in force_queries[0]

    fake_consumer = MagicMock()
    with patch(
        "stream_edge.clients.kafka.Consumer", return_value=fake_consumer
    ) as mock_cls:
        create_kafka_consumer(
            group_id="vektryn-matcher-worker",
            topics=[KafkaTopic.JOBS_ENRICHED, KafkaTopic.JOBS_RESCORE],
            bootstrap_servers="localhost:9092",
            max_poll_interval_ms=600_000,
        )
    passed_cfg = mock_cls.call_args.args[0]
    assert passed_cfg["max.poll.interval.ms"] == 600_000
    fake_consumer.subscribe.assert_called_once_with(["jobs.enriched", "jobs.rescore"])
