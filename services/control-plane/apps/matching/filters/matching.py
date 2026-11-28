import django_filters
from django.db.models import F

from apps.jobs.filters.jobs import parse_language_filter_values
from apps.matching.models.matching import MatchScore


class MatchScoreFilter(django_filters.FilterSet):
    resume_profile = django_filters.UUIDFilter(field_name="resume_profile__uuid")
    external_id = django_filters.CharFilter(field_name="job_posting__external_id")
    min_fit_score = django_filters.NumberFilter(
        field_name="fit_score", lookup_expr="gte"
    )
    min_cosine = django_filters.NumberFilter(
        field_name="cosine_similarity", lookup_expr="gte"
    )
    evaluated_only = django_filters.BooleanFilter(method="filter_evaluated_only")
    is_stale = django_filters.BooleanFilter(method="filter_is_stale")
    seniority = django_filters.CharFilter(field_name="job_posting__seniority")
    contract_type = django_filters.CharFilter(field_name="job_posting__contract_type")
    work_mode = django_filters.CharFilter(method="filter_work_mode")
    language = django_filters.CharFilter(method="filter_language")
    ats_source = django_filters.CharFilter(field_name="job_posting__ats_source")
    region = django_filters.CharFilter(method="filter_region")
    tech = django_filters.CharFilter(method="filter_tech")
    is_active = django_filters.BooleanFilter(field_name="job_posting__is_active")

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

    def filter_region(self, queryset, _name: str, value: str):
        regions = [r.strip().lower() for r in value.split(",") if r.strip()]
        if not regions:
            return queryset
        return queryset.filter(job_posting__region_eligibility__overlap=regions)

    def filter_tech(self, queryset, _name: str, value: str):
        tags = [t.strip().lower() for t in value.split(",") if t.strip()]
        for tag in tags:
            queryset = queryset.filter(job_posting__tech_stack__contains=[tag])
        return queryset

    def filter_work_mode(self, queryset, _name: str, value: str):
        modes = [m.strip().lower() for m in value.split(",") if m.strip()]
        if not modes:
            return queryset
        return queryset.filter(job_posting__work_mode__in=modes)

    def filter_language(self, queryset, _name: str, value: str):
        languages = parse_language_filter_values(value)
        if not languages:
            return queryset
        return queryset.filter(job_posting__language__in=languages)
