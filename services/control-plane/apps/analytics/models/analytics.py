from django.db import models

from apps.base.models.base_model import TimestampsOnlyBaseModel, enum_choices
from vektryn_contracts.enums import TechCategory


class StackTrendDaily(TimestampsOnlyBaseModel):
    bucket_date = models.DateField()
    tag = models.CharField(max_length=64)
    category = models.CharField(
        max_length=32,
        choices=enum_choices(TechCategory),
        default=TechCategory.OTHER,
    )

    mention_count = models.PositiveIntegerField(default=0)
    unique_companies_count = models.PositiveIntegerField(default=0)
    median_annual_usd = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
    )

    class Meta:
        ordering = ["-bucket_date", "-mention_count"]
        constraints = [
            models.UniqueConstraint(
                fields=["bucket_date", "tag"],
                name="uq_stack_trend_daily_bucket_tag",
            ),
        ]
        indexes = [
            models.Index(
                fields=["category", "bucket_date", "-mention_count"],
                name="idx_stack_trend_category_date",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.bucket_date} | {self.tag} ({self.mention_count})"