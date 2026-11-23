from django.contrib import admin

from apps.analytics.models.analytics import StackTrendDaily


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