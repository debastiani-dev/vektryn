from django.utils import timezone
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from apps.base.models.notification import Notification
from apps.base.serializers.notifications import NotificationSerializer
from apps.tracker.services.leads import sync_due_followup_notifications_for_user
from vektryn_contracts.enums import NotificationKind

_VALID_KINDS = frozenset(kind.value for kind in NotificationKind)
_TRUTHY_VALUES = frozenset({"1", "true", "yes"})


def _get_global_unread_count(user) -> int:
    return Notification.objects.filter(
        user=user,
        dismissed_at__isnull=True,
        read_at__isnull=True,
    ).count()


class NotificationViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    serializer_class = NotificationSerializer
    permission_classes = [IsAuthenticated]
    lookup_field = "uuid"
    queryset = Notification.objects.none()

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Notification.objects.none()
        return Notification.objects.filter(
            user=self.request.user,
            dismissed_at__isnull=True,
        ).order_by("-created_at")

    def list(self, request: Request, *args, **kwargs) -> Response:
        sync_due_followup_notifications_for_user(request.user)
        qs = self.get_queryset()
        unread_param = request.query_params.get("unread", "").strip().lower()
        if unread_param in _TRUTHY_VALUES:
            qs = qs.filter(read_at__isnull=True)

        kind_param = request.query_params.get("kind", "").strip().lower()
        if kind_param in _VALID_KINDS:
            qs = qs.filter(kind=kind_param)

        unread_count = _get_global_unread_count(request.user)
        page = self.paginate_queryset(qs)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            response = self.get_paginated_response(serializer.data)
            response.data["unread_count"] = unread_count
            return response

        serializer = self.get_serializer(qs, many=True)
        return Response(
            {
                "count": len(serializer.data),
                "next": None,
                "previous": None,
                "results": serializer.data,
                "unread_count": unread_count,
            }
        )

    @action(detail=True, methods=["patch"], url_path="read")
    def mark_read(self, request: Request, uuid=None) -> Response:
        notification = self.get_object()
        if notification.read_at is None:
            notification.read_at = timezone.now()
            notification.save(update_fields=["read_at"])
        data = self.get_serializer(notification).data
        return Response(
            {
                "notification": data,
                "unread_count": _get_global_unread_count(request.user),
            },
            status=status.HTTP_200_OK,
        )

    @action(detail=True, methods=["patch"], url_path="dismiss")
    def dismiss(self, request: Request, uuid=None) -> Response:
        notification = self.get_object()
        now = timezone.now()
        update_fields = ["dismissed_at"]
        notification.dismissed_at = now
        if notification.read_at is None:
            notification.read_at = now
            update_fields.append("read_at")
        notification.save(update_fields=update_fields)
        data = self.get_serializer(notification).data
        return Response(
            {
                "notification": data,
                "unread_count": _get_global_unread_count(request.user),
            },
            status=status.HTTP_200_OK,
        )

    @action(detail=False, methods=["post"], url_path="read-all")
    def read_all(self, request: Request) -> Response:
        now = timezone.now()
        updated = Notification.objects.filter(
            user=request.user,
            dismissed_at__isnull=True,
            read_at__isnull=True,
        ).update(read_at=now, modified_at=now)
        return Response(
            {
                "updated_count": updated,
                "unread_count": 0,
            },
            status=status.HTTP_200_OK,
        )
