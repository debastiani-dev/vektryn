"""Gemini 3.5/3.8/4 model ladder, thinking-level policy, error classification, and Redis keys."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

from vektryn_contracts.enums import NotificationKind

GEMINI_EMBEDDING_MODEL = "gemini-embedding-001"
AUTO_GEMINI_MODEL = "auto"

GEMINI_4_CARBON = "gemini-4-carbon"
GEMINI_4_NEON = "gemini-4-neon"
GEMINI_4_ARGON = "gemini-4-argon"
GEMINI_4_HYDROGEN = "gemini-4-hydrogen"
GEMINI_3_8_FLASH = "gemini-3.8-flash"
GEMINI_3_5_FLASH_LITE = "gemini-3.5-flash-lite"

ThinkingLevelName = Literal["minimal", "low", "medium", "high"]
GeminiTask = Literal["enrichment", "resume_skills", "scoring", "copilot"]

COOLDOWN_QUOTA_SECONDS = 20 * 60
COOLDOWN_TIER_DENIED_SECONDS = 24 * 60 * 60
PAUSE_INVALID_KEY_SECONDS = 6 * 60 * 60
PAUSE_PAYMENT_REQUIRED_SECONDS = 6 * 60 * 60
NOTIFICATION_THROTTLE_SECONDS = 6 * 60 * 60

_THINKING_RANK: dict[ThinkingLevelName, int] = {
    "minimal": 0,
    "low": 1,
    "medium": 2,
    "high": 3,
}


@dataclass(frozen=True)
class GeminiModelSpec:
    model_id: str
    label: str
    paid_only: bool
    min_thinking_level: ThinkingLevelName


@dataclass(frozen=True)
class GeminiModelAttempt:
    model_id: str
    thinking_level: ThinkingLevelName
    paid_only: bool


GEMINI_MODEL_LADDER: tuple[GeminiModelSpec, ...] = (
    GeminiModelSpec(
        model_id=GEMINI_4_CARBON,
        label="Gemini 4 Carbon",
        paid_only=True,
        min_thinking_level="low",
    ),
    GeminiModelSpec(
        model_id=GEMINI_4_NEON,
        label="Gemini 4 Neon",
        paid_only=True,
        min_thinking_level="low",
    ),
    GeminiModelSpec(
        model_id=GEMINI_4_ARGON,
        label="Gemini 4 Argon",
        paid_only=True,
        min_thinking_level="low",
    ),
    GeminiModelSpec(
        model_id=GEMINI_4_HYDROGEN,
        label="Gemini 4 Hydrogen",
        paid_only=False,
        min_thinking_level="low",
    ),
    GeminiModelSpec(
        model_id=GEMINI_3_8_FLASH,
        label="Gemini 3.8 Flash",
        paid_only=False,
        min_thinking_level="low",
    ),
    GeminiModelSpec(
        model_id=GEMINI_3_5_FLASH_LITE,
        label="Gemini 3.5 Flash-Lite",
        paid_only=False,
        min_thinking_level="minimal",
    ),
)

GEMINI_MODEL_MAP: dict[str, GeminiModelSpec] = {
    spec.model_id: spec for spec in GEMINI_MODEL_LADDER
}

VALID_PREFERRED_GEMINI_MODELS: frozenset[str] = frozenset(
    {AUTO_GEMINI_MODEL, *(spec.model_id for spec in GEMINI_MODEL_LADDER)}
)

AUTO_TASK_CHAINS: dict[GeminiTask, tuple[tuple[str, ThinkingLevelName], ...]] = {
    "enrichment": (
        (GEMINI_3_5_FLASH_LITE, "minimal"),
        (GEMINI_3_8_FLASH, "low"),
    ),
    "resume_skills": (
        (GEMINI_3_5_FLASH_LITE, "minimal"),
        (GEMINI_3_8_FLASH, "low"),
        (GEMINI_4_HYDROGEN, "low"),
    ),
    "scoring": (
        (GEMINI_3_5_FLASH_LITE, "low"),
        (GEMINI_3_8_FLASH, "low"),
        (GEMINI_4_HYDROGEN, "low"),
    ),
    "copilot": (
        (GEMINI_4_HYDROGEN, "medium"),
        (GEMINI_3_8_FLASH, "medium"),
        (GEMINI_3_5_FLASH_LITE, "low"),
    ),
}

TASK_DEFAULT_THINKING_LEVEL: dict[GeminiTask, ThinkingLevelName] = {
    "enrichment": "minimal",
    "resume_skills": "minimal",
    "scoring": "low",
    "copilot": "medium",
}


class GeminiErrorAction(StrEnum):
    INVALID_KEY = "invalid_key"
    PAYMENT_REQUIRED = "payment_required"
    TIER_DENIED = "tier_denied"
    QUOTA_EXHAUSTED = "quota_exhausted"
    TRANSIENT = "transient"
    FATAL = "fatal"


_INVALID_KEY_REASONS = frozenset(
    {
        "API_KEY_INVALID",
        "API_KEY_EXPIRED",
        "API_KEY_SERVICE_BLOCKED",
        "API_KEY_HTTP_REFERRER_BLOCKED",
        "API_KEY_IP_ADDRESS_BLOCKED",
    }
)
_PAYMENT_REASONS = frozenset(
    {
        "BILLING_DISABLED",
        "BILLING_NOT_ACTIVE",
        "PREPAYMENT_DEPLETED",
    }
)
_INVALID_KEY_MARKERS = (
    "api key not valid",
    "invalid api key",
    "api_key_invalid",
    "api key expired",
    "api key is invalid",
    "api key has been revoked",
    "api key was reported as leaked",
    "key not found",
)
_PAYMENT_MARKERS = (
    "prepayment credits are depleted",
    "prepayment credits",
    "credits are depleted",
    "insufficient credits",
    "insufficient balance",
    "payment required",
    "billing account",
    "billing is not enabled",
    "billing must be enabled",
    "enable billing",
    "spending cap",
)
_TIER_DENIED_MARKERS = (
    "paid tier",
    "free tier",
    "requires a paid",
    "model is not available",
    "does not have access to",
)


def clamp_thinking_level(
    model_id: str, requested: ThinkingLevelName
) -> ThinkingLevelName:
    """Clamp requested thinking level up to the model's supported minimum."""
    spec = GEMINI_MODEL_MAP.get(model_id)
    minimum: ThinkingLevelName = spec.min_thinking_level if spec is not None else "low"
    if _THINKING_RANK[requested] < _THINKING_RANK[minimum]:
        return minimum
    return requested


