import django_filters
from rest_framework import viewsets

from apps.analytics.models import StackTrendDaily
from apps.analytics.serializers.trends import StackTrendDailySerializer


class StackTrendFilter(django_filters.FilterSet):
    date_from = django_filters.DateFilter(field_name="bucket_date", lookup_expr="gte")
    date_to = django_filters.DateFilter(field_name="bucket_date", lookup_expr="lte")
    tag = django_filters.CharFilter(field_name="tag", lookup_expr="iexact")

    class Meta:
        model = StackTrendDaily
        fields = ["category", "tag", "date_from", "date_to"]


class StackTrendDailyViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = StackTrendDaily.objects.all()
    serializer_class = StackTrendDailySerializer
    filterset_class = StackTrendFilter
    ordering_fields = ["bucket_date", "mention_count", "unique_companies_count", "median_annual_usd"]
    ordering = ["-bucket_date", "-mention_count"]