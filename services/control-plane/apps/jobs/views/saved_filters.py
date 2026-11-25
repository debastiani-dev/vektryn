from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated

from apps.jobs.models.saved_filter import SavedFilter
from apps.jobs.serializers.saved_filters import SavedFilterSerializer


class SavedFilterViewSet(viewsets.ModelViewSet):
    serializer_class = SavedFilterSerializer
    permission_classes = [IsAuthenticated]
    lookup_field = "uuid"
    queryset = SavedFilter.objects.none()

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return SavedFilter.objects.none()
        return SavedFilter.objects.filter(user=self.request.user)

    def perform_create(self, serializer: SavedFilterSerializer) -> None:
        serializer.save(user=self.request.user)
