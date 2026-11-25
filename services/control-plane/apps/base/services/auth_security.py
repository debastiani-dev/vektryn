from contextlib import suppress
import ipaddress
import logging
from urllib.parse import quote

from django.conf import settings
from django.contrib.sessions.models import Session
from django.utils import timezone
import redis

logger = logging.getLogger(__name__)

DEFAULT_ACCT_MAX_FAILURES = 5
DEFAULT_IP_MAX_FAILURES = 20
DEFAULT_LOCKOUT_WINDOW_SECONDS = 900
DEFAULT_TRUSTED_PROXY_COUNT = 1
REDIS_SOCKET_TIMEOUT_SECONDS = 1.5
LOGIN_FAIL_IP_KEY_PREFIX = "vektryn:auth:login_fail:ip:"
LOGIN_FAIL_ACCT_KEY_PREFIX = "vektryn:auth:login_fail:acct:"


class LoginRateLimitError(RuntimeError):
    """Raised when a login attempt is blocked by IP or account throttling."""

    def __init__(self, retry_after_seconds: int) -> None:
        self.retry_after_seconds = max(1, int(retry_after_seconds))
        super().__init__(
            f"Too many failed login attempts. Try again in {self.retry_after_seconds}s."
        )


def _resolve_throttle_config() -> tuple[int, int, int, int]:
    acct_max = max(
        1,
        int(
            getattr(
                settings,
                "AUTH_LOGIN_ACCT_MAX_FAILURES",
                DEFAULT_ACCT_MAX_FAILURES,
            )
        ),
    )
    ip_max = max(
        1,
        int(
            getattr(
                settings,
                "AUTH_LOGIN_IP_MAX_FAILURES",
                DEFAULT_IP_MAX_FAILURES,
            )
        ),
    )
    window_seconds = max(
        1,
        int(
            getattr(
                settings,
                "AUTH_LOGIN_LOCKOUT_WINDOW_SECONDS",
                DEFAULT_LOCKOUT_WINDOW_SECONDS,
            )
        ),
    )
    trusted_proxies = max(
        0,
        int(
            getattr(
                settings,
                "AUTH_LOGIN_TRUSTED_PROXY_COUNT",
                DEFAULT_TRUSTED_PROXY_COUNT,
            )
        ),
    )
    return acct_max, ip_max, window_seconds, trusted_proxies


def _normalize_ip(raw: str | None) -> str | None:
    if not raw:
        return None
    candidate = raw.strip()
    if not candidate:
        return None
    try:
        return ipaddress.ip_address(candidate).compressed
    except ValueError:
        return None


def extract_client_ip(request) -> str:
    _, _, _, trusted_proxies = _resolve_throttle_config()
    meta = getattr(request, "META", {}) or {}
    if trusted_proxies > 0:
        xff = meta.get("HTTP_X_FORWARDED_FOR", "")
        if isinstance(xff, str) and xff.strip():
            valid_ips = [
                normalized
                for token in xff.split(",")
                if (normalized := _normalize_ip(token)) is not None
            ]
            if valid_ips:
                if len(valid_ips) >= trusted_proxies:
                    return valid_ips[-trusted_proxies]
                return valid_ips[0]

    remote_addr = meta.get("REMOTE_ADDR")
    normalized_remote = (
        _normalize_ip(remote_addr) if isinstance(remote_addr, str) else None
    )
    return normalized_remote or "unknown"


def build_login_throttle_keys(username: str, client_ip: str) -> tuple[str, str]:
    normalized_ip = _normalize_ip(client_ip) or "unknown"
    normalized_user = quote(username.strip().lower(), safe="")
    ip_key = f"{LOGIN_FAIL_IP_KEY_PREFIX}{normalized_ip}"
    acct_key = f"{LOGIN_FAIL_ACCT_KEY_PREFIX}{normalized_user}:{normalized_ip}"
    return ip_key, acct_key


def _open_redis_client() -> redis.Redis | None:
    redis_url = (getattr(settings, "REDIS_URL", "") or "").strip()
    if not redis_url:
        return None
    return redis.Redis.from_url(
        redis_url,
        socket_connect_timeout=REDIS_SOCKET_TIMEOUT_SECONDS,
        socket_timeout=REDIS_SOCKET_TIMEOUT_SECONDS,
        decode_responses=True,
    )