def resolve_model_chain(
    task: GeminiTask,
    preferred_model: str = AUTO_GEMINI_MODEL,
    allow_fallback: bool = True,
) -> list[GeminiModelAttempt]:
    """Resolve the ordered (model, thinking_level) chain for a task and user preference."""
    normalized = (preferred_model or AUTO_GEMINI_MODEL).strip()
    if normalized == AUTO_GEMINI_MODEL or normalized not in GEMINI_MODEL_MAP:
        raw_chain = AUTO_TASK_CHAINS[task]
        selected = raw_chain if allow_fallback else raw_chain[:1]
        return [
            GeminiModelAttempt(
                model_id=model_id,
                thinking_level=clamp_thinking_level(model_id, level),
                paid_only=GEMINI_MODEL_MAP[model_id].paid_only,
            )
            for model_id, level in selected
        ]

    start_index = next(
        idx
        for idx, spec in enumerate(GEMINI_MODEL_LADDER)
        if spec.model_id == normalized
    )
    specs = (
        GEMINI_MODEL_LADDER[start_index:]
        if allow_fallback
        else (GEMINI_MODEL_LADDER[start_index],)
    )
    default_level = TASK_DEFAULT_THINKING_LEVEL[task]
    attempts: list[GeminiModelAttempt] = []
    for spec in specs:
        requested_level: ThinkingLevelName = (
            "low"
            if task == "copilot" and spec.model_id == GEMINI_3_5_FLASH_LITE
            else default_level
        )
        attempts.append(
            GeminiModelAttempt(
                model_id=spec.model_id,
                thinking_level=clamp_thinking_level(spec.model_id, requested_level),
                paid_only=spec.paid_only,
            )
        )
    return attempts


def _extract_error_reasons(details: object) -> set[str]:
    """Recursively extract Google RPC ErrorInfo `reason` values from SDK error details."""
    reasons: set[str] = set()
    if isinstance(details, dict):
        reason = details.get("reason")
        if isinstance(reason, str) and reason:
            reasons.add(reason.upper())
        for key in ("error", "details"):
            nested = details.get(key)
            if nested is not None:
                reasons.update(_extract_error_reasons(nested))
    elif isinstance(details, (list, tuple)):
        for item in details:
            reasons.update(_extract_error_reasons(item))
    return reasons


def _has_marker(message_lower: str, markers: tuple[str, ...]) -> bool:
    return any(marker in message_lower for marker in markers)


