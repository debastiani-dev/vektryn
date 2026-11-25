from rest_framework import parsers, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.resumes.models.resumes import ResumeProfile
from apps.resumes.serializers.resumes import (
    ResumeProfileSerializer,
    ResumeRescoreRequestSerializer,
)
from apps.resumes.services.rescore_publisher import (
    RescoreBrokerError,
    RescoreCooldownError,
)
from apps.resumes.services.resume_service import ResumeService


class ResumeProfileViewSet(viewsets.ModelViewSet):
    serializer_class = ResumeProfileSerializer
    parser_classes = [parsers.JSONParser, parsers.MultiPartParser, parsers.FormParser]
    lookup_field = "uuid"
    queryset = ResumeProfile.objects.none()

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return ResumeProfile.objects.none()
        return ResumeProfile.objects.filter(user=self.request.user)

    @action(detail=True, methods=["post"], url_path="rescore")
    def rescore(self, request, uuid=None):
        profile = self.get_object()
        serializer = ResumeRescoreRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        service = ResumeService(user=request.user)
        try:
            event = service.trigger_rescore(
                instance=profile,
                max_jobs=serializer.validated_data["max_jobs"],
                force=serializer.validated_data["force"],
            )
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except RescoreCooldownError as exc:
            return Response(
                {"detail": str(exc), "retry_after": exc.retry_after},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
                headers={"Retry-After": str(exc.retry_after)},
            )
        except RescoreBrokerError:
            return Response(
                {
                    "detail": "Unable to queue rescore job right now. Please retry shortly."
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        return Response(
            {
                "status": "queued",
                "event_id": str(event.event_id),
                "resume_profile_uuid": str(profile.uuid),
                "max_jobs": event.max_jobs,
                "force": event.force,
            },
            status=status.HTTP_202_ACCEPTED,
        )
