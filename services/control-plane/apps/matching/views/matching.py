from rest_framework import viewsets

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
        return MatchScore.objects.select_related(
            "job_posting", "resume_profile"
        ).filter(resume_profile__user=self.request.user)
