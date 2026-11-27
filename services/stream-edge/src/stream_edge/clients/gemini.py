import asyncio
from collections import OrderedDict
from contextlib import suppress
from decimal import Decimal
import hashlib
import logging
import time
from typing import Callable, TypeVar

from google import genai
from google.genai import errors as genai_errors
from google.genai import types
import httpx
from pydantic import BaseModel, Field
import redis

from stream_edge.clients.notifications import persist_user_ai_notification
from stream_edge.config import settings
from vektryn_contracts import (
    COOLDOWN_QUOTA_SECONDS,
    COOLDOWN_TIER_DENIED_SECONDS,
    EMBEDDING_DIMENSIONS,
    GEMINI_EMBEDDING_MODEL,
    PAUSE_INVALID_KEY_SECONDS,
    PAUSE_PAYMENT_REQUIRED_SECONDS,
    ContractType,
    GeminiErrorAction,
    GeminiModelAttempt,
    NotificationKind,
    RegionEligibility,
    SalaryPeriod,
    SeniorityLevel,
    ThinkingLevelName,
    clamp_thinking_level,
    classify_gemini_error,
    gemini_invalid_key_pause_key,
    gemini_model_cooldown_key,
    gemini_payment_pause_key,
    resolve_model_chain,
)

logger = logging.getLogger(__name__)
T = TypeVar("T")

_THINKING_LEVEL_ENUM: dict[ThinkingLevelName, types.ThinkingLevel] = {
    "minimal": types.ThinkingLevel.MINIMAL,
    "low": types.ThinkingLevel.LOW,
    "medium": types.ThinkingLevel.MEDIUM,
    "high": types.ThinkingLevel.HIGH,
}


_NO_SDK_RETRIES = types.HttpRetryOptions(attempts=1)


def _is_deadline_exceeded(exc: genai_errors.APIError) -> bool:
    status = (getattr(exc, "status", None) or "").upper()
    return exc.code == 504 or status == "DEADLINE_EXCEEDED"


def build_thinking_config(level: ThinkingLevelName) -> types.ThinkingConfig:
    return types.ThinkingConfig(thinking_level=_THINKING_LEVEL_ENUM[level])


class ExtractedJobMetadata(BaseModel):
    seniority: SeniorityLevel = SeniorityLevel.UNKNOWN
    contract_type: ContractType = ContractType.UNKNOWN
    region_eligibility: list[RegionEligibility] = Field(default_factory=list)
    salary_min: Decimal | None = None
    salary_max: Decimal | None = None
    salary_currency: str = ""
    salary_period: SalaryPeriod | None = None
    tech_stack: list[str] = Field(default_factory=list)


class ResumeGapEvaluation(BaseModel):
    fit_score: int = Field(ge=0, le=100)
    matched_skills: list[str] = Field(default_factory=list)
    missing_keywords: list[str] = Field(default_factory=list)
    talking_points: list[str] = Field(default_factory=list)
    gap_summary: str = ""
    fit_highlights: list[str] = Field(default_factory=list)
    watchout_note: str = ""


class UserScoringPausedError(RuntimeError):
    """Raised when a user's BYOK key is invalid, credits depleted, or all models exhausted."""

    def __init__(self, action: GeminiErrorAction, message: str) -> None:
        self.action = action
        super().__init__(message)


