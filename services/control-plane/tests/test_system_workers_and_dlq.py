from datetime import UTC, datetime, timedelta
import json
from unittest.mock import MagicMock, patch
from uuid import uuid4

from confluent_kafka import KafkaError
from django.contrib.auth import get_user_model
import pytest
from rest_framework.test import APIClient

from apps.analytics.models.analytics import CollectorRunLog
from apps.analytics.services import collector_trigger, dlq_inspector, system_status
from vektryn_contracts import DeadLetterEvent, KafkaTopic

User = get_user_model()


def _make_kafka_msg(
    *,
    payload_bytes: bytes,
    partition: int = 0,
    offset: int = 0,
    error_code: int | None = None,
) -> MagicMock:
    msg = MagicMock()
    msg.partition.return_value = partition
    msg.offset.return_value = offset
    msg.value.return_value = payload_bytes
    if error_code is None:
        msg.error.return_value = None
    else:
        err = MagicMock()
        err.code.return_value = error_code
        msg.error.return_value = err
    return msg


def _make_dlq_bytes(
    *,
    event_id=None,
    original_topic: str = KafkaTopic.JOBS_RAW.value,
    error_type: str = "GeminiServiceError",
    error_message: str = "503 Service Unavailable",
    raw_payload=None,
    produced_at: datetime | None = None,
) -> tuple[str, bytes]:
    eid = event_id or uuid4()
    ev = DeadLetterEvent(
        event_id=eid,
        produced_at=produced_at or datetime.now(UTC),
        original_topic=original_topic,
        partition=0,
        offset=12,
        error_type=error_type,
        error_message=error_message,
        retry_count=1,
        raw_payload=(
            raw_payload
            if raw_payload is not None
            else {"ats_source": "greenhouse", "external_id": "job-42", "title": "Staff"}
        ),
    )
    return str(ev.event_id), ev.model_dump_json().encode("utf-8")


@pytest.mark.django_db
def test_system_status_worker_liveness_alive_stale_offline_and_skew():
    staff = User.objects.create_user(
        username="staff_liveness", password="pw", is_staff=True
    )
    now = datetime.now(UTC)
    CollectorRunLog.objects.create(
        source="greenhouse",
        fetched_count=10,
        ingested_count=2,
        deduped_count=8,
        error_count=0,
        duration_ms=500,
        ran_at=now,
    )
    client = APIClient()
    client.force_authenticate(user=staff)

    fake_dlq = {"status": "healthy", "recent_24h_count": 0, "total_count": 0}

    # 1. Both workers alive (with +2s future NTP skew clamped to age_seconds=0)
    fake_redis = MagicMock()
    fake_redis.mget.return_value = [
        json.dumps(
            {
                "worker": "enrichment-worker",
                "last_heartbeat_at": (now + timedelta(seconds=2)).isoformat(),
                "last_message_at": (now - timedelta(seconds=5)).isoformat(),
                "processed_count": 14,
            }
        ),
        json.dumps(
            {
                "worker": "matcher-worker",
                "last_heartbeat_at": (now - timedelta(seconds=15)).isoformat(),
                "last_message_at": None,
                "processed_count": 0,
            }
        ),
    ]
    with (
        patch.object(system_status, "get_dlq_health", return_value=fake_dlq),
        patch.object(system_status, "_get_redis_client", return_value=fake_redis),
        patch.object(collector_trigger, "_get_redis_client", return_value=None),
    ):
        res_alive = client.get("/api/v1/system/status/")
    assert res_alive.status_code == 200
    body_alive = res_alive.json()
    assert body_alive["overall_status"] == "healthy"
    assert body_alive["status_reasons"] == []
    assert body_alive["workers"]["status"] == "healthy"
    assert body_alive["workers"]["items"][0]["status"] == "alive"
    assert body_alive["workers"]["items"][0]["age_seconds"] == 0
    assert body_alive["workers"]["items"][0]["processed_count"] == 14
    assert body_alive["workers"]["items"][1]["status"] == "alive"

    # 2. One worker stale (>60s) -> overall warning
    fake_redis.mget.return_value = [
        json.dumps(
            {
                "worker": "enrichment-worker",
                "last_heartbeat_at": (now - timedelta(seconds=75)).isoformat(),
                "last_message_at": None,
                "processed_count": 3,
            }
        ),
        json.dumps(
            {
                "worker": "matcher-worker",
                "last_heartbeat_at": (now - timedelta(seconds=10)).isoformat(),
                "last_message_at": None,
                "processed_count": 9,
            }
        ),
    ]
    with (
        patch.object(system_status, "get_dlq_health", return_value=fake_dlq),
        patch.object(system_status, "_get_redis_client", return_value=fake_redis),
        patch.object(collector_trigger, "_get_redis_client", return_value=None),
    ):
        res_stale = client.get("/api/v1/system/status/")
    assert res_stale.json()["workers"]["status"] == "warning"
    assert res_stale.json()["overall_status"] == "warning"
    assert res_stale.json()["status_reasons"] == [
        "Stale worker heartbeat: enrichment-worker."
    ]

    # 3. One worker missing/expired -> offline -> overall degraded
    fake_redis.mget.return_value = [
        None,
        json.dumps(
            {
                "worker": "matcher-worker",
                "last_heartbeat_at": (now - timedelta(seconds=10)).isoformat(),
                "last_message_at": None,
                "processed_count": 9,
            }
        ),
    ]
    with (
        patch.object(system_status, "get_dlq_health", return_value=fake_dlq),
        patch.object(system_status, "_get_redis_client", return_value=fake_redis),
        patch.object(collector_trigger, "_get_redis_client", return_value=None),
    ):
        res_offline = client.get("/api/v1/system/status/")
    assert res_offline.json()["workers"]["status"] == "degraded"
    assert res_offline.json()["workers"]["items"][0]["status"] == "offline"
    assert res_offline.json()["overall_status"] == "degraded"
    assert res_offline.json()["status_reasons"] == [
        "Worker offline: enrichment-worker."
    ]


