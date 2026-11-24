from django.conf import settings
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from vektryn_contracts import sign_stream_token


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def current_user_view(request: Request) -> Response:
    user = request.user
    user_id = str(user.id)
    stream_token = sign_stream_token(user_id, settings.STREAM_AUTH_SECRET)
    return Response(
        {
            "id": user_id,
            "username": user.get_username(),
            "email": getattr(user, "email", ""),
            "stream_token": stream_token,
        }
    )
