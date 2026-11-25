import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
import inspect
import logging
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from prometheus_client import make_asgi_app

from stream_edge.api.alerts_sse import router as alerts_router
from stream_edge.api.ingest import router as ingest_router
from stream_edge.api.internal import router as internal_router
from stream_edge.clients.gcs import SnapshotStorageClient
from stream_edge.clients.kafka import KafkaEventProducer
from stream_edge.config import settings
from stream_edge.telemetry import configure_sentry, configure_tracing

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


def _configure_telemetry(app: FastAPI) -> None:
    app.mount("/metrics", make_asgi_app())
    configure_sentry("vektryn-stream-edge")

    if not os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip():
        return

    configure_tracing("vektryn-stream-edge")
    FastAPIInstrumentor.instrument_app(app, excluded_urls="/health,/metrics")


async def _shutdown_producer(producer: KafkaEventProducer) -> None:
    close_fn = getattr(producer, "close", None)
    if callable(close_fn):
        result = close_fn()
        if inspect.isawaitable(result):
            await result
        return

    flush_fn = getattr(producer, "flush", None)
    if callable(flush_fn):
        await asyncio.to_thread(flush_fn)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    producer = KafkaEventProducer()
    storage = SnapshotStorageClient()

    app.state.kafka_producer = producer
    app.state.snapshot_storage = storage
    logger.info("Stream Edge initialized (Kafka producer & snapshot storage ready)")

    try:
        yield
    finally:
        await _shutdown_producer(producer)
        logger.info("Stream Edge shut down cleanly")


app = FastAPI(
    title="Vektryn Stream Edge",
    version="0.2.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=getattr(
        settings,
        "cors_allowed_origins_list",
        ["http://localhost:5173", "http://127.0.0.1:5173"],
    ),
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

app.include_router(ingest_router)
app.include_router(alerts_router)
app.include_router(internal_router)
_configure_telemetry(app)


@app.get("/health", tags=["health"])
async def healthcheck() -> dict[str, str]:
    return {"status": "ok", "service": "stream-edge"}
