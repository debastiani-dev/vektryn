import logging
import os

from prometheus_client import Counter, Gauge, Histogram, start_http_server

logger = logging.getLogger(__name__)

INGEST_JOBS_TOTAL = Counter(
    "vektryn_ingest_jobs_total",
    "Total job postings accepted by stream-edge /ingest/jobs",
    ["ats_source", "status"],
)

SSE_ACTIVE_CLIENTS = Gauge(
    "vektryn_sse_active_clients",
    "Currently connected SSE /stream/alerts clients",
)

SSE_ALERTS_SENT_TOTAL = Counter(
    "vektryn_sse_alerts_sent_total",
    "Total live match alert events streamed over SSE",
)

GEMINI_CALLS_TOTAL = Counter(
    "vektryn_gemini_calls_total",
    "Total Gemini API calls by operation, model, and status",
    ["operation", "model", "status"],
)

GEMINI_LATENCY_SECONDS = Histogram(
    "vektryn_gemini_latency_seconds",
    "Gemini API call latency in seconds",
    ["operation", "model"],
    buckets=(0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 20.0, 45.0),
)

WORKER_MESSAGES_TOTAL = Counter(
    "vektryn_worker_messages_total",
    "Total Kafka worker messages handled by worker and outcome",
    ["worker", "outcome"],
)

WORKER_PROCESSING_SECONDS = Histogram(
    "vektryn_worker_processing_seconds",
    "End-to-end Kafka message processing duration in seconds",
    ["worker"],
    buckets=(0.05, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0),
)

MATCH_ALERTS_EMITTED_TOTAL = Counter(
    "vektryn_match_alerts_emitted_total",
    "Total high-fit JobMatchAlertEvent messages published to jobs.alerts",
)


def start_worker_metrics_server(default_port: int) -> None:
    """Starts a lightweight Prometheus /metrics HTTP endpoint for Kafka workers."""
    raw_port = os.getenv("METRICS_PORT", str(default_port)).strip()
    if not raw_port or raw_port == "0":
        return
    try:
        port = int(raw_port)
        start_http_server(port)
        logger.info("Worker Prometheus metrics server listening on :%d", port)
    except OSError as exc:
        logger.warning(
            "Unable to start worker Prometheus metrics server on :%s: %s",
            raw_port,
            exc,
        )
