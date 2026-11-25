from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.jobs.filters.jobs import JobPostingFilter
from apps.jobs.models.jobs import JobPosting
from apps.jobs.serializers.jobs import (
    JobPostingDetailSerializer,
    JobPostingSummarySerializer,
    ManualJobImportSerializer,
)
from apps.jobs.services.manual_import import (
    ManualImportFetchError,
    ManualImportIngestError,
    ManualImportRateLimitError,
    ManualImportValidationError,
    ManualJobImportService,
)


class JobPostingViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = JobPosting.objects.all()
    filterset_class = JobPostingFilter
    ordering_fields = ["created_at", "posted_at", "salary_max"]
    ordering = ["-created_at"]
    lookup_field = "uuid"

    def get_serializer_class(self):
        if self.action == "retrieve":
            return JobPostingDetailSerializer
        if self.action == "import_job":
            return ManualJobImportSerializer
        return JobPostingSummarySerializer

    @action(detail=False, methods=["post"], url_path="import")
    def import_job(self, request):
        serializer = ManualJobImportSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        service = ManualJobImportService(user=request.user)
        try:
            result = service.import_job(serializer.validated_data)
        except ManualImportValidationError as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except ManualImportFetchError as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        except ManualImportRateLimitError as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
                headers={"Retry-After": str(exc.retry_after)},
            )
        except ManualImportIngestError as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        payload = {
            "status": result.status,
            "ats_source": result.ats_source,
            "external_id": result.external_id,
            "content_hash": result.content_hash,
            "title": result.title,
            "company_name": result.company_name,
            "apply_url": result.apply_url,
            "event_id": result.event_id,
            "job_posting_uuid": (
                str(result.job_posting_uuid) if result.job_posting_uuid else None
            ),
        }
        http_status = (
            status.HTTP_202_ACCEPTED
            if result.status == "queued"
            else status.HTTP_200_OK
        )
        return Response(payload, status=http_status)
