"""Shared pytest fixtures for fast, deterministic Django tests."""

import pytest


@pytest.fixture(autouse=True)
def _fast_password_hasher(settings) -> None:
    """Use Django's fast MD5 hasher in tests to avoid ~1M-iteration PBKDF2 overhead."""
    settings.PASSWORD_HASHERS = [
        "django.contrib.auth.hashers.MD5PasswordHasher",
    ]
