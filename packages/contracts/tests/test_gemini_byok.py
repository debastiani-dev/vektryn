"""Unit tests for Gemini model ladder, error classifier, Fernet crypto, and redaction."""

import pytest
from cryptography.fernet import Fernet

from vektryn_contracts import (
    AUTO_GEMINI_MODEL,
    GEMINI_EMBEDDING_MODEL,
    GEMINI_MODEL_LADDER,
    REDACTED_VALUE,
    BYOKCryptoError,
    BYOKKeyNotConfiguredError,
    GeminiErrorAction,
    NotificationKind,
    all_user_gemini_state_keys,
    clamp_thinking_level,
    classify_gemini_error,
    decrypt_api_key,
    encrypt_api_key,
    gemini_invalid_key_pause_key,
    gemini_model_cooldown_key,
    gemini_payment_pause_key,
    mask_api_key_last4,
    normalize_api_key,
    redact_secrets,
    resolve_model_chain,
)


def test_notification_kind_includes_ai_byok_kinds() -> None:
    assert NotificationKind.AI_QUOTA_EXHAUSTED == "ai_quota_exhausted"
    assert NotificationKind.AI_KEY_INVALID == "ai_key_invalid"


def test_clamp_thinking_level_allows_minimal_only_on_flash_lite() -> None:
    assert clamp_thinking_level("gemini-3.5-flash-lite", "minimal") == "minimal"
    assert clamp_thinking_level("gemini-3.8-flash", "minimal") == "low"
    assert clamp_thinking_level("gemini-4-hydrogen", "minimal") == "low"
    assert clamp_thinking_level("gemini-4-carbon", "minimal") == "low"
    assert clamp_thinking_level("gemini-4-hydrogen", "medium") == "medium"
    assert clamp_thinking_level("unknown-model", "minimal") == "low"


def test_resolve_model_chain_auto_tasks() -> None:
    enrichment = resolve_model_chain("enrichment")
    assert [(a.model_id, a.thinking_level) for a in enrichment] == [
        ("gemini-3.5-flash-lite", "minimal"),
        ("gemini-3.8-flash", "low"),
    ]

    resume_skills = resolve_model_chain(
        "resume_skills", AUTO_GEMINI_MODEL, allow_fallback=True
    )
    assert [(a.model_id, a.thinking_level) for a in resume_skills] == [
        ("gemini-3.5-flash-lite", "minimal"),
        ("gemini-3.8-flash", "low"),
        ("gemini-4-hydrogen", "low"),
    ]

    scoring = resolve_model_chain("scoring", AUTO_GEMINI_MODEL, allow_fallback=True)
    assert [(a.model_id, a.thinking_level) for a in scoring] == [
        ("gemini-3.5-flash-lite", "low"),
        ("gemini-3.8-flash", "low"),
        ("gemini-4-hydrogen", "low"),
    ]

    copilot = resolve_model_chain("copilot", AUTO_GEMINI_MODEL, allow_fallback=True)
    assert [(a.model_id, a.thinking_level) for a in copilot] == [
        ("gemini-4-hydrogen", "medium"),
        ("gemini-3.8-flash", "medium"),
        ("gemini-3.5-flash-lite", "low"),
    ]


def test_resolve_model_chain_preferred_and_fallback_flag() -> None:
    chain = resolve_model_chain("copilot", "gemini-4-argon", allow_fallback=True)
    assert [(a.model_id, a.thinking_level, a.paid_only) for a in chain] == [
        ("gemini-4-argon", "medium", True),
        ("gemini-4-hydrogen", "medium", False),
        ("gemini-3.8-flash", "medium", False),
        ("gemini-3.5-flash-lite", "low", False),
    ]

    single = resolve_model_chain("scoring", "gemini-4-carbon", allow_fallback=False)
    assert [(a.model_id, a.thinking_level, a.paid_only) for a in single] == [
        ("gemini-4-carbon", "low", True),
    ]

    auto_no_fallback = resolve_model_chain(
        "copilot", AUTO_GEMINI_MODEL, allow_fallback=False
    )
    assert [(a.model_id, a.thinking_level) for a in auto_no_fallback] == [
        ("gemini-4-hydrogen", "medium"),
    ]


def test_embedding_model_constant_is_locked() -> None:
    assert GEMINI_EMBEDDING_MODEL == "gemini-embedding-001"
    assert GEMINI_EMBEDDING_MODEL not in {spec.model_id for spec in GEMINI_MODEL_LADDER}


