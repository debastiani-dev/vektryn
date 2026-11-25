from django.db import IntegrityError, transaction
from rest_framework import mixins, status, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from apps.jobs.models.triage import DismissedJob, MutedCompany
from apps.jobs.serializers.triage import (
    DismissedJobSerializer,
    MutedCompanySerializer,
)


class DismissedJobViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = DismissedJobSerializer
    permission_classes = [IsAuthenticated]
    lookup_field = "uuid"
    queryset = DismissedJob.objects.none()

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return DismissedJob.objects.none()
        return DismissedJob.objects.select_related("job_posting").filter(
            user=self.request.user
        )

    def create(self, request: Request, *args, **kwargs) -> Response:
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        job_posting = serializer.validated_data["job_posting"]

        existing = self.get_queryset().filter(job_posting=job_posting).first()
        if existing is not None:
            return Response(
                self.get_serializer(existing).data, status=status.HTTP_200_OK
            )

        try:
            with transaction.atomic():
                instance = serializer.save(user=request.user)
            return Response(
                self.get_serializer(instance).data, status=status.HTTP_201_CREATED
            )
        except IntegrityError:
            existing = self.get_queryset().get(job_posting=job_posting)
            return Response(
                self.get_serializer(existing).data, status=status.HTTP_200_OK
            )


class MutedCompanyViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = MutedCompanySerializer
    permission_classes = [IsAuthenticated]
    lookup_field = "uuid"
    queryset = MutedCompany.objects.none()

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return MutedCompany.objects.none()
        return MutedCompany.objects.filter(user=self.request.user)

    def create(self, request: Request, *args, **kwargs) -> Response:
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        normalized = serializer.validated_data["company_name_normalized"]

        existing = (
            self.get_queryset().filter(company_name_normalized=normalized).first()
        )
        if existing is not None:
            return Response(
                self.get_serializer(existing).data, status=status.HTTP_200_OK
            )

        try:
            with transaction.atomic():
                instance = serializer.save(user=request.user)
            return Response(
                self.get_serializer(instance).data, status=status.HTTP_201_CREATED
            )
        except IntegrityError:
            existing = self.get_queryset().get(company_name_normalized=normalized)
            return Response(
                self.get_serializer(existing).data, status=status.HTTP_200_OK
            )
