from rest_framework import viewsets

from apps.tracker.models import ApplicationLead
from apps.tracker.serializers.leads import ApplicationLeadSerializer


class ApplicationLeadViewSet(viewsets.ModelViewSet):
    queryset = ApplicationLead.objects.none()
    serializer_class = ApplicationLeadSerializer
    lookup_field = "uuid"
    filterset_fields = ["status", "priority", "resume_profile"]
    ordering_fields = ["modified_at", "last_activity_at", "applied_at", "created_at"]
    ordering = ["-modified_at"]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return ApplicationLead.objects.none()
        return ApplicationLead.objects.filter(user=self.request.user).select_related(
            "job_posting", "resume_profile"
        )
