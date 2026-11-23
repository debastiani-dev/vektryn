from django.contrib import admin

from apps.resumes.models.resumes import ResumeProfile


@admin.register(ResumeProfile)
class ResumeProfileAdmin(admin.ModelAdmin):
    list_display = ("label", "user", "min_alert_score", "is_active", "created_at")
    list_filter = ("is_active", "is_deleted")
    search_fields = ("label", "user__username")
    readonly_fields = ("uuid", "content_hash", "created_at", "modified_at")