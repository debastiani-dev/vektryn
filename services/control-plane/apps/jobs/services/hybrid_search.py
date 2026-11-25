from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
import json
import logging
from typing import Literal
from uuid import UUID

from django.conf import settings
from django.contrib.postgres.search import SearchQuery, SearchRank
from django.db import connection, transaction
from django.db.models import Case, FloatField, QuerySet, Value, When
from google import genai
from google.genai import types
from pgvector.django import CosineDistance
import redis

from apps.jobs.models.jobs import JobPosting
from vektryn_contracts.events import EMBEDDING_DIMENSIONS

logger = logging.getLogger(__name__)

SearchMode = Literal["hybrid", "keyword"]

RRF_K = 60
RRF_CANDIDATE_LIMIT = 200
MAX_SEARCH_QUERY_CHARS = 500
MIN_SEMANTIC_QUERY_CHARS = 2
EMBEDDING_CACHE_TTL_SECONDS = 300
EMBEDDING_TIMEOUT_MS = 4000
HNSW_EF_SEARCH = 200
PLACEHOLDER_GEMINI_KEYS = frozenset({"", "your_gemini_api_key_here"})


@dataclass(frozen=True)
class HybridSearchResult:
    rrf_scores: dict[UUID, float]
    search_mode: SearchMode


def normalize_search_query(raw: str | None) -> str:
    if not raw:
        return ""
    return " ".join(raw.split()).strip()[:MAX_SEARCH_QUERY_CHARS]


def extract_search_query(query_params: Mapping[str, str]) -> str:
    raw = query_params.get("search") or query_params.get("q") or ""
    return normalize_search_query(raw)


def _get_redis_client() -> redis.Redis | None:
    redis_url = (getattr(settings, "REDIS_URL", "") or "").strip()
    if not redis_url:
        return None
    try:
        return redis.Redis.from_url(
            redis_url,
            decode_responses=True,
            socket_connect_timeout=0.5,
            socket_timeout=0.5,
        )
    except Exception as exc:
        logger.debug("Redis unavailable for search embedding cache: %s", exc)
        return None


def _embedding_cache_key(normalized_lower: str) -> str:
    digest = hashlib.sha256(normalized_lower.encode("utf-8")).hexdigest()
    return f"vektryn:search_embed:v1:{digest}"


def _load_cached_embedding(cache_key: str) -> list[float] | None:
    client = _get_redis_client()
    if client is None:
        return None
    try:
        raw = client.get(cache_key)
        if not isinstance(raw, str) or not raw:
            return None
        parsed = json.loads(raw)
        if isinstance(parsed, list) and len(parsed) == EMBEDDING_DIMENSIONS:
            return [float(v) for v in parsed]
    except Exception as exc:
        logger.debug("Failed reading cached search embedding: %s", exc)
    return None


def _store_cached_embedding(cache_key: str, embedding: list[float]) -> None:
    client = _get_redis_client()
    if client is None:
        return
    try:
        client.set(
            cache_key,
            json.dumps(embedding),
            ex=EMBEDDING_CACHE_TTL_SECONDS,
        )
    except Exception as exc:
        logger.debug("Failed writing cached search embedding: %s", exc)


def embed_search_query(query: str) -> list[float] | None:
    normalized = normalize_search_query(query)
    if len(normalized) < MIN_SEMANTIC_QUERY_CHARS:
        return None

    cache_key = _embedding_cache_key(normalized.lower())
    cached = _load_cached_embedding(cache_key)
    if cached is not None:
        return cached

    api_key = (getattr(settings, "GEMINI_API_KEY", "") or "").strip()
    if api_key in PLACEHOLDER_GEMINI_KEYS:
        return None

    try:
        client = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(timeout=EMBEDDING_TIMEOUT_MS),
        )
        res = client.models.embed_content(
            model=settings.GEMINI_EMBEDDING_MODEL,
            contents=normalized,
            config=types.EmbedContentConfig(
                task_type="RETRIEVAL_QUERY",
                output_dimensionality=EMBEDDING_DIMENSIONS,
            ),
        )
        embeddings = getattr(res, "embeddings", None)
        if not embeddings:
            return None
        vector = [float(v) for v in embeddings[0].values]
        if len(vector) != EMBEDDING_DIMENSIONS:
            return None
    except Exception as exc:
        logger.warning(
            "Hybrid search query embedding failed; falling back to keyword-only: %s",
            exc,
        )
        return None

    _store_cached_embedding(cache_key, vector)
    return vector