def test_overall_status_ignores_recent_filtered_unmatched_and_reports_operational_reasons():
    now = datetime.now(UTC)
    healthy_dlq = {"status": "healthy", "recent_24h_count": 0, "total_count": 0}
    healthy_workers = {
        "status": "healthy",
        "items": [
            {"worker": "enrichment-worker", "status": "alive"},
            {"worker": "matcher-worker", "status": "alive"},
        ],
    }
    clean_totals = {
        "fetched_count": 20,
        "ingested_count": 5,
        "deduped_count": 15,
        "error_count": 0,
        "duration_ms": 1200,
    }

    # Normal Stage 1 eligibility filtering (recent_unmatched_count > 0) must stay healthy
    status, reasons = system_status._evaluate_overall_status(
        last_collect_at=now,
        latest_run_totals=clean_totals,
        jobs_metrics={
            "active_count": 68,
            "matched_active_count": 49,
            "ai_scored_count": 30,
            "unscored_active_count": 38,
            "pending_match_count": 19,
            "recent_unmatched_count": 19,
            "unembedded_active_count": 0,
        },
        dlq=healthy_dlq,
        workers=healthy_workers,
    )
    assert status == "healthy"
    assert reasons == []

    # Missing embeddings is an actual operational anomaly -> warning with explicit reason
    warn_status, warn_reasons = system_status._evaluate_overall_status(
        last_collect_at=now,
        latest_run_totals=clean_totals,
        jobs_metrics={
            "active_count": 10,
            "matched_active_count": 9,
            "ai_scored_count": 9,
            "unscored_active_count": 1,
            "pending_match_count": 1,
            "recent_unmatched_count": 1,
            "unembedded_active_count": 2,
        },
        dlq=healthy_dlq,
        workers=healthy_workers,
    )
    assert warn_status == "warning"
    assert warn_reasons == ["2 active jobs are missing embeddings."]


