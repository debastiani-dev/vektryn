from rest_framework import parsers, viewsets

from apps.resumes.models.resumes import ResumeProfile
from apps.resumes.serializers.resumes import ResumeProfileSerializer


class ResumeProfileViewSet(viewsets.ModelViewSet):
    serializer_class = ResumeProfileSerializer
    parser_classes = [parsers.JSONParser, parsers.MultiPartParser, parsers.FormParser]
    lookup_field = "uuid"
    queryset = ResumeProfile.objects.none()

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return ResumeProfile.objects.none()
        return ResumeProfile.objects.filter(user=self.request.user)