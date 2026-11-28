from uuid import UUID

from django.db.models import Count, F, Prefetch, Q
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.response import Response

from apps.base.services.byok import (
    BYOKInvalidKeyError,
    BYOKMissingError,
    BYOKQuotaExhaustedError,
    BYOKStorageUnavailableError,
)
from apps.jobs.filters.salary_filtering import (
    NullsLastOrderingFilter,
    apply_salary_filters,
    parse_and_validate_salary_filter_params,
)
from apps.jobs.models.jobs import JobPosting, JobPostingSource
from apps.jobs.services.fx_rates import (
    get_request_fx_snapshot,
    resolve_display_currency,
)
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
from apps.resumes.models.resumes import ResumeProfile


class MatchScoreViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = MatchScoreSerializer
    filter_backends = [DjangoFilterBackend, NullsLastOrderingFilter]
    filterset_class = MatchScoreFilter
    ordering_fields = [
        "fit_score",
        "cosine_similarity",
        "created_at",
        "job_posting__posted_at",
        "job_posting__salary_annual_mid_usd",
        "job_posting__salary_annual_max_usd",
    ]
    ordering = ["-fit_score", "-cosine_similarity", "-created_at"]
    lookup_field = "uuid"
    queryset = MatchScore.objects.none()

    def get_serializer_context(self):
        context = super().get_serializer_context()
        if self.action in ("list", "retrieve"):
            fx_snapshot = get_request_fx_snapshot(self.request)
            context["fx_snapshot"] = fx_snapshot
            context["display_currency"] = resolve_display_currency(
                self.request, fx_snapshot
            )
        return context

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return MatchScore.objects.none()
        qs = (
            MatchScore.objects.select_related("job_posting", "resume_profile")
            .prefetch_related(
                Prefetch(
                    "job_posting__sources",
                    queryset=JobPostingSource.objects.filter(is_deleted=False).order_by(
                        "-is_primary", "first_seen_at"
                    ),
                    to_attr="prefetched_sources",
                )
            )
            .filter(
                resume_profile__user=self.request.user,
                resume_profile__is_deleted=False,
                job_posting__is_deleted=False,
            )
        )
        if self.action == "list":
            raw_resume_param = (
                self.request.query_params.get("resume_profile") or ""
            ).strip()
            if raw_resume_param:
                try:
                    resume_uuid = UUID(raw_resume_param)
                except ValueError as exc:
                    raise ValidationError(
                        {"resume_profile": "Must be a valid UUID."}
                    ) from exc
                if not ResumeProfile.objects.filter(
                    uuid=resume_uuid, user=self.request.user
                ).exists():
                    raise NotFound("Resume profile not found.")
            else:
                qs = qs.filter(
                    resume_profile__is_active=True,
                    is_routed_winner=True,
                )

            include_inactive = self.request.query_params.get(
                "include_inactive", ""
            ).lower() in {"1", "true", "yes"}
            has_explicit_active = "is_active" in self.request.query_params
            if not include_inactive and not has_explicit_active:
                qs = qs.filter(job_posting__is_active=True)
        return qs

    def _apply_match_ordering(self, request, queryset):
        if (
            "ordering" not in request.query_params
            and (request.query_params.get("sort_by") or "").strip().lower() == "salary"
        ):
            return queryset.order_by(
                F("job_posting__salary_annual_mid_usd").desc(nulls_last=True),
                F("fit_score").desc(nulls_last=True),
                "-created_at",
            )
        return NullsLastOrderingFilter().filter_queryset(request, queryset, self)

    def list(self, request, *args, **kwargs):
        fx_snapshot = get_request_fx_snapshot(request)
        resolve_display_currency(request, fx_snapshot)
        salary_bounds = parse_and_validate_salary_filter_params(
            request.query_params,
            user=request.user,
            fx_snapshot=fx_snapshot,
        )

        structured_qs = DjangoFilterBackend().filter_queryset(
            request, self.get_queryset(), self
        )
        structured_qs = apply_salary_filters(
            structured_qs, salary_bounds, field_prefix="job_posting__"
        )
        structured_qs = apply_triage_filters(
            structured_qs,
            request,
            job_id_field="job_posting_id",
            company_field="job_posting__company_name",
        )
        search_query = extract_search_query(request.query_params)
        search_mode: str | None = None
        has_explicit_ordering = (
            "ordering" in request.query_params
            or (request.query_params.get("sort_by") or "").strip().lower() == "salary"
        )

        if search_query:
            base_jobs = JobPosting.objects.filter(
                uuid__in=structured_qs.values("job_posting_id")
            )
            result = execute_hybrid_search(base_jobs, search_query, user=request.user)
            search_mode = result.search_mode
            matched_ids = list(result.rrf_scores.keys())
            summary_qs = structured_qs.filter(job_posting_id__in=matched_ids)
            if has_explicit_ordering:
                ordered_qs = self._apply_match_ordering(request, summary_qs)
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
            ordered_qs = self._apply_match_ordering(request, structured_qs)

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
        except BYOKMissingError as exc:
            return Response(
                {"detail": str(exc), "code": exc.code},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except BYOKInvalidKeyError as exc:
            return Response(
                {"detail": str(exc), "code": exc.code},
                status=status.HTTP_403_FORBIDDEN,
            )
        except BYOKQuotaExhaustedError as exc:
            return Response(
                {
                    "detail": str(exc),
                    "code": exc.code,
                    "payment_required": exc.payment_required,
                },
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )
        except BYOKStorageUnavailableError as exc:
            return Response(
                {"detail": str(exc), "code": exc.code},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        except CopilotRateLimitError as exc:
            return Response(
                {
                    "detail": str(exc),
                    "code": "copilot_rate_limited",
                    "retry_after_seconds": exc.retry_after_seconds,
                },
                status=status.HTTP_429_TOO_MANY_REQUESTS,
                headers={"Retry-After": str(exc.retry_after_seconds)},
            )
        except CopilotUnavailableError as exc:
            return Response(
                {"detail": str(exc), "code": "copilot_unavailable"},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        payload = MatchArtifactSerializer(result.artifact).data
        payload["cached"] = result.cached
        http_status = status.HTTP_201_CREATED if result.created else status.HTTP_200_OK
        return Response(payload, status=http_status)
