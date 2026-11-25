from django.contrib import admin

from apps.base.models.notification import Notification
from apps.base.models.user_profile import UserProfile


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


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "display_name",
        "timezone",
        "preferred_currency",
        "default_copilot_tone",
        "modified_at",
    )
    list_filter = ("preferred_currency", "default_copilot_tone")
    search_fields = ("user__username", "user__email", "display_name")
    ordering = ("-modified_at",)
