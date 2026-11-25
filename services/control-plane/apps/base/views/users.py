from django.contrib.auth import get_user_model
from django.db.models import Q
from rest_framework import serializers, status, viewsets
from rest_framework.permissions import IsAdminUser, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from apps.base.serializers.users import (
    StaffUserCreateSerializer,
    StaffUserSerializer,
    StaffUserUpdateSerializer,
)
from apps.base.services.user_management import (
    DuplicateUsernameError,
    PrivilegedGuardError,
    create_staff_managed_user,
    soft_deactivate_staff_managed_user,
    update_staff_managed_user,
)

User = get_user_model()


def _parse_bool_filter(raw: str | None, param_name: str) -> bool | None:
    if raw is None or raw.strip() == "":
        return None
    normalized = raw.strip().lower()
    if normalized in {"true", "1"}:
        return True
    if normalized in {"false", "0"}:
        return False
    raise serializers.ValidationError({param_name: ["Must be 'true' or 'false'."]})


def _assert_actor_can_mutate_target(actor, target) -> Response | None:
    if target.is_superuser and not actor.is_superuser:
        return Response(
            {
                "detail": "Only a superuser can modify or deactivate a superuser account."
            },
            status=status.HTTP_403_FORBIDDEN,
        )
    return None


class StaffUserViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, IsAdminUser]
    serializer_class = StaffUserSerializer
    lookup_field = "id"
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_queryset(self):
        queryset = User.objects.select_related("profile").order_by(
            "-is_active", "-is_staff", "username"
        )
        params = self.request.query_params

        search = (params.get("search") or "").strip()
        if search:
            queryset = queryset.filter(
                Q(username__icontains=search)
                | Q(email__icontains=search)
                | Q(profile__display_name__icontains=search, profile__is_deleted=False)
            )

        is_active = _parse_bool_filter(params.get("is_active"), "is_active")
        if is_active is not None:
            queryset = queryset.filter(is_active=is_active)

        is_staff = _parse_bool_filter(params.get("is_staff"), "is_staff")
        if is_staff is not None:
            queryset = queryset.filter(is_staff=is_staff)

        return queryset

    def create(self, request: Request, *args, **kwargs) -> Response:
        serializer = StaffUserCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            user, profile = create_staff_managed_user(
                username=data["username"],
                password=data["password"],
                email=data.get("email", ""),
                is_staff=data.get("is_staff", False),
                is_active=data.get("is_active", True),
                profile_data=data.get("profile"),
            )
        except DuplicateUsernameError as exc:
            return Response(
                {"username": [str(exc)]},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user.profile = profile
        return Response(
            StaffUserSerializer(user).data,
            status=status.HTTP_201_CREATED,
        )

    def partial_update(self, request: Request, *args, **kwargs) -> Response:
        target = self.get_object()
        forbidden = _assert_actor_can_mutate_target(request.user, target)
        if forbidden is not None:
            return forbidden

        serializer = StaffUserUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        if target.pk == request.user.pk:
            if data.get("is_active") is False:
                return Response(
                    {
                        "is_active": [
                            "You cannot deactivate your own account from user management."
                        ]
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if data.get("is_staff") is False:
                return Response(
                    {"is_staff": ["You cannot remove your own staff privileges."]},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        try:
            updated_user, profile = update_staff_managed_user(
                target_user=target,
                email=data["email"] if "email" in data else None,
                is_active=data["is_active"] if "is_active" in data else None,
                is_staff=data["is_staff"] if "is_staff" in data else None,
                profile_data=data.get("profile"),
            )
        except PrivilegedGuardError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        updated_user.profile = profile
        return Response(
            StaffUserSerializer(updated_user).data, status=status.HTTP_200_OK
        )

    def destroy(self, request: Request, *args, **kwargs) -> Response:
        target = self.get_object()
        forbidden = _assert_actor_can_mutate_target(request.user, target)
        if forbidden is not None:
            return forbidden

        if target.pk == request.user.pk:
            return Response(
                {
                    "detail": "You cannot deactivate your own account from user management."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            updated_user, profile = soft_deactivate_staff_managed_user(
                target_user=target
            )
        except PrivilegedGuardError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        updated_user.profile = profile
        return Response(
            StaffUserSerializer(updated_user).data, status=status.HTTP_200_OK
        )
