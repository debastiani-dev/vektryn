from django.conf import settings
from django.db import models

from apps.base.models.base_model import BaseModel, enum_choices
from vektryn_contracts.enums import NotificationKind


class Notification(BaseModel):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notifications",
    )
    kind = models.CharField(
        max_length=32,
        choices=enum_choices(NotificationKind),
    )
    title = models.CharField(max_length=255)
    body = models.TextField(blank=True, default="")
    payload = models.JSONField(default=dict, blank=True)
    read_at = models.DateTimeField(null=True, blank=True)
    dismissed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["user", "read_at", "-created_at"],
                name="idx_notif_user_read_created",
            ),
        ]

    def __str__(self) -> str:
        return f"[{self.kind}] {self.title} (user={self.user_id})"