def _parse_int_or_zero(value: object) -> int:
    if value is None:
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _read_blocked_ttl(
    client: redis.Redis,
    key: str,
    max_failures: int,
    window_seconds: int,
) -> int | None:
    count = _parse_int_or_zero(client.get(key))
    if count < max_failures:
        return None
    ttl = _parse_int_or_zero(client.ttl(key))
    if ttl <= 0:
        client.expire(key, window_seconds)
        ttl = window_seconds
    return max(1, ttl)


def _increment_failure_counter(
    client: redis.Redis,
    key: str,
    window_seconds: int,
) -> tuple[int, int]:
    count = int(client.incr(key))
    if count == 1:
        client.expire(key, window_seconds)
        return count, window_seconds
    ttl = _parse_int_or_zero(client.ttl(key))
    if ttl <= 0:
        client.expire(key, window_seconds)
        ttl = window_seconds
    return count, max(1, ttl)


def check_login_throttle(username: str, client_ip: str) -> None:
    acct_max, ip_max, window_seconds, _ = _resolve_throttle_config()
    ip_key, acct_key = build_login_throttle_keys(username, client_ip)
    blocked_retry_after: int | None = None
    client: redis.Redis | None = None
    try:
        client = _open_redis_client()
        if client is None:
            return
        blocked_ttls: list[int] = []
        ip_ttl = _read_blocked_ttl(client, ip_key, ip_max, window_seconds)
        if ip_ttl is not None:
            blocked_ttls.append(ip_ttl)
        acct_ttl = _read_blocked_ttl(client, acct_key, acct_max, window_seconds)
        if acct_ttl is not None:
            blocked_ttls.append(acct_ttl)
        if blocked_ttls:
            blocked_retry_after = max(1, max(blocked_ttls))
    except Exception as exc:
        logger.warning("Redis unavailable for login throttle check: %s", exc)
    finally:
        if client is not None:
            with suppress(Exception):
                client.close()

    if blocked_retry_after is not None:
        raise LoginRateLimitError(retry_after_seconds=blocked_retry_after)


def record_login_failure(username: str, client_ip: str) -> int | None:
    acct_max, ip_max, window_seconds, _ = _resolve_throttle_config()
    ip_key, acct_key = build_login_throttle_keys(username, client_ip)
    client: redis.Redis | None = None
    try:
        client = _open_redis_client()
        if client is None:
            return None
        ip_count, ip_ttl = _increment_failure_counter(client, ip_key, window_seconds)
        acct_count, acct_ttl = _increment_failure_counter(
            client, acct_key, window_seconds
        )
        blocked_ttls: list[int] = []
        if ip_count >= ip_max:
            blocked_ttls.append(ip_ttl)
        if acct_count >= acct_max:
            blocked_ttls.append(acct_ttl)
        if blocked_ttls:
            return max(1, max(blocked_ttls))
        return None
    except Exception as exc:
        logger.warning("Redis unavailable for login failure recording: %s", exc)
        return None
    finally:
        if client is not None:
            with suppress(Exception):
                client.close()


def clear_login_account_failures(username: str, client_ip: str) -> None:
    _, acct_key = build_login_throttle_keys(username, client_ip)
    client: redis.Redis | None = None
    try:
        client = _open_redis_client()
        if client is None:
            return
        client.delete(acct_key)
    except Exception as exc:
        logger.warning("Redis unavailable for clearing login failure counter: %s", exc)
    finally:
        if client is not None:
            with suppress(Exception):
                client.close()


def invalidate_user_sessions(
    user_id: int | str,
    *,
    exclude_session_key: str | None = None,
) -> int:
    """Eagerly purge active Django DB sessions for a user (optionally keeping one)."""
    target_user_id = str(user_id)
    stale_keys: list[str] = []
    qs = (
        Session.objects.filter(expire_date__gte=timezone.now())
        .only("session_key", "session_data")
        .iterator(chunk_size=200)
    )
    for session in qs:
        if exclude_session_key and session.session_key == exclude_session_key:
            continue
        try:
            decoded = session.get_decoded()
        except Exception:
            continue
        if str(decoded.get("_auth_user_id", "")) == target_user_id:
            stale_keys.append(session.session_key)

    if not stale_keys:
        return 0
    deleted_count, _ = Session.objects.filter(session_key__in=stale_keys).delete()
    return int(deleted_count)