@pytest.mark.django_db
def test_dlq_endpoints_enforce_staff_permission():
    regular = User.objects.create_user(
        username="regular_dlq", password="pw", is_staff=False
    )
    client = APIClient()
    client.force_authenticate(user=regular)

    assert client.get("/api/v1/system/dlq/").status_code == 403
    assert (
        client.post(
            "/api/v1/system/dlq/replay/", {"dry_run": True}, format="json"
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/v1/system/dlq/dismiss/", {"event_ids": [str(uuid4())]}, format="json"
        ).status_code
        == 403
    )


@pytest.mark.django_db
def test_dlq_inspect_tail_peek_eof_topic_filter_and_malformed_record(settings):
    settings.KAFKA_BOOTSTRAP_SERVERS = "localhost:9092"
    staff = User.objects.create_user(username="staff_dlq", password="pw", is_staff=True)
    client = APIClient()
    client.force_authenticate(user=staff)

    now = datetime.now(UTC)
    eid_1, bytes_1 = _make_dlq_bytes(
        original_topic=KafkaTopic.JOBS_RAW.value,
        produced_at=now - timedelta(minutes=5),
        raw_payload={"ats_source": "lever", "external_id": "1", "blob": "x" * 700},
    )
    eid_2, bytes_2 = _make_dlq_bytes(
        original_topic=KafkaTopic.JOBS_RESCORE.value,
        produced_at=now - timedelta(minutes=1),
        raw_payload={"resume_profile_uuid": str(uuid4())},
    )

    fake_topic = MagicMock(error=None, partitions={0: MagicMock()})
    fake_consumer = MagicMock()
    fake_consumer.list_topics.return_value = MagicMock(
        topics={KafkaTopic.JOBS_DLQ.value: fake_topic}
    )
    # 3 records at offsets 10, 11, 12 -> high watermark is 13 (last offset = 12)
    fake_consumer.get_watermark_offsets.return_value = (10, 13)
    fake_consumer.poll.side_effect = [
        _make_kafka_msg(payload_bytes=bytes_1, partition=0, offset=10),
        _make_kafka_msg(payload_bytes=b"not-valid-json", partition=0, offset=11),
        _make_kafka_msg(payload_bytes=bytes_2, partition=0, offset=12),
    ]

    fake_redis = MagicMock()
    # 3 replayed keys + 3 dismissed keys
    fake_redis.mget.return_value = [
        None,
        "2026-11-25T12:00:00+00:00",
        None,
        None,
        None,
        "2026-11-25T12:05:00+00:00",
    ]
    fake_redis.ttl.return_value = 0

    with (
        patch.object(dlq_inspector, "Consumer", return_value=fake_consumer),
        patch.object(dlq_inspector, "_get_redis_client", return_value=fake_redis),
    ):
        res = client.get("/api/v1/system/dlq/?limit=10")

    assert res.status_code == 200
    body = res.json()
    assert body["total_count"] == 3
    assert body["returned_count"] == 3
    # Sorted newest-first: eid_2, eid_1, malformed
    assert body["items"][0]["event_id"] == eid_2
    assert body["items"][1]["event_id"] == eid_1
    assert body["items"][1]["payload_truncated"] is True
    assert body["items"][2]["error_type"] == "MalformedDeadLetterEvent"
    assert body["items"][2]["replayable"] is False
    # Exited immediately at high - 1 (3 polls only, no stall) and closed consumer
    assert fake_consumer.poll.call_count == 3
    fake_consumer.close.assert_called_once()

    # Topic filter widens scan window to MAX_DLQ_INSPECT_LIMIT (100) and stops on EOF
    fake_consumer_eof = MagicMock()
    fake_consumer_eof.list_topics.return_value = MagicMock(
        topics={KafkaTopic.JOBS_DLQ.value: fake_topic}
    )
    fake_consumer_eof.get_watermark_offsets.return_value = (0, 200)
    fake_consumer_eof.poll.side_effect = [
        _make_kafka_msg(payload_bytes=bytes_2, partition=0, offset=100),
        _make_kafka_msg(
            payload_bytes=b"",
            partition=0,
            offset=101,
            error_code=KafkaError._PARTITION_EOF,
        ),
    ]
    with (
        patch.object(dlq_inspector, "Consumer", return_value=fake_consumer_eof),
        patch.object(dlq_inspector, "_get_redis_client", return_value=None),
    ):
        res_filtered = client.get(
            f"/api/v1/system/dlq/?limit=5&original_topic={KafkaTopic.JOBS_RESCORE.value}"
        )
    assert res_filtered.status_code == 200
    assigned_tp = fake_consumer_eof.assign.call_args.args[0][0]
    assert assigned_tp.offset == 100  # 200 - MAX_DLQ_INSPECT_LIMIT (100)
    assert res_filtered.json()["returned_count"] == 1
    fake_consumer_eof.close.assert_called_once()


