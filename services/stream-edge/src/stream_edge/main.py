import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from stream_edge.api.alerts_sse import router as alerts_router
from stream_edge.api.ingest import router as ingest_router
from stream_edge.clients.gcs import SnapshotStorageClient
from stream_edge.clients.kafka import KafkaEventProducer, ensure_topics_exist
from stream_edge.clients.redis import DedupRedisClient
from stream_edge.config import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await asyncio.to_thread(ensure_topics_exist)
    producer = KafkaEventProducer()
    redis_client = DedupRedisClient()
    storage_client = SnapshotStorageClient()

    app.state.kafka_producer = producer
    app.state.redis_client = redis_client
    app.state.snapshot_storage = storage_client

    yield

    await redis_client.close()
    await asyncio.to_thread(producer.flush, 5.0)


app = FastAPI(
    title="Vektryn Stream Edge",
    description="Async ATS ingestion edge and real-time SSE match alert stream.",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_allowed_origins.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(ingest_router)
app.include_router(alerts_router)


@app.get("/health", tags=["health"])
async def healthcheck() -> dict[str, str]:
    redis_ok = await app.state.redis_client.ping()
    return {
        "status": "ok" if redis_ok else "degraded",
        "service": settings.service_name,
    }