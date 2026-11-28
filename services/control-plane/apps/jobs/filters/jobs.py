import django_filters
from rest_framework.exceptions import ValidationError as DRFValidationError

from apps.jobs.models.jobs import JobPosting
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
    tech = django_filters.CharFilter(method="filter_tech")
    region = django_filters.CharFilter(method="filter_region")
    work_mode = django_filters.CharFilter(method="filter_work_mode")
    language = django_filters.CharFilter(method="filter_language")
    min_salary = django_filters.NumberFilter(field_name="salary_max", lookup_expr="gte")

    class Meta:
        model = JobPosting
        fields = [
            "ats_source",
            "external_id",
            "seniority",
            "contract_type",
            "is_active",
        ]

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
