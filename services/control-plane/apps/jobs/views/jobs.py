from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.filters import OrderingFilter
from rest_framework.response import Response

from apps.jobs.filters.jobs import JobPostingFilter
from apps.jobs.models.jobs import JobPosting
from apps.jobs.serializers.jobs import (
    JobPostingDetailSerializer,
    JobPostingSummarySerializer,
    ManualJobImportSerializer,
)
from apps.jobs.services.hybrid_search import (
    annotate_rrf_score,
    execute_hybrid_search,
    extract_search_query,
)
from apps.jobs.services.manual_import import (
    ManualImportFetchError,
    ManualImportIngestError,
    ManualImportRateLimitError,
    ManualImportValidationError,
    ManualJobImportService,
)
from apps.jobs.services.triage import apply_triage_filters


class JobPostingViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = JobPosting.objects.all()
    filter_backends = [DjangoFilterBackend, OrderingFilter]
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

    def list(self, request, *args, **kwargs):
        structured_qs = DjangoFilterBackend().filter_queryset(
            request, self.get_queryset(), self
        )
        structured_qs = apply_triage_filters(
            structured_qs,
            request,
            job_id_field="uuid",
            company_field="company_name",
        )
        search_query = extract_search_query(request.query_params)
        search_mode: str | None = None

        if search_query:
            result = execute_hybrid_search(
                structured_qs, search_query, user=request.user
            )
            search_mode = result.search_mode
            if "ordering" in request.query_params:
                filtered_qs = structured_qs.filter(
                    uuid__in=list(result.rrf_scores.keys())
                )
                ordered_qs = OrderingFilter().filter_queryset(
                    request, filtered_qs, self
                )
            else:
                ordered_qs = annotate_rrf_score(
                    structured_qs, result.rrf_scores, id_field="uuid"
                ).order_by("-rrf_score", "-created_at")
        else:
            ordered_qs = OrderingFilter().filter_queryset(request, structured_qs, self)

        page = self.paginate_queryset(ordered_qs)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            response = self.get_paginated_response(serializer.data)
            response.data["search_mode"] = search_mode
            return response

        serializer = self.get_serializer(ordered_qs, many=True)
        return Response(serializer.data)

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
