import hashlib
import hmac
import time

DEFAULT_STREAM_TOKEN_TTL_SECONDS = 3600


def sign_stream_token(
    user_id: str,
    secret: str,
    *,
    ttl_seconds: int = DEFAULT_STREAM_TOKEN_TTL_SECONDS,
    now: int | None = None,
) -> str:
    cleaned_user = str(user_id).strip()
    cleaned_secret = secret.strip()
    if not cleaned_user:
        raise ValueError("user_id must be non-empty")
    if not cleaned_secret:
        raise ValueError("secret must be non-empty")

    issued_at = int(time.time()) if now is None else int(now)
    expires_at = issued_at + ttl_seconds
    message = f"{cleaned_user}:{expires_at}".encode("utf-8")
    signature = hmac.new(
        cleaned_secret.encode("utf-8"),
        message,
        hashlib.sha256,
    ).hexdigest()
    return f"{cleaned_user}.{expires_at}.{signature}"


def verify_stream_token(
    token: str,
    secret: str,
    *,
    now: int | None = None,
) -> str | None:
    cleaned_secret = secret.strip()
    if not token or not cleaned_secret:
        return None

    parts = token.strip().split(".")
    if len(parts) != 3:
        return None

    user_id, expires_raw, provided_sig = parts
    if not user_id or not provided_sig:
        return None

    try:
        expires_at = int(expires_raw)
    except ValueError:
        return None

    current_time = int(time.time()) if now is None else int(now)
    if expires_at <= current_time:
        return None

    message = f"{user_id}:{expires_at}".encode("utf-8")
    expected_sig = hmac.new(
        cleaned_secret.encode("utf-8"),
        message,
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(provided_sig, expected_sig):
        return None
    return user_id
