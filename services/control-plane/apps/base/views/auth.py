from django.conf import settings
from django.contrib.auth import (
    authenticate,
    login,
    logout,
    update_session_auth_hash,
)
from django.views.decorators.csrf import ensure_csrf_cookie
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from apps.base.serializers.auth import ChangePasswordSerializer, LoginSerializer
from apps.base.services.auth_security import (
    LoginRateLimitError,
    check_login_throttle,
    clear_login_account_failures,
    extract_client_ip,
    invalidate_user_sessions,
    record_login_failure,
)
from vektryn_contracts import sign_stream_token


def _serialize_user_session(user) -> dict[str, str | bool]:
    user_id = str(user.id)
    stream_token = sign_stream_token(user_id, settings.STREAM_AUTH_SECRET)
    return {
        "id": user_id,
        "username": user.get_username(),
        "email": getattr(user, "email", ""),
        "is_staff": bool(getattr(user, "is_staff", False)),
        "stream_token": stream_token,
    }


def _rate_limited_response(retry_after_seconds: int) -> Response:
    retry_after = max(1, int(retry_after_seconds))
    return Response(
        {
            "detail": f"Too many failed login attempts. Try again in {retry_after}s.",
            "retry_after_seconds": retry_after,
        },
        status=status.HTTP_429_TOO_MANY_REQUESTS,
        headers={"Retry-After": str(retry_after)},
    )


@api_view(["GET"])
@permission_classes([AllowAny])
@ensure_csrf_cookie
def csrf_cookie_view(_request: Request) -> Response:
    return Response({"detail": "CSRF cookie set"})


@api_view(["POST"])
@permission_classes([AllowAny])
def login_view(request: Request) -> Response:
    serializer = LoginSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(
            {"detail": "Username and password are required."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    username = serializer.validated_data["username"]
    password = serializer.validated_data["password"]
    client_ip = extract_client_ip(request._request)

    try:
        check_login_throttle(username, client_ip)
    except LoginRateLimitError as exc:
        return _rate_limited_response(exc.retry_after_seconds)

    user = authenticate(request._request, username=username, password=password)
    if user is None or not user.is_active:
        retry_after = record_login_failure(username, client_ip)
        if retry_after is not None:
            return _rate_limited_response(retry_after)
        return Response(
            {"detail": "Invalid username or password."},
            status=status.HTTP_401_UNAUTHORIZED,
        )

    clear_login_account_failures(username, client_ip)
    login(request._request, user)
    return Response(_serialize_user_session(user))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def logout_view(request: Request) -> Response:
    logout(request._request)
    return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def current_user_view(request: Request) -> Response:
    return Response(_serialize_user_session(request.user))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def change_password_view(request: Request) -> Response:
    serializer = ChangePasswordSerializer(
        data=request.data,
        context={"request": request},
    )
    serializer.is_valid(raise_exception=True)

    user = request.user
    user.set_password(serializer.validated_data["new_password"])
    user.save(update_fields=["password"])
    update_session_auth_hash(request._request, user)
    invalidate_user_sessions(
        user.pk,
        exclude_session_key=request._request.session.session_key,
    )
    return Response(
        {"detail": "Password updated successfully."},
        status=status.HTTP_200_OK,
    )
