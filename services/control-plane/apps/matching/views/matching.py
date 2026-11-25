from django.db.models import Count, F, Q
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.filters import OrderingFilter
from rest_framework.response import Response

from apps.jobs.models.jobs import JobPosting
from apps.jobs.services.hybrid_search import (
    annotate_rrf_score,
    execute_hybrid_search,
    extract_search_query,
)
from apps.jobs.services.triage import apply_triage_filters
from apps.matching.filters.matching import MatchScoreFilter
from apps.matching.models.artifacts import MatchArtifact
from apps.matching.models.matching import MatchScore
from apps.matching.serializers.artifacts import (
    MatchArtifactGenerateSerializer,
    MatchArtifactSerializer,
)
from apps.matching.serializers.matching import MatchScoreSerializer
from apps.matching.services.copilot import (
    CopilotRateLimitError,
    CopilotUnavailableError,
    get_or_generate_match_artifact,
)


class NullsLastOrderingFilter(OrderingFilter):
    """Apply NULLS LAST for nullable ordering fields so unscored/undated rows sort below populated rows."""

    nulls_last_fields = frozenset({"fit_score", "job_posting__posted_at"})

    def filter_queryset(self, request, queryset, view):
        ordering = self.get_ordering(request, queryset, view)
        if not ordering:
            return queryset

        expressions = []
        for term in ordering:
            descending = term.startswith("-")
            field_name = term.lstrip("-")
            if field_name in self.nulls_last_fields:
                expr = F(field_name)
                expressions.append(
                    expr.desc(nulls_last=True)
                    if descending
                    else expr.asc(nulls_last=True)
                )
            else:
                expressions.append(term)
        return queryset.order_by(*expressions)


class MatchScoreViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = MatchScoreSerializer
    filter_backends = [DjangoFilterBackend, NullsLastOrderingFilter]
    filterset_class = MatchScoreFilter
    ordering_fields = [
        "fit_score",
        "cosine_similarity",
        "created_at",
        "job_posting__posted_at",
    ]
    ordering = ["-fit_score", "-cosine_similarity", "-created_at"]
    lookup_field = "uuid"
    queryset = MatchScore.objects.none()

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return MatchScore.objects.none()
        qs = MatchScore.objects.select_related("job_posting", "resume_profile").filter(
            resume_profile__user=self.request.user,
            job_posting__is_deleted=False,
        )
        if self.action == "list":
            include_inactive = self.request.query_params.get(
                "include_inactive", ""
            ).lower() in {"1", "true", "yes"}
            has_explicit_active = "is_active" in self.request.query_params
            if not include_inactive and not has_explicit_active:
                qs = qs.filter(job_posting__is_active=True)
        return qs

    def list(self, request, *args, **kwargs):
        structured_qs = DjangoFilterBackend().filter_queryset(
            request, self.get_queryset(), self
        )
        structured_qs = apply_triage_filters(
            structured_qs,
            request,
            job_id_field="job_posting_id",
            company_field="job_posting__company_name",
        )
        search_query = extract_search_query(request.query_params)
        search_mode: str | None = None

        if search_query:
            base_jobs = JobPosting.objects.filter(
                uuid__in=structured_qs.values("job_posting_id")
            )
            result = execute_hybrid_search(base_jobs, search_query)
            search_mode = result.search_mode
            matched_ids = list(result.rrf_scores.keys())
            summary_qs = structured_qs.filter(job_posting_id__in=matched_ids)
            if "ordering" in request.query_params:
                ordered_qs = NullsLastOrderingFilter().filter_queryset(
                    request, summary_qs, self
                )
            else:
                ordered_qs = annotate_rrf_score(
                    structured_qs, result.rrf_scores, id_field="job_posting_id"
                ).order_by(
                    "-rrf_score",
                    F("fit_score").desc(nulls_last=True),
                    "-cosine_similarity",
                    "-created_at",
                )
        else:
            summary_qs = structured_qs
            ordered_qs = NullsLastOrderingFilter().filter_queryset(
                request, structured_qs, self
            )

        summary = summary_qs.aggregate(
            ai_scored_count=Count("uuid", filter=Q(fit_score__isnull=False)),
            strong_fit_count=Count("uuid", filter=Q(fit_score__gte=80)),
            alert_threshold_count=Count(
                "uuid", filter=Q(fit_score__gte=F("resume_profile__min_alert_score"))
            ),
        )

        page = self.paginate_queryset(ordered_qs)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            response = self.get_paginated_response(serializer.data)
            response.data["summary"] = summary
            response.data["search_mode"] = search_mode
            return response

        serializer = self.get_serializer(ordered_qs, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=["get", "post"], url_path="artifacts")
    def artifacts(self, request, uuid=None):
        match_score = self.get_object()

        if request.method == "GET":
            queryset = (
                MatchArtifact.objects.select_related("match_score__resume_profile")
                .filter(user=request.user, match_score=match_score)
                .order_by("-created_at")
            )
            serializer = MatchArtifactSerializer(queryset, many=True)
            return Response({"results": serializer.data})

        input_serializer = MatchArtifactGenerateSerializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)
        data = input_serializer.validated_data

        try:
            result = get_or_generate_match_artifact(
                user=request.user,
                match_score=match_score,
                kind=data["kind"],
                regenerate=data.get("regenerate", False),
                tone=data.get("tone"),
                guidance=data.get("guidance", ""),
            )
        except CopilotRateLimitError as exc:
            return Response(
                {
                    "detail": str(exc),
                    "retry_after_seconds": exc.retry_after_seconds,
                },
                status=status.HTTP_429_TOO_MANY_REQUESTS,
                headers={"Retry-After": str(exc.retry_after_seconds)},
            )
        except CopilotUnavailableError as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        payload = MatchArtifactSerializer(result.artifact).data
        payload["cached"] = result.cached
        http_status = status.HTTP_201_CREATED if result.created else status.HTTP_200_OK
        return Response(payload, status=http_status)
