"""Per-user BYOK Gemini credential resolution, Redis cooldowns, notifications, and tiered execution."""

from contextlib import suppress
from dataclasses import dataclass
from datetime import timedelta
import logging
import time
from typing import Any

from django.conf import settings
from django.utils import timezone
from google import genai
from google.genai import errors as genai_errors
from google.genai import types
import httpx
import redis

from apps.base.models.notification import Notification
from apps.base.models.user_profile import UserProfile
from vektryn_contracts import (
    AUTO_GEMINI_MODEL,
    COOLDOWN_QUOTA_SECONDS,
    COOLDOWN_TIER_DENIED_SECONDS,
    EMBEDDING_DIMENSIONS,
    GEMINI_EMBEDDING_MODEL,
    NOTIFICATION_THROTTLE_SECONDS,
    PAUSE_INVALID_KEY_SECONDS,
    PAUSE_PAYMENT_REQUIRED_SECONDS,
    BYOKCryptoError,
    BYOKKeyNotConfiguredError,
    GeminiErrorAction,
    GeminiModelAttempt,
    GeminiTask,
    NotificationKind,
    ThinkingLevelName,
    all_user_gemini_state_keys,
    classify_gemini_error,
    decrypt_api_key,
    encrypt_api_key,
    gemini_invalid_key_pause_key,
    gemini_model_cooldown_key,
    gemini_notification_throttle_key,
    gemini_payment_pause_key,
    mask_api_key_last4,
    resolve_model_chain,
)

logger = logging.getLogger(__name__)

_THINKING_LEVEL_ENUM: dict[ThinkingLevelName, types.ThinkingLevel] = {
    "minimal": types.ThinkingLevel.MINIMAL,
    "low": types.ThinkingLevel.LOW,
    "medium": types.ThinkingLevel.MEDIUM,
    "high": types.ThinkingLevel.HIGH,
}


class BYOKError(RuntimeError):
    """Base error for user-scoped BYOK Gemini failures."""

    code: str = "byok_error"
    http_status: int = 503

    def __init__(
        self, message: str, *, code: str | None = None, http_status: int | None = None
    ) -> None:
        if code is not None:
            self.code = code
        if http_status is not None:
            self.http_status = http_status
        super().__init__(message)


class BYOKMissingError(BYOKError):
    code = "byok_missing"
    http_status = 400


class BYOKInvalidKeyError(BYOKError):
    code = "byok_invalid"
    http_status = 403


class BYOKQuotaExhaustedError(BYOKError):
    code = "byok_quota_exhausted"
    http_status = 429

    def __init__(self, message: str, *, payment_required: bool = False) -> None:
        self.payment_required = payment_required
        super().__init__(message)


class BYOKStorageUnavailableError(BYOKError):
    code = "byok_unavailable"
    http_status = 503


class BYOKTransientError(BYOKError):
    code = "byok_transient"
    http_status = 503


@dataclass(frozen=True)
class UserGeminiCredentials:
    user_id: int
    api_key: str
    preferred_model: str
    allow_model_fallback: bool


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
        logger.debug("Redis unavailable for BYOK state: %s", exc)
        return None


def _close_redis(client: redis.Redis | None) -> None:
    if client is not None:
        with suppress(Exception):
            client.close()


def clear_user_gemini_state(user_id: int) -> None:
    """Clear all Gemini cooldowns, pause keys, and notification throttles for a user."""
    client = _get_redis_client()
    if client is None:
        return
    try:
        keys = all_user_gemini_state_keys(user_id)
        if keys:
            client.delete(*keys)
    except Exception as exc:
        logger.debug(
            "Failed clearing Gemini BYOK Redis state for user=%s: %s", user_id, exc
        )
    finally:
        _close_redis(client)


def get_user_pause_state(user_id: int) -> GeminiErrorAction | None:
    """Return INVALID_KEY or PAYMENT_REQUIRED if the user is currently paused in Redis."""
    client = _get_redis_client()
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
        logger.debug("Failed checking Gemini pause state for user=%s: %s", user_id, exc)
        return None
    finally:
        _close_redis(client)


