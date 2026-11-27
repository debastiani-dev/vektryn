from django.db.models import Sum
import django_filters
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from apps.analytics.models import StackTrendDaily
from apps.analytics.serializers.trends import StackTrendDailySerializer

_DEFAULT_SERIES_TAG_LIMIT = 5
_MAX_SERIES_TAG_LIMIT = 10
_MAX_SERIES_DATES = 90


def _parse_series_limit(raw: str | None) -> int:
    if not raw:
        return _DEFAULT_SERIES_TAG_LIMIT
    try:
        parsed = int(raw)
    except ValueError:
        return _DEFAULT_SERIES_TAG_LIMIT
    return max(1, min(_MAX_SERIES_TAG_LIMIT, parsed))


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
    ordering_fields = [
        "bucket_date",
        "mention_count",
        "unique_companies_count",
        "median_annual_usd",
    ]
    ordering = ["-bucket_date", "-mention_count"]

    @action(detail=False, methods=["get"], url_path="series")
    def series(self, request: Request) -> Response:
        """Return complete multi-day series for the top N tags without table pagination."""
        limit = _parse_series_limit(request.query_params.get("limit"))
        filtered_qs = self.filter_queryset(self.get_queryset())

        recent_dates = list(
            filtered_qs.values_list("bucket_date", flat=True)
            .distinct()
            .order_by("-bucket_date")[:_MAX_SERIES_DATES]
        )
        if not recent_dates:
            return Response({"dates": [], "tags": [], "results": []})

        dates = sorted(recent_dates)
        window_qs = filtered_qs.filter(
            bucket_date__gte=dates[0], bucket_date__lte=dates[-1]
        )

        top_tags = [
            row["tag"]
            for row in window_qs.values("tag")
            .annotate(total_mentions=Sum("mention_count"))
            .order_by("-total_mentions", "tag")[:limit]
        ]
        series_rows = list(
            window_qs.filter(tag__in=top_tags).order_by("bucket_date", "tag")
        )
        serializer = self.get_serializer(series_rows, many=True)
        return Response(
            {
                "dates": [d.isoformat() for d in dates],
                "tags": top_tags,
                "results": serializer.data,
            }
        )
