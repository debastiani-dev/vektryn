from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.sessions.models import Session
import pytest
import redis
from rest_framework.test import APIClient, APIRequestFactory

from apps.base.services import auth_security
from apps.base.services.auth_security import (
    build_login_throttle_keys,
    extract_client_ip,
)

User = get_user_model()


class _FakeRedis:
    def __init__(self) -> None:
        self.counts: dict[str, int] = {}
        self.ttls: dict[str, int] = {}
        self.close_count = 0

    def get(self, key: str) -> str | None:
        val = self.counts.get(key)
        return str(val) if val is not None else None

    def incr(self, key: str) -> int:
        self.counts[key] = self.counts.get(key, 0) + 1
        return self.counts[key]

    def expire(self, key: str, seconds: int) -> bool:
        if key in self.counts:
            self.ttls[key] = int(seconds)
            return True
        return False

    def ttl(self, key: str) -> int:
        if key not in self.counts:
            return -2
        return self.ttls.get(key, -1)

    def delete(self, *keys: str) -> int:
        deleted = 0
        for key in keys:
            if key in self.counts:
                del self.counts[key]
                self.ttls.pop(key, None)
                deleted += 1
        return deleted

    def close(self) -> None:
        self.close_count += 1


def test_extract_client_ip_and_spoofing_protection(settings):
    factory = APIRequestFactory()

    settings.AUTH_LOGIN_TRUSTED_PROXY_COUNT = 1
    req_direct = factory.post("/api/v1/auth/login/", REMOTE_ADDR="198.51.100.10")
    assert extract_client_ip(req_direct) == "198.51.100.10"

    # Rightmost hop blocks leftmost X-Forwarded-For spoofing
    req_spoofed = factory.post(
        "/api/v1/auth/login/",
        HTTP_X_FORWARDED_FOR="1.2.3.4, 203.0.113.7",
        REMOTE_ADDR="10.0.0.1",
    )
    assert extract_client_ip(req_spoofed) == "203.0.113.7"

    # Malformed tokens are ignored safely
    req_malformed = factory.post(
        "/api/v1/auth/login/",
        HTTP_X_FORWARDED_FOR="not-an-ip, 203.0.113.9:evil, 198.51.100.4",
        REMOTE_ADDR="10.0.0.1",
    )
    assert extract_client_ip(req_malformed) == "198.51.100.4"

    # Multi-hop configuration selects from the right
    settings.AUTH_LOGIN_TRUSTED_PROXY_COUNT = 2
    req_multi = factory.post(
        "/api/v1/auth/login/",
        HTTP_X_FORWARDED_FOR="9.9.9.9, 203.0.113.5, 34.10.20.30",
        REMOTE_ADDR="10.0.0.1",
    )
    assert extract_client_ip(req_multi) == "203.0.113.5"

    # Zero trusted proxies strictly ignores X-Forwarded-For
    settings.AUTH_LOGIN_TRUSTED_PROXY_COUNT = 0
    assert extract_client_ip(req_spoofed) == "10.0.0.1"

    # Key builder normalizes username case/whitespace and URL-encodes colons
    ip_key, acct_key = build_login_throttle_keys("  Admin:Evil ", "203.0.113.7")
    assert ip_key == "vektryn:auth:login_fail:ip:203.0.113.7"
    assert acct_key == "vektryn:auth:login_fail:acct:admin%3Aevil:203.0.113.7"


@pytest.mark.django_db
def test_login_malformed_payloads_return_400(settings):
    settings.REDIS_URL = ""
    client = APIClient()

    res_types = client.post(
        "/api/v1/auth/login/",
        {"username": ["alice"], "password": 123},
        format="json",
    )
    assert res_types.status_code == 400

    res_blank = client.post(
        "/api/v1/auth/login/",
        {"username": "   ", "password": "secret"},
        format="json",
    )
    assert res_blank.status_code == 400

    res_empty_pw = client.post(
        "/api/v1/auth/login/",
        {"username": "alice", "password": ""},
        format="json",
    )
    assert res_empty_pw.status_code == 400


