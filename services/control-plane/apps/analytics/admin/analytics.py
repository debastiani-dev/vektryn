from django.contrib import admin

from apps.analytics.models.analytics import CollectorRunLog, StackTrendDaily


@admin.register(StackTrendDaily)
class StackTrendDailyAdmin(admin.ModelAdmin):
    list_display = (
        "bucket_date",
        "tag",
        "category",
        "mention_count",
        "unique_companies_count",
        "median_annual_usd",
    )
    list_filter = ("category", "bucket_date")
    search_fields = ("tag",)


@admin.register(CollectorRunLog)
class CollectorRunLogAdmin(admin.ModelAdmin):
    list_display = (
        "ran_at",
        "source",
        "fetched_count",
        "ingested_count",
        "deduped_count",
        "error_count",
        "duration_ms",
    )
    list_filter = ("source",)
    ordering = ("-ran_at", "source")