def _get_cooled_models(user_id: int, attempts: list[GeminiModelAttempt]) -> set[str]:
    if not attempts:
        return set()
    client = _get_redis_client()
    if client is None:
        return set()
    try:
        keys = [
            gemini_model_cooldown_key(user_id, attempt.model_id) for attempt in attempts
        ]
        values = client.mget(keys)
        return {
            attempt.model_id
            for attempt, value in zip(attempts, values, strict=False)
            if value
        }
    except Exception as exc:
        logger.debug("Failed reading Gemini cooldowns for user=%s: %s", user_id, exc)
        return set()
    finally:
        _close_redis(client)


def mark_model_cooldown(user_id: int, model_id: str, ttl_seconds: int) -> None:
    client = _get_redis_client()
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
            "Failed setting model cooldown for user=%s model=%s: %s",
            user_id,
            model_id,
            exc,
        )
    finally:
        _close_redis(client)


def mark_user_pause(user_id: int, action: GeminiErrorAction) -> None:
    client = _get_redis_client()
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
            "Failed setting pause state for user=%s action=%s: %s", user_id, action, exc
        )
    finally:
        _close_redis(client)


def emit_user_ai_notification(
    user_id: int,
    *,
    kind: NotificationKind,
    title: str,
    body: str,
    payload: dict[str, Any] | None = None,
) -> bool:
    """Create a throttled Notification (at most once per 6h per user+kind)."""
    client = _get_redis_client()
    throttled_by_redis = False
    if client is not None:
        try:
            acquired = client.set(
                gemini_notification_throttle_key(user_id, kind),
                "1",
                nx=True,
                ex=NOTIFICATION_THROTTLE_SECONDS,
            )
            if not acquired:
                return False
            throttled_by_redis = True
        except Exception as exc:
            logger.debug(
                "Redis throttle failed for AI notification user=%s: %s", user_id, exc
            )
        finally:
            _close_redis(client)

    if not throttled_by_redis:
        cutoff = timezone.now() - timedelta(seconds=NOTIFICATION_THROTTLE_SECONDS)
        if Notification.objects.filter(
            user_id=user_id,
            kind=kind.value,
            created_at__gte=cutoff,
        ).exists():
            return False

    Notification.objects.create(
        user_id=user_id,
        kind=kind.value,
        title=title[:255],
        body=body,
        payload=payload or {},
    )
    return True


def _notify_invalid_key(user_id: int) -> None:
    emit_user_ai_notification(
        user_id,
        kind=NotificationKind.AI_KEY_INVALID,
        title="Gemini API key invalid or revoked",
        body=(
            "Google AI Studio rejected your Gemini API key. Open Account Settings -> "
            "AI & API Key to paste a valid key using AI Studio's Copy key button."
        ),
        payload={"reason": "invalid_key"},
    )


def _notify_payment_required(user_id: int) -> None:
    emit_user_ai_notification(
        user_id,
        kind=NotificationKind.AI_QUOTA_EXHAUSTED,
        title="Gemini API prepayment credits depleted",
        body=(
            "Your Google AI Studio account reported depleted prepayment credits or "
            "disabled billing. Top up credits in Google AI Studio or update your key "
            "in Account Settings to resume AI features."
        ),
        payload={"reason": "payment_required"},
    )


def _notify_quota_exhausted(user_id: int, attempted_models: list[str]) -> None:
    emit_user_ai_notification(
        user_id,
        kind=NotificationKind.AI_QUOTA_EXHAUSTED,
        title="Gemini API quota exhausted",
        body=(
            "All eligible Gemini models in your fallback chain hit quota limits. "
            "AI features will resume automatically once cooldowns expire, or you can "
            "update your key or model preference in Account Settings."
        ),
        payload={"reason": "quota_exhausted", "models": attempted_models},
    )


