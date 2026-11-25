from django.db.models import Count, Q
from rest_framework import viewsets
from rest_framework.response import Response

from apps.matching.filters.matching import MatchScoreFilter
from apps.matching.models.matching import MatchScore
from apps.matching.serializers.matching import MatchScoreSerializer


class MatchScoreViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = MatchScoreSerializer
    filterset_class = MatchScoreFilter
    ordering_fields = ["fit_score", "cosine_similarity", "created_at"]
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
            if not include_inactive:
                qs = qs.filter(job_posting__is_active=True)
        return qs

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        summary = queryset.aggregate(
            ai_scored_count=Count("uuid", filter=Q(fit_score__isnull=False)),
            strong_fit_count=Count("uuid", filter=Q(fit_score__gte=80)),
            alert_threshold_count=Count("uuid", filter=Q(fit_score__gte=70)),
        )

        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            response = self.get_paginated_response(serializer.data)
            response.data["summary"] = summary
            return response

        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)
