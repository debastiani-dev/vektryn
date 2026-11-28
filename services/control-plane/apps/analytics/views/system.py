from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAdminUser, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from apps.analytics.serializers.dlq import (
    DlqDismissRequestSerializer,
    DlqReplayRequestSerializer,
)
from apps.analytics.services.collector_trigger import (
    CollectCooldownError,
    CollectTriggerError,
    trigger_collector_sync,
)
from apps.analytics.services.dlq_inspector import (
    DEFAULT_DLQ_INSPECT_LIMIT,
    MAX_DLQ_INSPECT_LIMIT,
    DlqBrokerUnavailableError,
    DlqReplayCooldownError,
    dismiss_dlq_messages,
    inspect_dlq_messages,
    replay_dlq_messages,
)
from apps.analytics.services.system_status import build_system_status_payload
from apps.jobs.services.fx_rates import get_fx_snapshot


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def system_status_view(request: Request) -> Response:
    payload = build_system_status_payload(request.user)
    return Response(payload, status=status.HTTP_200_OK)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def system_fx_rates_view(_request: Request) -> Response:
    snapshot = get_fx_snapshot()
    return Response(snapshot.to_api_dict(), status=status.HTTP_200_OK)


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


@api_view(["GET"])
@permission_classes([IsAuthenticated, IsAdminUser])
def system_dlq_list_view(request: Request) -> Response:
    raw_limit = request.query_params.get("limit")
    limit = DEFAULT_DLQ_INSPECT_LIMIT
    if raw_limit is not None and raw_limit != "":
        try:
            limit = int(raw_limit)
        except ValueError:
            return Response(
                {"detail": "limit must be an integer."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if limit < 1 or limit > MAX_DLQ_INSPECT_LIMIT:
            return Response(
                {"detail": f"limit must be between 1 and {MAX_DLQ_INSPECT_LIMIT}."},
                status=status.HTTP_400_BAD_REQUEST,
            )

    original_topic = (request.query_params.get("original_topic") or "").strip() or None
    try:
        payload = inspect_dlq_messages(limit=limit, original_topic=original_topic)
    except DlqBrokerUnavailableError as exc:
        return Response(
            {"detail": str(exc)},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    return Response(payload, status=status.HTTP_200_OK)


@api_view(["POST"])
@permission_classes([IsAuthenticated, IsAdminUser])
def system_dlq_replay_view(request: Request) -> Response:
    serializer = DlqReplayRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data

    try:
        result = replay_dlq_messages(
            event_ids=data.get("event_ids"),
            limit=data.get("limit", 10),
            original_topic=data.get("original_topic"),
            dry_run=data.get("dry_run", True),
        )
    except DlqReplayCooldownError as exc:
        return Response(
            {"detail": str(exc), "retry_after_seconds": exc.retry_after},
            status=status.HTTP_429_TOO_MANY_REQUESTS,
            headers={"Retry-After": str(exc.retry_after)},
        )
    except DlqBrokerUnavailableError as exc:
        return Response(
            {"detail": str(exc)},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    return Response(result, status=status.HTTP_200_OK)


@api_view(["POST"])
@permission_classes([IsAuthenticated, IsAdminUser])
def system_dlq_dismiss_view(request: Request) -> Response:
    serializer = DlqDismissRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    try:
        result = dismiss_dlq_messages(serializer.validated_data["event_ids"])
    except DlqBrokerUnavailableError as exc:
        return Response(
            {"detail": str(exc)},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    return Response(result, status=status.HTTP_200_OK)
