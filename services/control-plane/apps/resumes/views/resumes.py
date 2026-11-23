from rest_framework import parsers, viewsets

from apps.resumes.models.resumes import ResumeProfile
from apps.resumes.serializers.resumes import ResumeProfileSerializer


class ResumeProfileViewSet(viewsets.ModelViewSet):
    serializer_class = ResumeProfileSerializer
    parser_classes = [parsers.JSONParser, parsers.MultiPartParser, parsers.FormParser]
    lookup_field = "uuid"

    def get_queryset(self):
        return ResumeProfile.objects.filter(user=self.request.user)