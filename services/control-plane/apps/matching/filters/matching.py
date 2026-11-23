import django_filters
from django.db.models import F

from apps.matching.models.matching import MatchScore


class MatchScoreFilter(django_filters.FilterSet):
    resume_profile = django_filters.UUIDFilter(field_name="resume_profile__uuid")
    min_fit_score = django_filters.NumberFilter(field_name="fit_score", lookup_expr="gte")
    min_cosine = django_filters.NumberFilter(
        field_name="cosine_similarity", lookup_expr="gte"
    )
    evaluated_only = django_filters.BooleanFilter(method="filter_evaluated_only")
    is_stale = django_filters.BooleanFilter(method="filter_is_stale")

    class Meta:
        model = MatchScore
        fields = ["resume_profile", "scoring_model"]

    def filter_evaluated_only(self, queryset, _name: str, value: bool):
        if value:
            return queryset.filter(fit_score__isnull=False)
        return queryset

    def filter_is_stale(self, queryset, _name: str, value: bool):
        if value:
            return queryset.exclude(
                resume_content_hash=F("resume_profile__content_hash")
            )
        return queryset.filter(resume_content_hash=F("resume_profile__content_hash"))