@pytest.mark.parametrize(
    ("code", "status", "message", "details", "paid_only", "expected"),
    [
        (
            400,
            "INVALID_ARGUMENT",
            "API key not valid. Please pass a valid API key.",
            {"error": {"details": [{"reason": "API_KEY_INVALID"}]}},
            False,
            GeminiErrorAction.INVALID_KEY,
        ),
        (
            400,
            "INVALID_ARGUMENT",
            "API key not valid.",
            None,
            False,
            GeminiErrorAction.INVALID_KEY,
        ),
        (
            401,
            "UNAUTHENTICATED",
            "Request had invalid authentication credentials.",
            None,
            False,
            GeminiErrorAction.INVALID_KEY,
        ),
        (
            403,
            "PERMISSION_DENIED",
            "API key expired.",
            None,
            True,
            GeminiErrorAction.INVALID_KEY,
        ),
        (
            402,
            "FAILED_PRECONDITION",
            "Payment required",
            None,
            True,
            GeminiErrorAction.PAYMENT_REQUIRED,
        ),
        (
            429,
            "RESOURCE_EXHAUSTED",
            "Prepayment credits are depleted. Please add credits to continue.",
            None,
            False,
            GeminiErrorAction.PAYMENT_REQUIRED,
        ),
        (
            403,
            "PERMISSION_DENIED",
            "Billing must be enabled for this project.",
            None,
            True,
            GeminiErrorAction.PAYMENT_REQUIRED,
        ),
        (
            403,
            "PERMISSION_DENIED",
            "Model is not available on the free tier.",
            None,
            True,
            GeminiErrorAction.TIER_DENIED,
        ),
        (
            403,
            "PERMISSION_DENIED",
            "Permission denied.",
            None,
            True,
            GeminiErrorAction.TIER_DENIED,
        ),
        (
            403,
            "PERMISSION_DENIED",
            "Permission denied.",
            None,
            False,
            GeminiErrorAction.INVALID_KEY,
        ),
        (
            429,
            "RESOURCE_EXHAUSTED",
            "Quota exceeded for requests per minute.",
            None,
            False,
            GeminiErrorAction.QUOTA_EXHAUSTED,
        ),
        (
            503,
            "UNAVAILABLE",
            "The service is currently unavailable.",
            None,
            False,
            GeminiErrorAction.TRANSIENT,
        ),
        (
            500,
            "INTERNAL",
            "Internal error encountered.",
            None,
            False,
            GeminiErrorAction.TRANSIENT,
        ),
        (
            400,
            "INVALID_ARGUMENT",
            "Malformed JSON schema.",
            None,
            False,
            GeminiErrorAction.FATAL,
        ),
    ],
)
def test_classify_gemini_error(
    code: int | None,
    status: str | None,
    message: str | None,
    details: object,
    paid_only: bool,
    expected: GeminiErrorAction,
) -> None:
    assert (
        classify_gemini_error(code, status, message, details, model_paid_only=paid_only)
        is expected
    )


def test_normalize_api_key_strips_whitespace_and_wrapping_quotes() -> None:
    raw = '  "AQ.Ab8RN6-ValidKeyValue1234567890" \n'
    assert normalize_api_key(raw) == "AQ.Ab8RN6-ValidKeyValue1234567890"
    assert (
        normalize_api_key(" 'AIzaSyD-1234567890abcdef123456' ")
        == "AIzaSyD-1234567890abcdef123456"
    )
    assert (
        normalize_api_key("`AQ.Ab8RN6-ValidKeyValue1234567890`")
        == "AQ.Ab8RN6-ValidKeyValue1234567890"
    )


@pytest.mark.parametrize(
    "bad_key", ["", "   ", "short", "AQ.has space inside 1234567890", "x" * 201]
)
def test_normalize_api_key_rejects_invalid_values(bad_key: str) -> None:
    with pytest.raises(ValueError):
        normalize_api_key(bad_key)


def test_encrypt_decrypt_round_trip_and_failure_modes() -> None:
    fernet_key = Fernet.generate_key().decode("utf-8")
    plaintext = "AQ.Ab8RN6-TestSecretKeyValue123456789"
    token = encrypt_api_key(plaintext, fernet_key)
    assert token != plaintext
    assert decrypt_api_key(token, fernet_key) == plaintext
    assert mask_api_key_last4(plaintext) == "6789"

    with pytest.raises(BYOKKeyNotConfiguredError):
        encrypt_api_key(plaintext, "")

    with pytest.raises(BYOKKeyNotConfiguredError):
        encrypt_api_key(plaintext, "not-a-valid-fernet-key")

    other_key = Fernet.generate_key().decode("utf-8")
    with pytest.raises(BYOKCryptoError):
        decrypt_api_key(token, other_key)


def test_redact_secrets_scrubs_aiza_aq_and_query_params() -> None:
    legacy = "Error calling https://generativelanguage.googleapis.com/v1?key=AIzaSyD1234567890abcdefghijklmno"
    aq = "ClientError: invalid key AQ.Ab8RN6L_test.token-1234567890abcdef in request"
    query = "GET /v1beta/models?api_key=custom_secret_token_999&alt=json"

    redacted_legacy = redact_secrets(legacy)
    assert "AIzaSy" not in redacted_legacy
    assert REDACTED_VALUE in redacted_legacy

    redacted_aq = redact_secrets(aq)
    assert "AQ.Ab8RN6" not in redacted_aq
    assert REDACTED_VALUE in redacted_aq

    redacted_query = redact_secrets(query)
    assert "custom_secret_token_999" not in redacted_query
    assert f"api_key={REDACTED_VALUE}&alt=json" in redacted_query


def test_all_user_gemini_state_keys_is_deterministic() -> None:
    keys = all_user_gemini_state_keys(42)
    assert gemini_invalid_key_pause_key(42) in keys
    assert gemini_payment_pause_key(42) in keys
    for spec in GEMINI_MODEL_LADDER:
        assert gemini_model_cooldown_key(42, spec.model_id) in keys
    assert len(keys) == len(set(keys))