@pytest.mark.django_db
def test_login_account_throttle_lockout_pre_auth_and_clear_on_success(
    settings, monkeypatch
):
    fake_redis = _FakeRedis()
    settings.REDIS_URL = "redis://fake:6379/0"
    settings.AUTH_LOGIN_ACCT_MAX_FAILURES = 3
    settings.AUTH_LOGIN_IP_MAX_FAILURES = 10
    settings.AUTH_LOGIN_LOCKOUT_WINDOW_SECONDS = 600
    settings.AUTH_LOGIN_TRUSTED_PROXY_COUNT = 1
    monkeypatch.setattr(redis.Redis, "from_url", lambda *args, **kwargs: fake_redis)

    User.objects.create_user(username="alice", password="CorrectPassword!99")
    client = APIClient()

    # Attempts 1 and 2 fail with 401
    for _ in range(2):
        res = client.post(
            "/api/v1/auth/login/",
            {"username": "alice", "password": "wrong"},
            format="json",
            REMOTE_ADDR="203.0.113.10",
        )
        assert res.status_code == 401

    # Attempt 3 breaches account threshold -> 429 + Retry-After
    res_lock = client.post(
        "/api/v1/auth/login/",
        {"username": "alice", "password": "wrong"},
        format="json",
        REMOTE_ADDR="203.0.113.10",
    )
    assert res_lock.status_code == 429
    assert res_lock.headers["Retry-After"] == "600"
    assert res_lock.json()["retry_after_seconds"] == 600

    # Subsequent attempt is blocked BEFORE authenticate() runs (PBKDF2 DoS protection)
    with patch("apps.base.views.auth.authenticate") as mock_auth:
        res_blocked = client.post(
            "/api/v1/auth/login/",
            {"username": "alice", "password": "CorrectPassword!99"},
            format="json",
            REMOTE_ADDR="203.0.113.10",
        )
        assert res_blocked.status_code == 429
        assert res_blocked.headers["Retry-After"] == "600"
        mock_auth.assert_not_called()

    # After account lockout clears/expires, valid login succeeds and clears ONLY acct counter
    ip_key, acct_key = build_login_throttle_keys("alice", "203.0.113.10")
    fake_redis.delete(acct_key)
    # Record 1 fresh failure before succeeding to verify clear_login_account_failures deletes it
    res_fail_once = client.post(
        "/api/v1/auth/login/",
        {"username": "alice", "password": "wrong"},
        format="json",
        REMOTE_ADDR="203.0.113.10",
    )
    assert res_fail_once.status_code == 401
    assert fake_redis.get(acct_key) == "1"

    res_ok = client.post(
        "/api/v1/auth/login/",
        {"username": "alice", "password": "CorrectPassword!99"},
        format="json",
        REMOTE_ADDR="203.0.113.10",
    )
    assert res_ok.status_code == 200
    assert fake_redis.get(acct_key) is None
    assert fake_redis.get(ip_key) == "4"  # IP counter preserved on valid login
    assert fake_redis.close_count >= 5


@pytest.mark.django_db
def test_login_ip_throttle_dual_breach_max_ttl_and_orphan_recovery(
    settings, monkeypatch
):
    fake_redis = _FakeRedis()
    settings.REDIS_URL = "redis://fake:6379/0"
    settings.AUTH_LOGIN_ACCT_MAX_FAILURES = 5
    settings.AUTH_LOGIN_IP_MAX_FAILURES = 3
    settings.AUTH_LOGIN_LOCKOUT_WINDOW_SECONDS = 900
    monkeypatch.setattr(redis.Redis, "from_url", lambda *args, **kwargs: fake_redis)

    client = APIClient()
    # Credential stuffing across distinct usernames from the same IP triggers IP lockout
    for idx in range(2):
        res = client.post(
            "/api/v1/auth/login/",
            {"username": f"user_{idx}", "password": "wrong"},
            format="json",
            REMOTE_ADDR="198.51.100.22",
        )
        assert res.status_code == 401

    res_ip_lock = client.post(
        "/api/v1/auth/login/",
        {"username": "user_2", "password": "wrong"},
        format="json",
        REMOTE_ADDR="198.51.100.22",
    )
    assert res_ip_lock.status_code == 429
    assert res_ip_lock.headers["Retry-After"] == "900"

    # Dual breach returns max(ttl_acct, ttl_ip)
    ip_key, acct_key = build_login_throttle_keys("bob", "198.51.100.22")
    fake_redis.counts[acct_key] = 5
    fake_redis.ttls[acct_key] = 120
    fake_redis.counts[ip_key] = 3
    fake_redis.ttls[ip_key] = 480

    res_dual = client.post(
        "/api/v1/auth/login/",
        {"username": "bob", "password": "wrong"},
        format="json",
        REMOTE_ADDR="198.51.100.22",
    )
    assert res_dual.status_code == 429
    assert res_dual.headers["Retry-After"] == "480"
    assert res_dual.json()["retry_after_seconds"] == 480

    # Orphan key with ttl == -1 recovers by resetting TTL to window_seconds
    fake_redis.counts[ip_key] = 1
    fake_redis.counts[acct_key] = 5
    fake_redis.ttls[acct_key] = -1
    res_orphan = client.post(
        "/api/v1/auth/login/",
        {"username": "bob", "password": "wrong"},
        format="json",
        REMOTE_ADDR="198.51.100.22",
    )
    assert res_orphan.status_code == 429
    assert res_orphan.headers["Retry-After"] == "900"
    assert fake_redis.ttl(acct_key) == 900