@pytest.mark.django_db
def test_dlq_replay_dry_run_batch_skip_explicit_rereplay_flush_and_cooldown(settings):
    settings.KAFKA_BOOTSTRAP_SERVERS = "localhost:9092"
    staff = User.objects.create_user(
        username="staff_replay", password="pw", is_staff=True
    )
    client = APIClient()
    client.force_authenticate(user=staff)

    now = datetime.now(UTC)
    eid_raw, bytes_raw = _make_dlq_bytes(
        original_topic=KafkaTopic.JOBS_RAW.value,
        produced_at=now - timedelta(minutes=1),
        raw_payload={
            "ats_source": "greenhouse",
            "external_id": "abc-1",
            "title": "SWE",
        },
    )
    eid_already, bytes_already = _make_dlq_bytes(
        original_topic=KafkaTopic.JOBS_ENRICHED.value,
        produced_at=now - timedelta(minutes=2),
        raw_payload=json.dumps({"ats_source": "lever", "external_id": "abc-2"}),
    )
    eid_bad_topic, bytes_bad_topic = _make_dlq_bytes(
        original_topic=KafkaTopic.JOBS_ALERTS.value,
        produced_at=now - timedelta(minutes=3),
        raw_payload={"alert": True},
    )

    def _make_consumer(*_args, **_kwargs):
        fake_topic = MagicMock(error=None, partitions={0: MagicMock()})
        consumer = MagicMock()
        consumer.list_topics.return_value = MagicMock(
            topics={KafkaTopic.JOBS_DLQ.value: fake_topic}
        )
        consumer.get_watermark_offsets.return_value = (0, 3)
        consumer.poll.side_effect = [
            _make_kafka_msg(payload_bytes=bytes_bad_topic, partition=0, offset=0),
            _make_kafka_msg(payload_bytes=bytes_already, partition=0, offset=1),
            _make_kafka_msg(payload_bytes=bytes_raw, partition=0, offset=2),
        ]
        return consumer

    # 1. Dry-run batch skips already_replayed and non-allowlisted topic without acquiring lock
    fake_redis = MagicMock()
    # 3 replayed keys + 3 dismissed keys
    fake_redis.mget.return_value = [
        None,
        "2026-11-25T10:00:00+00:00",
        None,
        None,
        None,
        None,
    ]

    with (
        patch.object(dlq_inspector, "Consumer", side_effect=_make_consumer),
        patch.object(dlq_inspector, "_get_redis_client", return_value=fake_redis),
        patch.object(dlq_inspector, "Producer") as mock_producer_cls,
    ):
        dry_res = client.post(
            "/api/v1/system/dlq/replay/",
            {"dry_run": True, "limit": 10},
            format="json",
        )
    assert dry_res.status_code == 200
    dry_body = dry_res.json()
    assert dry_body["dry_run"] is True
    assert dry_body["matched_count"] == 1
    assert dry_body["skipped_count"] == 2
    mock_producer_cls.assert_not_called()
    fake_redis.set.assert_not_called()

    # 2. Execute batch publishes exact inner raw_payload (never DeadLetterEvent wrapper)
    produced_calls: list[dict] = []

    class _FakeProducer:
        def produce(self, *, topic, key, value, on_delivery):
            produced_calls.append({"topic": topic, "key": key, "value": value})
            on_delivery(None, MagicMock())

        def poll(self, _timeout):
            return 0

        def flush(self, _timeout):
            return 0

    fake_redis.set.return_value = True
    fake_redis.pipeline.return_value = MagicMock()

    with (
        patch.object(dlq_inspector, "Consumer", side_effect=_make_consumer),
        patch.object(dlq_inspector, "_get_redis_client", return_value=fake_redis),
        patch.object(dlq_inspector, "Producer", return_value=_FakeProducer()),
    ):
        exec_res = client.post(
            "/api/v1/system/dlq/replay/",
            {"dry_run": False, "limit": 10},
            format="json",
        )
    assert exec_res.status_code == 200
    exec_body = exec_res.json()
    assert exec_body["replayed_count"] == 1
    assert exec_body["skipped_count"] == 2
    assert exec_body["failed_count"] == 0
    assert len(produced_calls) == 1
    assert produced_calls[0]["topic"] == KafkaTopic.JOBS_RAW.value
    assert produced_calls[0]["key"] == b"greenhouse:abc-1"
    published_json = json.loads(produced_calls[0]["value"].decode("utf-8"))
    assert published_json["external_id"] == "abc-1"
    assert "original_topic" not in published_json  # Not wrapped in DeadLetterEvent!

    # 3. Explicit event_ids allows intentional re-replay of already-replayed string raw_payload
    produced_calls.clear()
    with (
        patch.object(dlq_inspector, "Consumer", side_effect=_make_consumer),
        patch.object(dlq_inspector, "_get_redis_client", return_value=fake_redis),
        patch.object(dlq_inspector, "Producer", return_value=_FakeProducer()),
    ):
        explicit_res = client.post(
            "/api/v1/system/dlq/replay/",
            {"dry_run": False, "event_ids": [eid_already]},
            format="json",
        )
    assert explicit_res.status_code == 200
    assert explicit_res.json()["replayed_count"] == 1
    assert produced_calls[0]["key"] == b"lever:abc-2"

    # 4. Unconfirmed flush timeout marks item failed and releases cooldown lock
    class _StalledProducer:
        def produce(self, *, topic, key, value, on_delivery):
            # Never invokes on_delivery
            return None

        def poll(self, _timeout):
            return 0

        def flush(self, _timeout):
            return 1

    fake_redis.delete.reset_mock()
    with (
        patch.object(dlq_inspector, "Consumer", side_effect=_make_consumer),
        patch.object(dlq_inspector, "_get_redis_client", return_value=fake_redis),
        patch.object(dlq_inspector, "Producer", return_value=_StalledProducer()),
    ):
        stalled_res = client.post(
            "/api/v1/system/dlq/replay/",
            {"dry_run": False, "event_ids": [eid_raw]},
            format="json",
        )
    assert stalled_res.status_code == 200
    assert stalled_res.json()["replayed_count"] == 0
    assert stalled_res.json()["failed_count"] == 1
    fake_redis.delete.assert_called_once_with(dlq_inspector.DLQ_REPLAY_COOLDOWN_KEY)

    # 5. Cooldown active (including ttl < 0 recovery) returns 429 + Retry-After
    fake_redis_locked = MagicMock()
    fake_redis_locked.mget.return_value = [None, None, None, None, None, None]
    fake_redis_locked.set.return_value = False
    fake_redis_locked.ttl.return_value = -1

    with (
        patch.object(dlq_inspector, "Consumer", side_effect=_make_consumer),
        patch.object(
            dlq_inspector, "_get_redis_client", return_value=fake_redis_locked
        ),
    ):
        locked_res = client.post(
            "/api/v1/system/dlq/replay/",
            {"dry_run": False, "event_ids": [eid_raw]},
            format="json",
        )
    assert locked_res.status_code == 429
    assert locked_res["Retry-After"] == str(dlq_inspector.DLQ_REPLAY_COOLDOWN_SECONDS)
    fake_redis_locked.expire.assert_called_once_with(
        dlq_inspector.DLQ_REPLAY_COOLDOWN_KEY,
        dlq_inspector.DLQ_REPLAY_COOLDOWN_SECONDS,
    )

    # 6. No eligible items does NOT acquire cooldown lock
    fake_redis_noop = MagicMock()
    fake_redis_noop.mget.return_value = [None, None]
    with (
        patch.object(dlq_inspector, "Consumer", side_effect=_make_consumer),
        patch.object(dlq_inspector, "_get_redis_client", return_value=fake_redis_noop),
    ):
        noop_res = client.post(
            "/api/v1/system/dlq/replay/",
            {"dry_run": False, "event_ids": [eid_bad_topic]},
            format="json",
        )
    assert noop_res.status_code == 200
    assert noop_res.json()["replayed_count"] == 0
    assert noop_res.json()["skipped_count"] == 1
    fake_redis_noop.set.assert_not_called()