def build_resume_fit_prompt(
    *,
    resume_text: str,
    resume_skills: list[str],
    job_title: str,
    company_name: str,
    job_description: str,
    job_stack: list[str],
) -> str:
    return (
        "Evaluate how well this candidate's resume matches the target software engineering role, "
        "focusing on giving the candidate a clear, practical assessment of why this role is "
        "(or isn't) worth applying to.\n\n"
        "Strict grounding rules:\n"
        "- Base every claim strictly on evidence present in the resume and job description. "
        "Never fabricate experience, tools, or metrics.\n"
        "- Calibrate against the role's actual engineering discipline "
        "(backend, fullstack, frontend, data, platform, infra, ML, mobile, etc.) "
        "rather than assuming a backend-only role.\n\n"
        "Return:\n"
        "- fit_score: integer 0-100 calibrated objectively on core technical stack overlap, "
        "system/architecture scope, seniority alignment, and domain fit "
        "(85-100: direct strong fit; 70-84: solid fit worth applying; "
        "50-69: partial/stretch fit; 0-49: weak fit).\n"
        "- matched_skills: normalized lowercase skills/technologies present in both "
        "the resume and the job requirements.\n"
        "- missing_keywords: genuinely important skills/tools requested in the job "
        "that are absent or weak in the resume (omit trivial or optional nice-to-haves).\n"
        "- talking_points: 3-4 concise, concrete interview talking points that connect "
        "specific projects, architectures, or outcomes from the candidate's resume "
        "directly to this role's top responsibilities.\n"
        "- gap_summary: 1-2 punchy opening sentences summarizing the overall fit verdict "
        "directly for the candidate (use second person 'you/your', no generic filler) "
        "explaining why this role is or isn't worth applying to.\n"
        "- fit_highlights: 2-4 concise, evidence-backed reasons to apply (1 crisp sentence each) "
        "connecting specific experience, domain background, seniority/scope, and transferable "
        "stack strengths from the resume directly to what this role needs.\n"
        "- watchout_note: 1-2 brief sentences concisely summarizing the most relevant material "
        "gap(s) or positioning watch-out(s) to address when applying (or empty string '' if none "
        "are material, since missing_keywords is displayed separately).\n\n"
        f"CANDIDATE RESUME SKILLS: {', '.join(resume_skills)}\n"
        f"CANDIDATE RESUME:\n{resume_text[:10000]}\n\n"
        f"TARGET ROLE: {job_title} @ {company_name}\n"
        f"TARGET STACK: {', '.join(job_stack)}\n"
        f"JOB DESCRIPTION:\n{job_description[:10000]}"
    )


class GeminiStreamClient:
    """Platform-key Gemini client reserved exclusively for job ingestion/enrichment."""

    PLACEHOLDER_KEYS = {"", "your_gemini_api_key_here"}
    RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
    REQUEST_TIMEOUT_MS = 30_000

    def __init__(self, api_key: str = settings.gemini_api_key) -> None:
        cleaned = (api_key or "").strip()
        if cleaned in self.PLACEHOLDER_KEYS:
            raise ValueError(
                "A valid GEMINI_API_KEY is required for the enrichment worker."
            )
        self._client = genai.Client(
            api_key=cleaned,
            http_options=types.HttpOptions(
                timeout=self.REQUEST_TIMEOUT_MS,
                retry_options=_NO_SDK_RETRIES,
            ),
        )

    @classmethod
    def _call_with_retry(cls, fn: Callable[[], T], max_attempts: int = 3) -> T:
        last_exc: genai_errors.APIError | None = None
        for attempt in range(max_attempts):
            try:
                return fn()
            except genai_errors.APIError as exc:
                last_exc = exc
                if (
                    exc.code not in cls.RETRYABLE_STATUS_CODES
                    or attempt == max_attempts - 1
                ):
                    raise
                time.sleep(2.0 * (2**attempt))
        raise last_exc  # type: ignore[misc]

    def _enrichment_chain(self) -> list[tuple[str, ThinkingLevelName]]:
        primary = (settings.gemini_enrichment_model or "").strip()
        fallback = (settings.gemini_enrichment_fallback_model or "").strip()
        if primary:
            chain: list[tuple[str, ThinkingLevelName]] = [
                (primary, clamp_thinking_level(primary, "minimal"))
            ]
            if fallback and fallback != primary:
                chain.append((fallback, clamp_thinking_level(fallback, "low")))
            return chain
        return [
            (attempt.model_id, attempt.thinking_level)
            for attempt in resolve_model_chain("enrichment")
        ]

    def _generate_structured_sync(
        self,
        *,
        prompt: str,
        schema: type[BaseModel],
    ) -> tuple[str, str]:
        chain = self._enrichment_chain()
        last_exc: genai_errors.APIError | None = None
        for idx, (model_id, thinking_level) in enumerate(chain):
            config = types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=schema,
                thinking_config=build_thinking_config(thinking_level),
            )
            try:
                res = self._call_with_retry(
                    lambda m=model_id, c=config: self._client.models.generate_content(
                        model=m,
                        contents=prompt,
                        config=c,
                    ),
                    max_attempts=3,
                )
                return res.text, model_id
            except genai_errors.APIError as exc:
                last_exc = exc
                if exc.code in self.RETRYABLE_STATUS_CODES and idx < len(chain) - 1:
                    continue
                raise
        raise last_exc  # type: ignore[misc]

    async def extract_job_metadata(
        self,
        *,
        title: str,
        company_name: str,
        location_raw: str,
        description_clean: str,
    ) -> ExtractedJobMetadata:
        prompt = (
            "Analyze this software engineering job posting and extract structured metadata.\n"
            "- Map seniority and legal/tax contract_type (clt, pj, b2b_contractor, w2, c2c, eor, unknown).\n"
            "- Identify all eligible regions in region_eligibility (e.g., brazil, latam, worldwide, north_america, europe, emea, apac, restricted).\n"
            "- Extract salary_min, salary_max, 3-letter ISO salary_currency, and salary_period only if explicitly stated.\n"
            "- Extract normalized lowercase tech_stack tags (languages, frameworks, databases, brokers, cloud, DevOps).\n\n"
            f"Title: {title}\n"
            f"Company: {company_name}\n"
            f"Location: {location_raw}\n\n"
            f"Description:\n{description_clean[:12000]}"
        )
        raw_json, _ = await asyncio.to_thread(
            self._generate_structured_sync,
            prompt=prompt,
            schema=ExtractedJobMetadata,
        )
        return ExtractedJobMetadata.model_validate_json(raw_json)

    def _embed_sync(self, text: str) -> list[float]:
        model = (
            settings.gemini_embedding_model or GEMINI_EMBEDDING_MODEL
        ).strip() or GEMINI_EMBEDDING_MODEL
        res = self._call_with_retry(
            lambda: self._client.models.embed_content(
                model=model,
                contents=text[:12000],
                config=types.EmbedContentConfig(
                    task_type="RETRIEVAL_DOCUMENT",
                    output_dimensionality=EMBEDDING_DIMENSIONS,
                ),
            )
        )
        return list(res.embeddings[0].values)

    async def embed_job_text(
        self,
        *,
        title: str,
        company_name: str,
        tech_stack: list[str],
        description_clean: str,
    ) -> list[float]:
        composite = (
            f"Role: {title} at {company_name}\n"
            f"Stack: {', '.join(tech_stack)}\n\n"
            f"{description_clean}"
        )
        return await asyncio.to_thread(self._embed_sync, composite)