def _is_invalid_key_error(
    code: int | None, status: str, msg: str, reasons: set[str]
) -> bool:
    if reasons & _INVALID_KEY_REASONS or code == 401 or status == "UNAUTHENTICATED":
        return True
    return code in (400, 403) and _has_marker(msg, _INVALID_KEY_MARKERS)


def _is_payment_required_error(code: int | None, msg: str, reasons: set[str]) -> bool:
    return (
        code == 402
        or bool(reasons & _PAYMENT_REASONS)
        or _has_marker(msg, _PAYMENT_MARKERS)
    )


def _is_quota_error(code: int | None, status: str, msg: str) -> bool:
    return (
        code == 429
        or status == "RESOURCE_EXHAUSTED"
        or "quota" in msg
        or "rate limit" in msg
    )


def _is_transient_error(code: int | None, status: str) -> bool:
    return code in (500, 502, 503, 504) or status in (
        "INTERNAL",
        "UNAVAILABLE",
        "DEADLINE_EXCEEDED",
    )


def _has_marker(message_lower: str, markers: tuple[str, ...]) -> bool:
    return any(marker in message_lower for marker in markers)


def _is_invalid_key_error(
    code: int | None, status: str, msg: str, reasons: set[str]
) -> bool:
    if reasons & _INVALID_KEY_REASONS or code == 401 or status == "UNAUTHENTICATED":
        return True
    return code in (400, 403) and _has_marker(msg, _INVALID_KEY_MARKERS)


def _is_payment_required_error(code: int | None, msg: str, reasons: set[str]) -> bool:
    return (
        code == 402
        or bool(reasons & _PAYMENT_REASONS)
        or _has_marker(msg, _PAYMENT_MARKERS)
    )


def _is_quota_error(code: int | None, status: str, msg: str) -> bool:
    return (
        code == 429
        or status == "RESOURCE_EXHAUSTED"
        or "quota" in msg
        or "rate limit" in msg
    )


def _is_transient_error(code: int | None, status: str) -> bool:
    return code in (500, 502, 503, 504) or status in (
        "INTERNAL",
        "UNAVAILABLE",
        "DEADLINE_EXCEEDED",
    )


def classify_gemini_error(
    code: int | None,
    status: str | None = None,
    message: str | None = None,
    details: object = None,
    *,
    model_paid_only: bool = False,
) -> GeminiErrorAction:
    """Classify a Gemini API error into a deterministic fallback or short-circuit action."""
    msg = (message or "").lower()
    st = (status or "").upper()
    reasons = _extract_error_reasons(details)

    if _is_invalid_key_error(code, st, msg, reasons):
        return GeminiErrorAction.INVALID_KEY
    if _is_payment_required_error(code, msg, reasons):
        return GeminiErrorAction.PAYMENT_REQUIRED
    if code == 403 or st == "PERMISSION_DENIED":
        if model_paid_only or _has_marker(msg, _TIER_DENIED_MARKERS):
            return GeminiErrorAction.TIER_DENIED
        return GeminiErrorAction.INVALID_KEY
    if _is_quota_error(code, st, msg):
        return GeminiErrorAction.QUOTA_EXHAUSTED
    if _is_transient_error(code, st):
        return GeminiErrorAction.TRANSIENT
    return GeminiErrorAction.FATAL


def gemini_model_cooldown_key(user_id: int, model_id: str) -> str:
    return f"vektryn:gemini:cooldown:{user_id}:{model_id}"


def gemini_invalid_key_pause_key(user_id: int) -> str:
    return f"vektryn:gemini:pause:{user_id}:invalid_key"


def gemini_payment_pause_key(user_id: int) -> str:
    return f"vektryn:gemini:pause:{user_id}:payment_required"


def gemini_notification_throttle_key(user_id: int, kind: str | NotificationKind) -> str:
    kind_value = kind.value if isinstance(kind, NotificationKind) else str(kind)
    return f"vektryn:gemini:notify:{user_id}:{kind_value}"


def all_user_gemini_state_keys(user_id: int) -> list[str]:
    """Return every deterministic Redis key scoped to a user's Gemini BYOK state."""
    return [
        gemini_invalid_key_pause_key(user_id),
        gemini_payment_pause_key(user_id),
        *(
            gemini_model_cooldown_key(user_id, spec.model_id)
            for spec in GEMINI_MODEL_LADDER
        ),
        gemini_notification_throttle_key(user_id, NotificationKind.AI_KEY_INVALID),
        gemini_notification_throttle_key(user_id, NotificationKind.AI_QUOTA_EXHAUSTED),
    ]
