from django.contrib import admin

from apps.tracker.models.tracker import ApplicationLead


@admin.register(ApplicationLead)
class ApplicationLeadAdmin(admin.ModelAdmin):
    list_display = (
        "job_posting",
        "user",
        "status",
        "priority",
        "applied_at",
        "last_activity_at",
    )
    list_filter = ("status", "priority", "is_deleted")
    readonly_fields = ("uuid", "created_at", "modified_at")