class UserGeminiScoringManager:
    """Per-user BYOK Gemini scoring manager with bounded LRU client cache & Redis cooldowns."""

    MAX_CACHED_CLIENTS = 16
    REQUEST_TIMEOUT_MS = 45_000

    def __init__(self, *, max_cached_clients: int = MAX_CACHED_CLIENTS) -> None:
        self._max_cached = max(1, int(max_cached_clients))
        self._clients: OrderedDict[tuple[int, str], genai.Client] = OrderedDict()

    def _get_client(self, user_id: int, api_key: str) -> genai.Client:
        key_hash = hashlib.sha256(api_key.encode("utf-8")).hexdigest()[:12]
        cache_key = (int(user_id), key_hash)
        cached = self._clients.get(cache_key)
        if cached is not None:
            self._clients.move_to_end(cache_key)
            return cached

        client = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(
                timeout=self.REQUEST_TIMEOUT_MS,
                retry_options=_NO_SDK_RETRIES,
            ),
        )
        self._clients[cache_key] = client
        while len(self._clients) > self._max_cached:
            self._clients.popitem(last=False)
        return client

    @staticmethod
    def _get_redis() -> redis.Redis | None:
        redis_url = (settings.redis_url or "").strip()
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
            logger.debug("Redis unavailable for matcher BYOK state: %s", exc)
            return None

    @staticmethod
    def _close_redis(client: redis.Redis | None) -> None:
        if client is not None:
            with suppress(Exception):
                client.close()

    def get_pause_state(self, user_id: int) -> GeminiErrorAction | None:
        client = self._get_redis()
        if client is None:
            return None
        try:
            invalid_val, payment_val = client.mget(
                [
                    gemini_invalid_key_pause_key(user_id),
                    gemini_payment_pause_key(user_id),
                ]
            )
            if invalid_val:
                return GeminiErrorAction.INVALID_KEY
            if payment_val:
                return GeminiErrorAction.PAYMENT_REQUIRED
            return None
        except Exception as exc:
            logger.debug(
                "Failed reading matcher pause state for user=%s: %s", user_id, exc
            )
            return None
        finally:
            self._close_redis(client)

    def _get_cooled_models(
        self, user_id: int, chain: list[GeminiModelAttempt]
    ) -> set[str]:
        client = self._get_redis()
        if client is None or not chain:
            return set()
        try:
            keys = [gemini_model_cooldown_key(user_id, a.model_id) for a in chain]
            values = client.mget(keys)
            return {
                attempt.model_id
                for attempt, value in zip(chain, values, strict=False)
                if value
            }
        except Exception as exc:
            logger.debug(
                "Failed reading matcher cooldowns for user=%s: %s", user_id, exc
            )
            return set()
        finally:
            self._close_redis(client)

    def _mark_cooldown(self, user_id: int, model_id: str, ttl_seconds: int) -> None:
        client = self._get_redis()
        if client is None:
            return
        try:
            client.set(
                gemini_model_cooldown_key(user_id, model_id),
                "1",
                ex=max(60, int(ttl_seconds)),
            )
        except Exception as exc:
            logger.debug(
                "Failed setting matcher cooldown user=%s model=%s: %s",
                user_id,
                model_id,
                exc,
            )
        finally:
            self._close_redis(client)

    def _mark_pause(self, user_id: int, action: GeminiErrorAction) -> None:
        client = self._get_redis()
        if client is None:
            return
        try:
            if action is GeminiErrorAction.INVALID_KEY:
                client.set(
                    gemini_invalid_key_pause_key(user_id),
                    "1",
                    ex=PAUSE_INVALID_KEY_SECONDS,
                )
            elif action is GeminiErrorAction.PAYMENT_REQUIRED:
                client.set(
                    gemini_payment_pause_key(user_id),
                    "1",
                    ex=PAUSE_PAYMENT_REQUIRED_SECONDS,
                )
        except Exception as exc:
            logger.debug(
                "Failed setting matcher pause user=%s action=%s: %s",
                user_id,
                action,
                exc,
            )
        finally:
            self._close_redis(client)

    @staticmethod
    def _emit_terminal_notification(
        user_id: int,
        action: GeminiErrorAction,
        attempted_models: list[str] | None = None,
    ) -> None:
        if action is GeminiErrorAction.INVALID_KEY:
            persist_user_ai_notification(
                user_id=user_id,
                kind=NotificationKind.AI_KEY_INVALID,
                title="Gemini API key invalid or revoked",
                body=(
                    "Google AI Studio rejected your Gemini API key during AI match scoring. "
                    "Open Account Settings -> AI & API Key to paste a valid key."
                ),
                payload={"reason": "invalid_key", "source": "matcher-worker"},
            )
        elif action is GeminiErrorAction.PAYMENT_REQUIRED:
            persist_user_ai_notification(
                user_id=user_id,
                kind=NotificationKind.AI_QUOTA_EXHAUSTED,
                title="Gemini API prepayment credits depleted",
                body=(
                    "Your Google AI Studio account reported depleted prepayment credits or "
                    "disabled billing during AI match scoring. Top up credits or update your "
                    "key in Account Settings."
                ),
                payload={"reason": "payment_required", "source": "matcher-worker"},
            )
        elif action is GeminiErrorAction.QUOTA_EXHAUSTED:
            persist_user_ai_notification(
                user_id=user_id,
                kind=NotificationKind.AI_QUOTA_EXHAUSTED,
                title="Gemini API quota exhausted",
                body=(
                    "All eligible Gemini models in your fallback chain hit quota limits during "
                    "AI match scoring. Stage 1 vector matching continues and Stage 2 will resume "
                    "automatically once cooldowns expire."
                ),
                payload={
                    "reason": "quota_exhausted",
                    "source": "matcher-worker",
                    "models": attempted_models or [],
                },
            )

    def _handle_attempt_api_error(
        self,
        *,
        user_id: int,
        attempt: GeminiModelAttempt,
        exc: genai_errors.APIError,
        retry_idx: int,
        has_fallback: bool,
    ) -> tuple[bool, bool]:
        """Classify a model APIError. Returns (should_retry_same_model, hit_quota_or_tier)."""
        action = classify_gemini_error(
            exc.code,
            getattr(exc, "status", None),
            getattr(exc, "message", str(exc)),
            getattr(exc, "details", None),
            model_paid_only=attempt.paid_only,
        )
        if action in (
            GeminiErrorAction.INVALID_KEY,
            GeminiErrorAction.PAYMENT_REQUIRED,
        ):
            self._mark_pause(user_id, action)
            self._emit_terminal_notification(user_id, action)
            raise UserScoringPausedError(
                action, f"User {user_id} scoring stopped ({action.value})."
            ) from exc
        if action is GeminiErrorAction.TIER_DENIED:
            self._mark_cooldown(user_id, attempt.model_id, COOLDOWN_TIER_DENIED_SECONDS)
            return False, True
        if action is GeminiErrorAction.QUOTA_EXHAUSTED:
            self._mark_cooldown(user_id, attempt.model_id, COOLDOWN_QUOTA_SECONDS)
            return False, True
        if action is GeminiErrorAction.TRANSIENT:
            if _is_deadline_exceeded(exc) and has_fallback:
                return False, False
            if retry_idx == 0:
                time.sleep(1.0)
                return True, False
            return False, False
        raise exc

    def _try_score_model(
        self,
        *,
        client: genai.Client,
        user_id: int,
        attempt: GeminiModelAttempt,
        prompt: str,
        has_fallback: bool,
    ) -> tuple[ResumeGapEvaluation | None, bool, Exception | None]:
        config = types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=ResumeGapEvaluation,
            thinking_config=build_thinking_config(attempt.thinking_level),
        )
        last_exc: Exception | None = None
        for retry_idx in range(2):
            try:
                response = client.models.generate_content(
                    model=attempt.model_id,
                    contents=prompt,
                    config=config,
                )
                return (
                    ResumeGapEvaluation.model_validate_json(response.text),
                    False,
                    None,
                )
            except (httpx.TimeoutException, TimeoutError) as exc:
                return None, False, exc
            except genai_errors.APIError as exc:
                last_exc = exc
                should_retry, hit_quota = self._handle_attempt_api_error(
                    user_id=user_id,
                    attempt=attempt,
                    exc=exc,
                    retry_idx=retry_idx,
                    has_fallback=has_fallback,
                )
                if not should_retry:
                    return None, hit_quota, last_exc
        return None, False, last_exc

    def _resolve_eligible_scoring_chain(
        self,
        *,
        user_id: int,
        preferred_model: str,
        allow_model_fallback: bool,
    ) -> tuple[list[GeminiModelAttempt], list[GeminiModelAttempt]]:
        paused = self.get_pause_state(user_id)
        if paused is not None:
            raise UserScoringPausedError(
                paused, f"User {user_id} AI scoring paused ({paused.value})."
            )
        chain = resolve_model_chain(
            "scoring", preferred_model, allow_fallback=allow_model_fallback
        )
        cooled = self._get_cooled_models(user_id, chain)
        eligible = [attempt for attempt in chain if attempt.model_id not in cooled]
        if not eligible:
            self._emit_terminal_notification(
                user_id,
                GeminiErrorAction.QUOTA_EXHAUSTED,
                [a.model_id for a in chain],
            )
            raise UserScoringPausedError(
                GeminiErrorAction.QUOTA_EXHAUSTED,
                f"All models on cooldown for user {user_id}.",
            )
        return chain, eligible

    def evaluate_resume_fit_sync(
        self,
        *,
        user_id: int,
        api_key: str,
        preferred_model: str,
        allow_model_fallback: bool,
        resume_text: str,
        resume_skills: list[str],
        job_title: str,
        company_name: str,
        job_description: str,
        job_stack: list[str],
    ) -> tuple[ResumeGapEvaluation, str]:
        chain, eligible = self._resolve_eligible_scoring_chain(
            user_id=user_id,
            preferred_model=preferred_model,
            allow_model_fallback=allow_model_fallback,
        )
        prompt = build_resume_fit_prompt(
            resume_text=resume_text,
            resume_skills=resume_skills,
            job_title=job_title,
            company_name=company_name,
            job_description=job_description,
            job_stack=job_stack,
        )
        client = self._get_client(user_id, api_key)
        saw_quota_or_tier = False
        last_exc: Exception | None = None

        for idx, attempt in enumerate(eligible):
            evaluation, hit_quota, exc = self._try_score_model(
                client=client,
                user_id=user_id,
                attempt=attempt,
                prompt=prompt,
                has_fallback=idx < len(eligible) - 1,
            )
            if evaluation is not None:
                return evaluation, attempt.model_id
            saw_quota_or_tier = saw_quota_or_tier or hit_quota
            if exc is not None:
                last_exc = exc

        if saw_quota_or_tier:
            self._emit_terminal_notification(
                user_id,
                GeminiErrorAction.QUOTA_EXHAUSTED,
                [a.model_id for a in chain],
            )
            raise UserScoringPausedError(
                GeminiErrorAction.QUOTA_EXHAUSTED,
                f"All models exhausted for user {user_id}.",
            )
        raise RuntimeError(
            f"All Gemini scoring attempts failed for user {user_id}."
        ) from last_exc
