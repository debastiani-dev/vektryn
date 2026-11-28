import django_filters
from django.db.models import Exists, OuterRef, Q
from rest_framework.exceptions import ValidationError as DRFValidationError

from apps.jobs.models.jobs import JobPosting, JobPostingSource
from vektryn_contracts.language import normalize_language_code


def parse_language_filter_values(value: str) -> list[str]:
    tokens = [part.strip() for part in value.split(",") if part.strip()]
    normalized: list[str] = []
    for token in tokens:
        try:
            code = normalize_language_code(token, strict=True)
        except ValueError as exc:
            raise DRFValidationError(
                {"language": f"Invalid ISO 639-1 language code: {token!r}."}
            ) from exc
        if code not in normalized:
            normalized.append(code)
    return normalized


class JobPostingFilter(django_filters.FilterSet):
    ats_source = django_filters.CharFilter(method="filter_ats_source")
    hide_reposts = django_filters.BooleanFilter(method="filter_hide_reposts")
    tech = django_filters.CharFilter(method="filter_tech")
    region = django_filters.CharFilter(method="filter_region")
    work_mode = django_filters.CharFilter(method="filter_work_mode")
    language = django_filters.CharFilter(method="filter_language")
    min_salary = django_filters.NumberFilter(field_name="salary_max", lookup_expr="gte")

    class Meta:
        model = JobPosting
        fields = [
            "external_id",
            "seniority",
            "contract_type",
            "is_active",
        ]

    def filter_ats_source(self, queryset, _name: str, value: str):
        sources = [s.strip().lower() for s in value.split(",") if s.strip()]
        if not sources:
            return queryset
        linked_source = JobPostingSource.objects.filter(
            job_posting_id=OuterRef("uuid"),
            ats_source__in=sources,
            is_deleted=False,
        )
        return queryset.filter(Exists(linked_source) | Q(ats_source__in=sources))

    def filter_hide_reposts(self, queryset, _name: str, value: bool):
        if value:
            return queryset.filter(repost_count=0)
        return queryset

    def filter_tech(self, queryset, _name: str, value: str):
        tags = [t.strip().lower() for t in value.split(",") if t.strip()]
        for tag in tags:
            queryset = queryset.filter(tech_stack__contains=[tag])
        return queryset

    def filter_region(self, queryset, _name: str, value: str):
        regions = [r.strip().lower() for r in value.split(",") if r.strip()]
        if not regions:
            return queryset
        return queryset.filter(region_eligibility__overlap=regions)

    def filter_work_mode(self, queryset, _name: str, value: str):
        modes = [m.strip().lower() for m in value.split(",") if m.strip()]
        if not modes:
            return queryset
        return queryset.filter(work_mode__in=modes)

    def filter_language(self, queryset, _name: str, value: str):
        languages = parse_language_filter_values(value)
        if not languages:
            return queryset
        return queryset.filter(language__in=languages)