def _fetch_keyword_ranks(
    base_jobs: QuerySet[JobPosting],
    query: str,
) -> dict[UUID, int]:
    ts_query = SearchQuery(query, config="english", search_type="websearch")
    uuids = list(
        base_jobs.filter(search_vector=ts_query)
        .annotate(text_rank=SearchRank("search_vector", ts_query))
        .order_by("-text_rank", "-created_at")
        .values_list("uuid", flat=True)[:RRF_CANDIDATE_LIMIT]
    )
    return {job_id: rank for rank, job_id in enumerate(uuids, start=1)}


def _fetch_semantic_ranks(
    base_jobs: QuerySet[JobPosting],
    query_embedding: list[float],
    min_similarity: float,
) -> dict[UUID, int]:
    max_distance = max(0.0, min(2.0, 1.0 - min_similarity))
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT set_config('hnsw.iterative_scan', 'relaxed_order', true), "
                "set_config('hnsw.ef_search', %s, true)",
                [str(HNSW_EF_SEARCH)],
            )
        uuids = list(
            base_jobs.filter(embedding__isnull=False)
            .annotate(vec_distance=CosineDistance("embedding", query_embedding))
            .filter(vec_distance__lte=max_distance)
            .order_by("vec_distance")
            .values_list("uuid", flat=True)[:RRF_CANDIDATE_LIMIT]
        )
    return {job_id: rank for rank, job_id in enumerate(uuids, start=1)}


def fuse_rrf_scores(
    keyword_ranks: Mapping[UUID, int],
    semantic_ranks: Mapping[UUID, int],
    *,
    k: int = RRF_K,
) -> dict[UUID, float]:
    fused: dict[UUID, float] = {}
    for job_id in keyword_ranks.keys() | semantic_ranks.keys():
        score = 0.0
        if job_id in keyword_ranks:
            score += 1.0 / (k + keyword_ranks[job_id])
        if job_id in semantic_ranks:
            score += 1.0 / (k + semantic_ranks[job_id])
        fused[job_id] = score
    return fused


def execute_hybrid_search(
    base_jobs: QuerySet[JobPosting],
    query: str,
) -> HybridSearchResult:
    normalized = normalize_search_query(query)
    if not normalized:
        return HybridSearchResult(rrf_scores={}, search_mode="keyword")

    keyword_ranks = _fetch_keyword_ranks(base_jobs, normalized)
    query_embedding = embed_search_query(normalized)
    if query_embedding is None:
        return HybridSearchResult(
            rrf_scores=fuse_rrf_scores(keyword_ranks, {}),
            search_mode="keyword",
        )

    min_similarity = float(getattr(settings, "HYBRID_SEARCH_MIN_SIMILARITY", 0.60))
    semantic_ranks = _fetch_semantic_ranks(base_jobs, query_embedding, min_similarity)
    return HybridSearchResult(
        rrf_scores=fuse_rrf_scores(keyword_ranks, semantic_ranks),
        search_mode="hybrid",
    )


def annotate_rrf_score(
    queryset: QuerySet,
    rrf_scores: Mapping[UUID, float],
    *,
    id_field: str = "uuid",
) -> QuerySet:
    if not rrf_scores:
        return queryset.none().annotate(rrf_score=Value(0.0, output_field=FloatField()))
    whens = [
        When(**{id_field: job_id}, then=Value(score))
        for job_id, score in rrf_scores.items()
    ]
    return queryset.filter(**{f"{id_field}__in": list(rrf_scores.keys())}).annotate(
        rrf_score=Case(*whens, default=Value(0.0), output_field=FloatField())
    )
