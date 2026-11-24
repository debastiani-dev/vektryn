from django.contrib.auth.models import AbstractBaseUser


class BaseService:
    """Shared base class for domain services encapsulating business logic."""

    def __init__(self, user: AbstractBaseUser | None = None) -> None:
        self.user = user
