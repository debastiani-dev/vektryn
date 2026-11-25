from collections.abc import Iterable
from enum import StrEnum
import os
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from vektryn_contracts.enums import ContractType, RegionEligibility, SeniorityLevel

BASE_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BASE_DIR.parent.parent


class ControlPlaneSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    django_secret_key: str = Field(
        default="change-me-in-production-use-long-random-string",
        validation_alias=AliasChoices("DJANGO_SECRET_KEY", "SECRET_KEY"),
    )
    django_debug: bool = True
    django_allowed_hosts: str = "localhost,127.0.0.1,control-plane"
    cors_allowed_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    csrf_trusted_origins: str = Field(
        default="http://localhost:3000,http://127.0.0.1:3000",
        validation_alias=AliasChoices(
            "CSRF_TRUSTED_ORIGINS", "DJANGO_CSRF_TRUSTED_ORIGINS"
        ),
    )

    database_url: str = ""
    postgres_db: str = "vektryn"
    postgres_user: str = "vektryn"
    postgres_password: str = "vektryn_dev_password"
    postgres_host: str = Field(default="localhost")
    postgres_port: int = 5432

    redis_url: str = ""

    kafka_bootstrap_servers: str = ""
    kafka_security_protocol: str = ""
    kafka_sasl_mechanism: str = ""
    kafka_sasl_username: str = ""
    kafka_sasl_password: str = ""

    gemini_api_key: str = ""
    gemini_embedding_model: str = "gemini-embedding-001"
    gemini_scoring_model: str = "gemini-4-hydrogen"
    gemini_fallback_scoring_model: str = "gemini-3.5-flash-lite"
    hybrid_search_min_similarity: float = 0.60

    stream_auth_secret: str = Field(
        default="",
        validation_alias=AliasChoices(
            "STREAM_AUTH_SECRET", "DJANGO_SECRET_KEY", "SECRET_KEY"
        ),
    )
    stream_edge_url: str = ""
    ingest_api_key: str = ""
    storage_backend: str = ""
    local_storage_dir: Path = REPO_ROOT / ".local_storage"
    gcs_resumes_bucket: str = Field(
        default="",
        validation_alias=AliasChoices("GCS_RESUMES_BUCKET", "GCS_BUCKET_RESUMES"),
    )


def _pick_db_field(
    *,
    env_has_database_url: bool,
    env_var: str,
    parsed_value: object,
    fallback: object,
) -> object:
    if not env_has_database_url and os.environ.get(env_var):
        return fallback
    return parsed_value or fallback


def _build_database_config(settings: ControlPlaneSettings) -> dict[str, object]:
    if not settings.database_url.strip():
        return {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": settings.postgres_db,
            "USER": settings.postgres_user,
            "PASSWORD": settings.postgres_password,
            "HOST": settings.postgres_host,
            "PORT": settings.postgres_port,
            "CONN_MAX_AGE": 60,
        }

    parsed = urlparse(settings.database_url.strip())
    env_has_database_url = bool(os.environ.get("DATABASE_URL", "").strip())
    db_config: dict[str, object] = {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": _pick_db_field(
            env_has_database_url=env_has_database_url,
            env_var="POSTGRES_DB",
            parsed_value=parsed.path.lstrip("/"),
            fallback=settings.postgres_db,
        ),
        "USER": _pick_db_field(
            env_has_database_url=env_has_database_url,
            env_var="POSTGRES_USER",
            parsed_value=unquote(parsed.username or ""),
            fallback=settings.postgres_user,
        ),
        "PASSWORD": _pick_db_field(
            env_has_database_url=env_has_database_url,
            env_var="POSTGRES_PASSWORD",
            parsed_value=unquote(parsed.password or ""),
            fallback=settings.postgres_password,
        ),
        "HOST": _pick_db_field(
            env_has_database_url=env_has_database_url,
            env_var="POSTGRES_HOST",
            parsed_value=parsed.hostname,
            fallback=settings.postgres_host,
        ),
        "PORT": _pick_db_field(
            env_has_database_url=env_has_database_url,
            env_var="POSTGRES_PORT",
            parsed_value=parsed.port,
            fallback=settings.postgres_port,
        ),
        "CONN_MAX_AGE": 60,
    }
    query_params = parse_qs(parsed.query)
    sslmode = query_params.get("sslmode", [None])[0]
    if sslmode:
        db_config["OPTIONS"] = {"sslmode": sslmode}
    return db_config