def encrypt_user_api_key(plaintext: str) -> tuple[str, str]:
    """Encrypt a normalized plaintext key using BYOK_ENCRYPTION_KEY and return (ciphertext, last4)."""
    encryption_key = (getattr(settings, "BYOK_ENCRYPTION_KEY", "") or "").strip()
    try:
        ciphertext = encrypt_api_key(plaintext, encryption_key)
    except BYOKKeyNotConfiguredError as exc:
        raise BYOKStorageUnavailableError(
            "API key storage is temporarily unavailable on this server."
        ) from exc
    return ciphertext, mask_api_key_last4(plaintext)


def user_has_gemini_api_key(user) -> bool:
    user_pk = getattr(user, "pk", None)
    if not user_pk:
        return False
    return (
        UserProfile.objects.filter(user_id=user_pk)
        .exclude(gemini_api_key_encrypted="")
        .exists()
    )


def resolve_user_gemini_credentials(user) -> UserGeminiCredentials:
    """Resolve and decrypt the user's mandatory BYOK Gemini API key (no platform fallback)."""
    user_pk = getattr(user, "pk", None)
    if not user_pk:
        raise BYOKMissingError(
            "Add your Google AI Studio Gemini API key in Account Settings to use AI features."
        )

    profile = UserProfile.objects.filter(user_id=user_pk).first()
    if profile is None or not profile.has_gemini_api_key:
        raise BYOKMissingError(
            "Add your Google AI Studio Gemini API key in Account Settings to use AI features."
        )

    encryption_key = (getattr(settings, "BYOK_ENCRYPTION_KEY", "") or "").strip()
    try:
        api_key = decrypt_api_key(profile.gemini_api_key_encrypted, encryption_key)
    except BYOKKeyNotConfiguredError as exc:
        raise BYOKStorageUnavailableError(
            "API key encryption is not configured on this server."
        ) from exc
    except BYOKCryptoError as exc:
        raise BYOKInvalidKeyError(
            "Your stored Gemini API key could not be decrypted. Please re-enter it in Account Settings."
        ) from exc

    return UserGeminiCredentials(
        user_id=int(user_pk),
        api_key=api_key,
        preferred_model=profile.preferred_gemini_model or AUTO_GEMINI_MODEL,
        allow_model_fallback=bool(profile.allow_model_fallback),
    )


def build_thinking_config(thinking_level: ThinkingLevelName) -> types.ThinkingConfig:
    return types.ThinkingConfig(thinking_level=_THINKING_LEVEL_ENUM[thinking_level])


def _raise_if_paused(user_id: int) -> None:
    paused = get_user_pause_state(user_id)
    if paused is GeminiErrorAction.INVALID_KEY:
        raise BYOKInvalidKeyError(
            "Your Gemini API key was rejected by Google AI Studio. Update it in Account Settings."
        )
    if paused is GeminiErrorAction.PAYMENT_REQUIRED:
        raise BYOKQuotaExhaustedError(
            "Your Google AI Studio prepayment credits are depleted or billing is required.",
            payment_required=True,
        )


def _handle_terminal_error(
    user_id: int, action: GeminiErrorAction, exc: Exception
) -> None:
    if action is GeminiErrorAction.INVALID_KEY:
        if user_id:
            mark_user_pause(user_id, GeminiErrorAction.INVALID_KEY)
            _notify_invalid_key(user_id)
        raise BYOKInvalidKeyError(
            "Your Gemini API key is invalid or revoked. Update it in Account Settings."
        ) from exc
    if action is GeminiErrorAction.PAYMENT_REQUIRED:
        if user_id:
            mark_user_pause(user_id, GeminiErrorAction.PAYMENT_REQUIRED)
            _notify_payment_required(user_id)
        raise BYOKQuotaExhaustedError(
            "Your Google AI Studio prepayment credits are depleted. Add credits or update your API key in Account Settings.",
            payment_required=True,
        ) from exc


