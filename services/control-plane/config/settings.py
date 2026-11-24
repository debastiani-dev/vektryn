from enum import StrEnum
import os
from pathlib import Path
from urllib.parse import unquote, urlparse

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

    gemini_api_key: str = ""
    gemini_embedding_model: str = "gemini-embedding-001"
    gemini_scoring_model: str = "gemini-4-hydrogen"
    gemini_fallback_scoring_model: str = "gemini-3.5-flash-lite"

    stream_auth_secret: str = Field(
        default="",
        validation_alias=AliasChoices(
            "STREAM_AUTH_SECRET", "DJANGO_SECRET_KEY", "SECRET_KEY"
        ),
    )
    storage_backend: str = ""
    local_storage_dir: Path = REPO_ROOT / ".local_storage"
    gcs_resumes_bucket: str = Field(
        default="",
        validation_alias=AliasChoices("GCS_RESUMES_BUCKET", "GCS_BUCKET_RESUMES"),
    )


def _build_database_config(settings: ControlPlaneSettings) -> dict[str, object]:
    if settings.database_url.strip():
        parsed = urlparse(settings.database_url.strip())
        env_has_database_url = bool(os.environ.get("DATABASE_URL", "").strip())
        host = (
            settings.postgres_host
            if not env_has_database_url and os.environ.get("POSTGRES_HOST")
            else (parsed.hostname or settings.postgres_host)
        )
        port = (
            settings.postgres_port
            if not env_has_database_url and os.environ.get("POSTGRES_PORT")
            else (parsed.port or settings.postgres_port)
        )
        name = (
            settings.postgres_db
            if not env_has_database_url and os.environ.get("POSTGRES_DB")
            else (parsed.path.lstrip("/") or settings.postgres_db)
        )
        user = (
            settings.postgres_user
            if not env_has_database_url and os.environ.get("POSTGRES_USER")
            else (unquote(parsed.username or "") or settings.postgres_user)
        )
        password = (
            settings.postgres_password
            if not env_has_database_url and os.environ.get("POSTGRES_PASSWORD")
            else (unquote(parsed.password or "") or settings.postgres_password)
        )
        return {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": name,
            "USER": user,
            "PASSWORD": password,
            "HOST": host,
            "PORT": port,
            "CONN_MAX_AGE": 60,
        }
    return {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": settings.postgres_db,
        "USER": settings.postgres_user,
        "PASSWORD": settings.postgres_password,
        "HOST": settings.postgres_host,
        "PORT": settings.postgres_port,
        "CONN_MAX_AGE": 60,
    }


env = ControlPlaneSettings()

SECRET_KEY = env.django_secret_key
DEBUG = env.django_debug
ALLOWED_HOSTS = [h.strip() for h in env.django_allowed_hosts.split(",") if h.strip()]

CSRF_TRUSTED_ORIGINS = [
    o.strip() for o in env.csrf_trusted_origins.split(",") if o.strip()
]

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

STREAM_AUTH_SECRET = env.stream_auth_secret.strip() or SECRET_KEY
STORAGE_BACKEND = env.storage_backend.strip().lower()
LOCAL_STORAGE_DIR = env.local_storage_dir
GCS_RESUMES_BUCKET = env.gcs_resumes_bucket.strip()

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


def _choices(enum_cls: type[StrEnum]) -> list[tuple[str, str]]:
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
