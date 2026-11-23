from rest_framework import viewsets

from apps.jobs.filters.jobs import JobPostingFilter
from apps.jobs.models.jobs import JobPosting
from apps.jobs.serializers.jobs import (
    JobPostingDetailSerializer,
    JobPostingSummarySerializer,
)


class JobPostingViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = JobPosting.objects.all()
    filterset_class = JobPostingFilter
    ordering_fields = ["created_at", "posted_at", "salary_max"]
    ordering = ["-created_at"]
    lookup_field = "uuid"

    def get_serializer_class(self):
        if self.action == "retrieve":
            return JobPostingDetailSerializer
        return JobPostingSummarySerializer