def _remaining_timeout_ms(deadline: float | None, cap_ms: int) -> int:
    if deadline is None:
        return max(1000, cap_ms)
    remaining_ms = int((deadline - time.monotonic()) * 1000)
    if remaining_ms < 500:
        raise BYOKTransientError("Gemini request timed out before completing.")
    return max(1000, min(cap_ms, remaining_ms))


def _resolve_execution_context(
    user,
    *,
    genai_client: genai.Client | None,
) -> tuple[int, str, str, bool]:
    if genai_client is not None:
        user_pk = int(getattr(user, "pk", 0) or 0)
        profile = (
            UserProfile.objects.filter(user_id=user_pk).first() if user_pk else None
        )
        preferred = (
            profile.preferred_gemini_model
            if profile is not None and profile.preferred_gemini_model
            else AUTO_GEMINI_MODEL
        )
        allow_fallback = (
            bool(profile.allow_model_fallback) if profile is not None else True
        )
        return user_pk, "", preferred, allow_fallback

    creds = resolve_user_gemini_credentials(user)
    return (
        creds.user_id,
        creds.api_key,
        creds.preferred_model,
        creds.allow_model_fallback,
    )


_NO_SDK_RETRIES = types.HttpRetryOptions(attempts=1)


def _is_deadline_exceeded(exc: genai_errors.APIError) -> bool:
    status = (getattr(exc, "status", None) or "").upper()
    return exc.code == 504 or status == "DEADLINE_EXCEEDED"


def _build_user_client(
    *,
    api_key: str,
    timeout_ms: int,
    genai_client: genai.Client | None,
) -> genai.Client:
    if genai_client is not None:
        return genai_client
    return genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(
            timeout=timeout_ms,
            retry_options=_NO_SDK_RETRIES,
        ),
    )


def _parse_embedding_vector(response: object) -> list[float]:
    embeddings = getattr(response, "embeddings", None)
    if not embeddings:
        raise BYOKTransientError("Gemini embedding returned no vectors.")
    vector = [float(v) for v in embeddings[0].values]
    if len(vector) != EMBEDDING_DIMENSIONS:
        raise BYOKTransientError(f"Unexpected embedding dimensionality: {len(vector)}")
    return vector


def _handle_embed_api_error(
    *,
    user_id: int,
    embed_model: str,
    exc: genai_errors.APIError,
    attempt_idx: int,
    attempts_allowed: int,
    deadline: float | None,
) -> None:
    """Classify an embed APIError; sleep to retry if transient, otherwise raise."""
    action = classify_gemini_error(
        exc.code,
        getattr(exc, "status", None),
        getattr(exc, "message", str(exc)),
        getattr(exc, "details", None),
        model_paid_only=False,
    )
    if action in (GeminiErrorAction.INVALID_KEY, GeminiErrorAction.PAYMENT_REQUIRED):
        _handle_terminal_error(user_id, action, exc)
    if action is GeminiErrorAction.QUOTA_EXHAUSTED:
        if user_id:
            _notify_quota_exhausted(user_id, [embed_model])
        raise BYOKQuotaExhaustedError(
            "Your Gemini API embedding quota is temporarily exhausted. Please try again later."
        ) from exc
    sleep_seconds = min(1.0 * (2**attempt_idx), 2.0)
    has_budget = deadline is None or (deadline - time.monotonic()) > sleep_seconds + 0.5
    if (
        action is GeminiErrorAction.TRANSIENT
        and attempt_idx < attempts_allowed - 1
        and has_budget
    ):
        time.sleep(sleep_seconds)
        return
    raise BYOKTransientError(f"Gemini embedding request failed ({exc.code}).") from exc


