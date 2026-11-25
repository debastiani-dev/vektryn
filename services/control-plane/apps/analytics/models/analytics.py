from django.db import models

from apps.base.models.base_model import TimestampsOnlyBaseModel, enum_choices
from vektryn_contracts.enums import ATSSource, TechCategory


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


class CollectorRunLog(TimestampsOnlyBaseModel):
    source = models.CharField(
        max_length=32,
        choices=enum_choices(ATSSource),
    )
    fetched_count = models.PositiveIntegerField(default=0)
    ingested_count = models.PositiveIntegerField(default=0)
    deduped_count = models.PositiveIntegerField(default=0)
    error_count = models.PositiveIntegerField(default=0)
    duration_ms = models.PositiveIntegerField(default=0)
    ran_at = models.DateTimeField(db_index=True)

    class Meta:
        ordering = ["-ran_at", "source"]
        indexes = [
            models.Index(
                fields=["source", "-ran_at"],
                name="idx_collector_run_source_ran",
            ),
        ]

    def __str__(self) -> str:
        return (
            f"{self.source} @ {self.ran_at:%Y-%m-%d %H:%M} "
            f"(in={self.ingested_count}, dup={self.deduped_count}, err={self.error_count})"
        )
