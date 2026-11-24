import django_filters
from django.db.models import Q

from apps.jobs.models.jobs import JobPosting


class JobPostingFilter(django_filters.FilterSet):
    tech = django_filters.CharFilter(method="filter_tech")
    region = django_filters.CharFilter(method="filter_region")
    search = django_filters.CharFilter(method="filter_search")
    min_salary = django_filters.NumberFilter(field_name="salary_max", lookup_expr="gte")

    class Meta:
        model = JobPosting
        fields = ["ats_source", "seniority", "contract_type", "is_active"]

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

    def filter_search(self, queryset, _name: str, value: str):
        term = value.strip()
        if not term:
            return queryset
        return queryset.filter(
            Q(title__icontains=term)
            | Q(company_name__icontains=term)
            | Q(description_clean__icontains=term)
        )