env = ControlPlaneSettings()

SECRET_KEY = env.django_secret_key
DEBUG = env.django_debug
ALLOWED_HOSTS = [h.strip() for h in env.django_allowed_hosts.split(",") if h.strip()]

CSRF_TRUSTED_ORIGINS = [
    o.strip() for o in env.csrf_trusted_origins.split(",") if o.strip()
]

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
USE_X_FORWARDED_HOST = True
if not DEBUG:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SESSION_COOKIE_SAMESITE = "Lax"
    CSRF_COOKIE_SAMESITE = "Lax"
    SECURE_CONTENT_TYPE_NOSNIFF = True

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.postgres",
    # Third-party
    "rest_framework",
    "django_filters",
    "corsheaders",
    "drf_spectacular",
    # Domain apps
    "apps.base",
    "apps.jobs",
    "apps.resumes",
    "apps.matching",
    "apps.tracker",
    "apps.analytics",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

DATABASES = {
    "default": _build_database_config(env),
}

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"
    },
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

CORS_ALLOWED_ORIGINS = [
    o.strip() for o in env.cors_allowed_origins.split(",") if o.strip()
]
CORS_ALLOW_CREDENTIALS = True

GEMINI_API_KEY = env.gemini_api_key
GEMINI_EMBEDDING_MODEL = env.gemini_embedding_model
GEMINI_SCORING_MODEL = env.gemini_scoring_model
GEMINI_FALLBACK_SCORING_MODEL = env.gemini_fallback_scoring_model
HYBRID_SEARCH_MIN_SIMILARITY = env.hybrid_search_min_similarity

STREAM_AUTH_SECRET = env.stream_auth_secret.strip() or SECRET_KEY
STREAM_EDGE_URL = env.stream_edge_url.strip().rstrip("/")
INGEST_API_KEY = env.ingest_api_key.strip()
STORAGE_BACKEND = env.storage_backend.strip().lower()
LOCAL_STORAGE_DIR = env.local_storage_dir
GCS_RESUMES_BUCKET = env.gcs_resumes_bucket.strip()
REDIS_URL = env.redis_url.strip()
KAFKA_BOOTSTRAP_SERVERS = env.kafka_bootstrap_servers.strip()
KAFKA_SECURITY_PROTOCOL = env.kafka_security_protocol.strip()
KAFKA_SASL_MECHANISM = env.kafka_sasl_mechanism.strip()
KAFKA_SASL_USERNAME = env.kafka_sasl_username.strip()
KAFKA_SASL_PASSWORD = env.kafka_sasl_password.strip()

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
        "rest_framework.authentication.BasicAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_FILTER_BACKENDS": [
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.OrderingFilter",
    ],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 25,
}


def _choices(enum_cls: Iterable[StrEnum]) -> list[tuple[str, str]]:
    return [
        (member.value, member.name.replace("_", " ").title()) for member in enum_cls
    ]


SPECTACULAR_SETTINGS = {
    "TITLE": "Vektryn Control Plane API",
    "DESCRIPTION": "Tech market intelligence, semantic resume matching, and application tracker API.",
    "VERSION": "0.1.0",
    "COMPONENT_SPLIT_REQUEST": True,
    "ENUM_NAME_OVERRIDES": {
        "SeniorityLevelEnum": _choices(SeniorityLevel),
        "ContractTypeEnum": _choices(ContractType),
        "RegionEligibilityEnum": _choices(RegionEligibility),
    },
}
