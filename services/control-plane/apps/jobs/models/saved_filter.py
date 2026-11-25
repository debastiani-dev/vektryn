from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.base.models.base_model import BaseModel


class SavedFilter(BaseModel):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="saved_filters",
    )
    name = models.CharField(max_length=80)
    query_params = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["name", "-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "name"],
                condition=Q(is_deleted=False),
                name="uq_saved_filter_active_user_name",
            ),
        ]
        indexes = [
            models.Index(
                fields=["user", "-created_at"],
                name="idx_saved_filter_user_created",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.name} (user={self.user_id})"
