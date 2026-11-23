from rest_framework import serializers

from apps.analytics.models import StackTrendDaily


class StackTrendDailySerializer(serializers.ModelSerializer):
    class Meta:
        model = StackTrendDaily
        fields = [
            "id",
            "bucket_date",
            "tag",
            "category",
            "mention_count",
            "unique_companies_count",
            "median_annual_usd",
        ]