@pytest.mark.django_db
def test_dlq_dismiss_skips_batch_replay_and_clears_degraded_dlq_health(settings):
    settings.KAFKA_BOOTSTRAP_SERVERS = "localhost:9092"
    staff = User.objects.create_user(
        username="staff_dismiss", password="pw", is_staff=True
    )
    client = APIClient()
    client.force_authenticate(user=staff)

    eid_1, bytes_1 = _make_dlq_bytes(
        original_topic=KafkaTopic.JOBS_RAW.value,
        raw_payload={"ats_source": "manual", "external_id": "smoke-1"},
    )

    # 1. POST /api/v1/system/dlq/dismiss/ persists 7-day marker and invalidates DLQ health cache
    fake_pipe = MagicMock()
    fake_redis = MagicMock()
    fake_redis.pipeline.return_value = fake_pipe

    with patch.object(dlq_inspector, "_get_redis_client", return_value=fake_redis):
        res = client.post(
            "/api/v1/system/dlq/dismiss/",
            {"event_ids": [eid_1, "malformed-0-1"]},
            format="json",
        )
    assert res.status_code == 200
    assert res.json()["dismissed_count"] == 2
    assert fake_pipe.set.call_count == 2
    fake_pipe.delete.assert_called_once_with(dlq_inspector.DLQ_CACHE_KEY)

    # 2. Batch replay skips already_dismissed entry without touching Kafka Producer
    def _make_consumer(*_args, **_kwargs):
        fake_topic = MagicMock(error=None, partitions={0: MagicMock()})
        consumer = MagicMock()
        consumer.list_topics.return_value = MagicMock(
            topics={KafkaTopic.JOBS_DLQ.value: fake_topic}
        )
        consumer.get_watermark_offsets.return_value = (0, 1)
        consumer.poll.side_effect = [
            _make_kafka_msg(payload_bytes=bytes_1, partition=0, offset=0),
        ]
        return consumer

    fake_redis_dismissed = MagicMock()
    fake_redis_dismissed.mget.return_value = [None, "2026-11-25T15:00:00+00:00"]

    with (
        patch.object(dlq_inspector, "Consumer", side_effect=_make_consumer),
        patch.object(
            dlq_inspector, "_get_redis_client", return_value=fake_redis_dismissed
        ),
    ):
        dry_res = client.post(
            "/api/v1/system/dlq/replay/",
            {"dry_run": True, "limit": 10},
            format="json",
        )
    assert dry_res.status_code == 200
    assert dry_res.json()["matched_count"] == 0
    assert dry_res.json()["skipped_count"] == 1
    assert dry_res.json()["items"][0]["reason"] == "already_dismissed"

    # 3. get_dlq_health() subtracts dismissed recent entry -> flips back to healthy (0 recent)
    fake_status_redis = MagicMock()
    fake_status_redis.get.return_value = None
    with (
        patch.object(
            system_status, "_get_redis_client", return_value=fake_status_redis
        ),
        patch.object(
            system_status,
            "_probe_kafka_dlq_health",
            return_value={"status": "warning", "recent_24h_count": 1, "total_count": 1},
        ),
        patch.object(dlq_inspector, "Consumer", side_effect=_make_consumer),
        patch.object(
            dlq_inspector, "_get_redis_client", return_value=fake_redis_dismissed
        ),
    ):
        dlq_health = system_status.get_dlq_health()
    assert dlq_health == {"status": "healthy", "recent_24h_count": 0, "total_count": 1}
