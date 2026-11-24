import asyncio
import json
from unittest.mock import MagicMock, patch
from uuid import uuid4

import httpx
import pytest

from stream_edge.clients.kafka import KafkaEventProducer
from stream_edge.config import StreamEdgeSettings
from stream_edge.main import app
from stream_edge.workers.dlq_replay import replay_dlq
from stream_edge.workers.lifecycle import _MARK_CLOSED_SQL, _is_posting_closed
from stream_edge.workers.matcher import _upsert_job_and_score_sync
from vektryn_contracts import (
    ATSSource,
    DeadLetterEvent,
    EMBEDDING_DIMENSIONS,
    JobEnrichedEvent,
    KafkaTopic,
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
    with patch("stream_edge.clients.kafka.Producer", return_value=fake_confluent_producer):
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
        patch("stream_edge.workers.dlq_replay._collect_dlq_events", return_value=[dlq_item]),
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
            return httpx.Response(200, text="<html>This position has been filled.</html>")
        return httpx.Response(200, text="<html>Senior Python Engineer — Apply now</html>")

    transport = httpx.MockTransport(handler)
    semaphore = asyncio.Semaphore(4)
    async with httpx.AsyncClient(transport=transport) as client:
        assert await _is_posting_closed(client, semaphore, "u1", "https://ex.com/gone") == "u1"
        assert await _is_posting_closed(client, semaphore, "u2", "https://ex.com/filled") == "u2"
        assert await _is_posting_closed(client, semaphore, "u3", "https://ex.com/open") is None


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
