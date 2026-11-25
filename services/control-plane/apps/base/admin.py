from django.contrib import admin

from apps.base.models.notification import Notification


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = (
        "created_at",
        "user",
        "kind",
        "title",
        "read_at",
        "dismissed_at",
    )
    list_filter = ("kind", "read_at", "dismissed_at")
    search_fields = ("title", "body", "user__username")
    ordering = ("-created_at",)
