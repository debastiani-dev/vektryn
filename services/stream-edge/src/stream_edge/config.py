from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# services/stream-edge/src/stream_edge/config.py -> repo root is 4 parents up
REPO_ROOT = Path(__file__).resolve().parents[4]


class StreamEdgeSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    service_name: str = "stream-edge"
    debug: bool = True
    cors_allowed_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # PostgreSQL (pgvector)
    postgres_db: str = "vektryn"
    postgres_user: str = "vektryn"
    postgres_password: str = "vektryn_dev_password"
    postgres_host: str = Field(default="localhost")
    postgres_port: int = 5432

    # Redis (SHA-256 deduplication locks)
    redis_url: str = "redis://localhost:6379/0"
    dedup_ttl_seconds: int = 60 * 60 * 24 * 30  # 30 days

    # Apache Kafka (KRaft)
    kafka_bootstrap_servers: str = "localhost:29092"
    kafka_enrichment_group_id: str = "vektryn-enrichment-worker"
    kafka_matcher_group_id: str = "vektryn-matcher-worker"

    # Storage: local directory in dev; set GCS_BUCKET_NAME in GCP prod
    local_storage_dir: Path = REPO_ROOT / ".local_storage"
    gcs_bucket_name: str = ""

    # Gemini API
    gemini_api_key: str = ""
    gemini_embedding_model: str = "gemini-embedding-001"
    gemini_scoring_model: str = "gemini-4-hydrogen"
    gemini_fallback_scoring_model: str = "gemini-3.5-flash-lite"

    # Two-stage matching thresholds
    cosine_similarity_threshold: float = 0.58

    # ATS Job Board Tokens (comma-separated in .env, e.g. GREENHOUSE_BOARD_TOKENS=gitlab,stripe)
    greenhouse_board_tokens: str = ""
    ashby_board_tokens: str = ""

    @property
    def greenhouse_boards(self) -> list[str]:
        return [b.strip() for b in self.greenhouse_board_tokens.split(",") if b.strip()]

    @property
    def ashby_boards(self) -> list[str]:
        return [b.strip() for b in self.ashby_board_tokens.split(",") if b.strip()]

    @property
    def postgres_dsn(self) -> str:
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


settings = StreamEdgeSettings()