def execute_user_gemini_embed(
    *,
    user,
    contents: str,
    task_type: str,
    timeout_ms: int = 5000,
    max_attempts: int = 2,
    genai_client: genai.Client | None = None,
    deadline: float | None = None,
) -> list[float]:
    """Generate a 768-dim embedding using the user's mandatory BYOK key."""
    user_id, api_key, _, _ = _resolve_execution_context(user, genai_client=genai_client)
    if user_id:
        _raise_if_paused(user_id)

    embed_model = (
        getattr(settings, "GEMINI_EMBEDDING_MODEL", GEMINI_EMBEDDING_MODEL)
        or GEMINI_EMBEDDING_MODEL
    )
    last_exc: Exception | None = None
    attempts_allowed = max(1, int(max_attempts))

    for attempt_idx in range(attempts_allowed):
        effective_timeout = _remaining_timeout_ms(deadline, timeout_ms)
        client = _build_user_client(
            api_key=api_key,
            timeout_ms=effective_timeout,
            genai_client=genai_client,
        )
        try:
            response = client.models.embed_content(
                model=embed_model,
                contents=contents,
                config=types.EmbedContentConfig(
                    task_type=task_type,
                    output_dimensionality=EMBEDDING_DIMENSIONS,
                ),
            )
            return _parse_embedding_vector(response)
        except genai_errors.APIError as exc:
            last_exc = exc
            _handle_embed_api_error(
                user_id=user_id,
                embed_model=embed_model,
                exc=exc,
                attempt_idx=attempt_idx,
                attempts_allowed=attempts_allowed,
                deadline=deadline,
            )

    raise BYOKTransientError("Gemini embedding request failed.") from last_exc


def _invoke_single_attempt(
    *,
    client: genai.Client,
    attempt: GeminiModelAttempt,
    contents: str,
    system_instruction: str | None,
    response_mime_type: str | None,
    response_schema: object | None,
) -> object:
    config_kwargs: dict[str, Any] = {
        "thinking_config": build_thinking_config(attempt.thinking_level),
    }
    if system_instruction is not None:
        config_kwargs["system_instruction"] = system_instruction
    if response_mime_type is not None:
        config_kwargs["response_mime_type"] = response_mime_type
    if response_schema is not None:
        config_kwargs["response_schema"] = response_schema
    return client.models.generate_content(
        model=attempt.model_id,
        contents=contents,
        config=types.GenerateContentConfig(**config_kwargs),
    )


def _handle_generate_api_error(
    *,
    user_id: int,
    attempt: GeminiModelAttempt,
    exc: genai_errors.APIError,
    retry_idx: int,
    max_transient_retries: int,
    deadline: float,
    has_fallback: bool,
) -> tuple[bool, bool, Exception | None]:
    """Return (should_retry, hit_quota_or_tier, transient_exc)."""
    action = classify_gemini_error(
        exc.code,
        getattr(exc, "status", None),
        getattr(exc, "message", str(exc)),
        getattr(exc, "details", None),
        model_paid_only=attempt.paid_only,
    )
    if action in (GeminiErrorAction.INVALID_KEY, GeminiErrorAction.PAYMENT_REQUIRED):
        _handle_terminal_error(user_id, action, exc)
    if action is GeminiErrorAction.TIER_DENIED:
        if user_id:
            mark_model_cooldown(user_id, attempt.model_id, COOLDOWN_TIER_DENIED_SECONDS)
        return False, True, None
    if action is GeminiErrorAction.QUOTA_EXHAUSTED:
        if user_id:
            mark_model_cooldown(user_id, attempt.model_id, COOLDOWN_QUOTA_SECONDS)
        return False, True, None
    if action is GeminiErrorAction.TRANSIENT:
        if _is_deadline_exceeded(exc) and has_fallback:
            return False, False, exc
        if retry_idx < max_transient_retries and (deadline - time.monotonic()) > 2.5:
            time.sleep(0.8)
            return True, False, exc
        return False, False, exc
    raise BYOKTransientError(
        f"Gemini request failed on {attempt.model_id} ({exc.code})."
    ) from exc