@pytest.mark.django_db
def test_login_throttle_fails_open_when_redis_unavailable(
    settings, monkeypatch, caplog
):
    User.objects.create_user(username="failopen", password="SafePassword!2026")
    client = APIClient()

    # Empty REDIS_URL -> fail open cleanly
    settings.REDIS_URL = ""
    res_ok = client.post(
        "/api/v1/auth/login/",
        {"username": "failopen", "password": "SafePassword!2026"},
        format="json",
    )
    assert res_ok.status_code == 200

    # Redis ConnectionError -> logs warning and fails open
    settings.REDIS_URL = "redis://down:6379/0"

    def _boom(*_args, **_kwargs):
        raise redis.ConnectionError("redis down")

    monkeypatch.setattr(redis.Redis, "from_url", _boom)

    with caplog.at_level("WARNING", logger=auth_security.logger.name):
        res_bad = client.post(
            "/api/v1/auth/login/",
            {"username": "failopen", "password": "wrong"},
            format="json",
        )
        assert res_bad.status_code == 401
        res_good = client.post(
            "/api/v1/auth/login/",
            {"username": "failopen", "password": "SafePassword!2026"},
            format="json",
        )
        assert res_good.status_code == 200

    assert any("Redis unavailable" in rec.message for rec in caplog.records)


@pytest.mark.django_db
def test_change_password_validation_and_session_rotation(settings):
    settings.REDIS_URL = ""
    initial_pw = "InitialStrong!2026"
    rotated_pw = "RotatedQuantum#2026"
    user = User.objects.create_user(
        username="rotator_user",
        email="rotator@example.com",
        password=initial_pw,
    )

    anon = APIClient()
    assert (
        anon.post(
            "/api/v1/auth/change-password/",
            {"current_password": initial_pw, "new_password": rotated_pw},
            format="json",
        ).status_code
        == 403
    )

    # Establish two independent browser sessions for the same user
    client_primary = APIClient()
    client_other = APIClient()
    assert (
        client_primary.post(
            "/api/v1/auth/login/",
            {"username": user.username, "password": initial_pw},
            format="json",
        ).status_code
        == 200
    )
    assert (
        client_other.post(
            "/api/v1/auth/login/",
            {"username": user.username, "password": initial_pw},
            format="json",
        ).status_code
        == 200
    )

    # Wrong current password
    res_wrong = client_primary.post(
        "/api/v1/auth/change-password/",
        {"current_password": "wrong-password", "new_password": rotated_pw},
        format="json",
    )
    assert res_wrong.status_code == 400
    assert "current_password" in res_wrong.json()

    # Reuse current password
    res_same = client_primary.post(
        "/api/v1/auth/change-password/",
        {"current_password": initial_pw, "new_password": initial_pw},
        format="json",
    )
    assert res_same.status_code == 400
    assert "new_password" in res_same.json()

    # Blank confirm_password must NOT bypass validation
    res_blank_confirm = client_primary.post(
        "/api/v1/auth/change-password/",
        {
            "current_password": initial_pw,
            "new_password": rotated_pw,
            "confirm_password": "",
        },
        format="json",
    )
    assert res_blank_confirm.status_code == 400
    assert "confirm_password" in res_blank_confirm.json()

    # Mismatched confirm_password
    res_mismatch = client_primary.post(
        "/api/v1/auth/change-password/",
        {
            "current_password": initial_pw,
            "new_password": rotated_pw,
            "confirm_password": "DifferentPassword#2026",
        },
        format="json",
    )
    assert res_mismatch.status_code == 400
    assert "confirm_password" in res_mismatch.json()

    # Django AUTH_PASSWORD_VALIDATORS enforcement (short, common, numeric, similar)
    for weak in ("short1", "password", "1234567890", "rotator_user2026"):
        res_weak = client_primary.post(
            "/api/v1/auth/change-password/",
            {"current_password": initial_pw, "new_password": weak},
            format="json",
        )
        assert res_weak.status_code == 400, f"Expected 400 for weak password {weak!r}"
        assert "new_password" in res_weak.json()

    # Successful password rotation keeps primary session alive and invalidates other session
    res_ok = client_primary.post(
        "/api/v1/auth/change-password/",
        {
            "current_password": initial_pw,
            "new_password": rotated_pw,
            "confirm_password": rotated_pw,
        },
        format="json",
    )
    assert res_ok.status_code == 200
    assert res_ok.json()["detail"] == "Password updated successfully."

    # Secondary session row is eagerly purged from django_session, leaving only primary
    other_session_key = client_other.cookies["sessionid"].value
    primary_session_key = client_primary.cookies["sessionid"].value
    assert Session.objects.filter(session_key=primary_session_key).exists()
    assert not Session.objects.filter(session_key=other_session_key).exists()

    # Active session stays authenticated via update_session_auth_hash
    assert client_primary.get("/api/v1/auth/me/").status_code == 200
    # Other session with old hash is rejected with unauthenticated 403
    res_other = client_other.get("/api/v1/auth/me/")
    assert res_other.status_code == 403
    assert "Authentication credentials were not provided" in res_other.json()["detail"]

    # Old password fails login, new password succeeds
    fresh = APIClient()
    assert (
        fresh.post(
            "/api/v1/auth/login/",
            {"username": user.username, "password": initial_pw},
            format="json",
        ).status_code
        == 401
    )
    assert (
        fresh.post(
            "/api/v1/auth/login/",
            {"username": user.username, "password": rotated_pw},
            format="json",
        ).status_code
        == 200
    )
