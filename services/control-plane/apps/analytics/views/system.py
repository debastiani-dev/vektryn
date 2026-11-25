from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAdminUser, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from apps.analytics.services.collector_trigger import (
    CollectCooldownError,
    CollectTriggerError,
    trigger_collector_sync,
)
from apps.analytics.services.system_status import build_system_status_payload


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def system_status_view(request: Request) -> Response:
    payload = build_system_status_payload(request.user)
    return Response(payload, status=status.HTTP_200_OK)


@api_view(["POST"])
@permission_classes([IsAuthenticated, IsAdminUser])
def trigger_collector_sync_view(_request: Request) -> Response:
    try:
        result = trigger_collector_sync()
    except CollectCooldownError as exc:
        return Response(
            {"detail": str(exc), "retry_after": exc.retry_after},
            status=status.HTTP_429_TOO_MANY_REQUESTS,
            headers={"Retry-After": str(exc.retry_after)},
        )
    except CollectTriggerError as exc:
        return Response(
            {"detail": str(exc)},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    return Response(result, status=status.HTTP_202_ACCEPTED)
