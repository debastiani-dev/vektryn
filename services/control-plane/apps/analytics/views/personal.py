from uuid import UUID

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from apps.analytics.services.personal_analytics import (
    ALLOWED_DAY_WINDOWS,
    build_personal_analytics_payload,
)
from apps.resumes.models.resumes import ResumeProfile


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def personal_analytics_view(request: Request) -> Response:
    days_param = (request.query_params.get("days") or "30").strip().lower()
    if days_param not in ALLOWED_DAY_WINDOWS:
        return Response(
            {"detail": "days must be one of: 30, 90, all."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    raw_resume = (request.query_params.get("resume_profile") or "").strip()
    resume_uuid: UUID | None = None
    if raw_resume:
        try:
            resume_uuid = UUID(raw_resume)
        except ValueError:
            return Response(
                {"detail": "resume_profile must be a valid UUID."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        owned = ResumeProfile.objects.filter(
            uuid=resume_uuid, user=request.user
        ).exists()
        if not owned:
            return Response(
                {"detail": "Resume profile not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

    payload = build_personal_analytics_payload(
        user=request.user,
        days_param=days_param,
        resume_profile_uuid=resume_uuid,
    )
    return Response(payload, status=status.HTTP_200_OK)