def _try_generate_model(
    *,
    user_id: int,
    api_key: str,
    attempt: GeminiModelAttempt,
    contents: str,
    system_instruction: str | None,
    response_mime_type: str | None,
    response_schema: object | None,
    deadline: float,
    per_attempt_timeout_ms: int,
    max_transient_retries: int,
    has_fallback: bool,
    genai_client: genai.Client | None,
) -> tuple[object | None, bool, Exception | None]:
    last_transient_exc: Exception | None = None
    for retry_idx in range(max(0, max_transient_retries) + 1):
        effective_timeout = _remaining_timeout_ms(deadline, per_attempt_timeout_ms)
        client = _build_user_client(
            api_key=api_key,
            timeout_ms=effective_timeout,
            genai_client=genai_client,
        )
        try:
            response = _invoke_single_attempt(
                client=client,
                attempt=attempt,
                contents=contents,
                system_instruction=system_instruction,
                response_mime_type=response_mime_type,
                response_schema=response_schema,
            )
            return response, False, None
        except (httpx.TimeoutException, TimeoutError) as exc:
            return None, False, exc
        except genai_errors.APIError as exc:
            should_retry, hit_quota, transient_exc = _handle_generate_api_error(
                user_id=user_id,
                attempt=attempt,
                exc=exc,
                retry_idx=retry_idx,
                max_transient_retries=max_transient_retries,
                deadline=deadline,
                has_fallback=has_fallback,
            )
            if transient_exc is not None:
                last_transient_exc = transient_exc
            if not should_retry:
                return None, hit_quota, last_transient_exc
    return None, False, last_transient_exc


def execute_user_gemini_generate(
    *,
    user,
    task: GeminiTask,
    contents: str,
    system_instruction: str | None = None,
    response_mime_type: str | None = None,
    response_schema: object | None = None,
    deadline_seconds: float = 50.0,
    per_attempt_timeout_ms: int = 35000,
    max_transient_retries: int = 1,
    genai_client: genai.Client | None = None,
) -> tuple[object, str]:
    """Execute a tiered Gemini generation call under a single shared deadline."""
    user_id, api_key, preferred_model, allow_fallback = _resolve_execution_context(
        user,
        genai_client=genai_client,
    )
    if user_id:
        _raise_if_paused(user_id)

    chain = resolve_model_chain(task, preferred_model, allow_fallback=allow_fallback)
    cooled = _get_cooled_models(user_id, chain) if user_id else set()
    eligible = [attempt for attempt in chain if attempt.model_id not in cooled]
    if not eligible:
        if user_id:
            _notify_quota_exhausted(user_id, [a.model_id for a in chain])
        raise BYOKQuotaExhaustedError(
            "All eligible Gemini models are temporarily in cooldown due to quota limits."
        )

    deadline = time.monotonic() + max(2.0, float(deadline_seconds))
    saw_quota_or_tier = False
    last_transient_exc: Exception | None = None

    for idx, attempt in enumerate(eligible):
        response, hit_quota, transient_exc = _try_generate_model(
            user_id=user_id,
            api_key=api_key,
            attempt=attempt,
            contents=contents,
            system_instruction=system_instruction,
            response_mime_type=response_mime_type,
            response_schema=response_schema,
            deadline=deadline,
            per_attempt_timeout_ms=per_attempt_timeout_ms,
            max_transient_retries=max_transient_retries,
            has_fallback=idx < len(eligible) - 1,
            genai_client=genai_client,
        )
        if response is not None:
            return response, attempt.model_id
        saw_quota_or_tier = saw_quota_or_tier or hit_quota
        if transient_exc is not None:
            last_transient_exc = transient_exc

    if saw_quota_or_tier and last_transient_exc is None:
        if user_id:
            _notify_quota_exhausted(user_id, [a.model_id for a in chain])
        raise BYOKQuotaExhaustedError(
            "All eligible Gemini models hit quota or tier limits. Try again shortly or update your model settings."
        )

    raise BYOKTransientError(
        "Gemini request failed or timed out across fallback models. Please try again shortly."
    ) from last_transient_exc
