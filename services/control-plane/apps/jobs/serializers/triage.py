from rest_framework import serializers

from apps.jobs.models.jobs import JobPosting
from apps.jobs.models.triage import (
    DismissedJob,
    MutedCompany,
    normalize_company_name,
)


class DismissedJobSerializer(serializers.ModelSerializer):
    job_posting = serializers.PrimaryKeyRelatedField(queryset=JobPosting.objects.all())
    job_title = serializers.CharField(source="job_posting.title", read_only=True)
    company_name = serializers.CharField(
        source="job_posting.company_name", read_only=True
    )
    ats_source = serializers.CharField(source="job_posting.ats_source", read_only=True)

    class Meta:
        model = DismissedJob
        fields = (
            "uuid",
            "job_posting",
            "job_title",
            "company_name",
            "ats_source",
            "created_at",
        )
        read_only_fields = (
            "uuid",
            "job_title",
            "company_name",
            "ats_source",
            "created_at",
        )


class MutedCompanySerializer(serializers.ModelSerializer):
    company_name = serializers.CharField(
        write_only=True,
        required=False,
        allow_blank=True,
        max_length=180,
    )
    company_name_display = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=180,
    )

    class Meta:
        model = MutedCompany
        fields = (
            "uuid",
            "company_name",
            "company_name_display",
            "company_name_normalized",
            "created_at",
        )
        read_only_fields = (
            "uuid",
            "company_name_normalized",
            "created_at",
        )

    def validate(self, attrs: dict) -> dict:
        raw_name = attrs.pop("company_name", None)
        if raw_name is None or not str(raw_name).strip():
            raw_name = attrs.get("company_name_display", "")
        display = " ".join(str(raw_name or "").strip().split())
        if not display:
            raise serializers.ValidationError(
                {"company_name": "Company name cannot be blank."}
            )
        normalized = normalize_company_name(display)
        attrs["company_name_display"] = display
        attrs["company_name_normalized"] = normalized
        return attrs
