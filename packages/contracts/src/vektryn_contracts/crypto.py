"""Fernet encryption and hygiene helpers for user-supplied Gemini API keys."""

from cryptography.fernet import Fernet, InvalidToken

API_KEY_MIN_LENGTH = 20
API_KEY_MAX_LENGTH = 200
_WRAPPING_QUOTES = ('"', "'", "`")


class BYOKCryptoError(ValueError):
    """Base error raised when encrypting or decrypting BYOK credentials fails."""


class BYOKKeyNotConfiguredError(BYOKCryptoError):
    """Raised when BYOK_ENCRYPTION_KEY is missing or not a valid Fernet key."""


def normalize_api_key(raw_key: str) -> str:
    """Strip surrounding whitespace and one matching pair of quotes/backticks, then validate."""
    cleaned = raw_key.strip()
    if (
        len(cleaned) >= 2
        and cleaned[0] in _WRAPPING_QUOTES
        and cleaned[-1] == cleaned[0]
    ):
        cleaned = cleaned[1:-1].strip()
    if not cleaned:
        raise ValueError("API key cannot be blank.")
    if any(ch.isspace() for ch in cleaned):
        raise ValueError("API key must not contain whitespace.")
    if not (API_KEY_MIN_LENGTH <= len(cleaned) <= API_KEY_MAX_LENGTH):
        raise ValueError(
            f"API key length must be between {API_KEY_MIN_LENGTH} and {API_KEY_MAX_LENGTH} characters."
        )
    return cleaned


def build_fernet(encryption_key: str) -> Fernet:
    """Validate and construct a Fernet cipher from BYOK_ENCRYPTION_KEY."""
    cleaned = (encryption_key or "").strip()
    if not cleaned:
        raise BYOKKeyNotConfiguredError("BYOK_ENCRYPTION_KEY is not configured.")
    try:
        return Fernet(cleaned.encode("utf-8"))
    except (ValueError, TypeError) as exc:
        raise BYOKKeyNotConfiguredError(
            "BYOK_ENCRYPTION_KEY is not a valid Fernet key."
        ) from exc


def encrypt_api_key(plaintext: str, encryption_key: str) -> str:
    """Encrypt a normalized user API key with Fernet and return a UTF-8 token."""
    fernet = build_fernet(encryption_key)
    return fernet.encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt_api_key(ciphertext: str, encryption_key: str) -> str:
    """Decrypt a stored Fernet token back into the user's plaintext API key."""
    fernet = build_fernet(encryption_key)
    try:
        return fernet.decrypt(ciphertext.encode("utf-8")).decode("utf-8")
    except (InvalidToken, ValueError, TypeError) as exc:
        raise BYOKCryptoError("Unable to decrypt stored Gemini API key.") from exc


def mask_api_key_last4(plaintext: str) -> str:
    """Return the last 4 characters of a plaintext API key for non-sensitive UI display."""
    return plaintext[-4:] if len(plaintext) >= 4 else plaintext
