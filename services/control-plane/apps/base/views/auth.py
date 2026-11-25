from django.conf import settings
from django.contrib.auth import authenticate, login, logout
from django.views.decorators.csrf import ensure_csrf_cookie
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

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


@api_view(["GET"])
@permission_classes([AllowAny])
@ensure_csrf_cookie
def csrf_cookie_view(_request: Request) -> Response:
    return Response({"detail": "CSRF cookie set"})


@api_view(["POST"])
@permission_classes([AllowAny])
def login_view(request: Request) -> Response:
    username = str(request.data.get("username", "")).strip()
    password = str(request.data.get("password", ""))
    if not username or not password:
        return Response(
            {"detail": "Username and password are required."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    user = authenticate(request._request, username=username, password=password)
    if user is None or not user.is_active:
        return Response(
            {"detail": "Invalid username or password."},
            status=status.HTTP_401_UNAUTHORIZED,
        )

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
