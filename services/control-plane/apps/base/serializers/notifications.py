from rest_framework import serializers

from apps.base.models.notification import Notification


class NotificationSerializer(serializers.ModelSerializer):
    is_read = serializers.SerializerMethodField()

    class Meta:
        model = Notification
        fields = (
            "uuid",
            "kind",
            "title",
            "body",
            "payload",
            "read_at",
            "dismissed_at",
            "is_read",
            "created_at",
            "modified_at",
        )
        read_only_fields = fields

    def get_is_read(self, obj: Notification) -> bool:
        return obj.read_at is not None
