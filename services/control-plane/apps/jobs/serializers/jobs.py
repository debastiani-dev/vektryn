from rest_framework import serializers

from apps.jobs.models.jobs import JobPosting


class JobPostingSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = JobPosting
        fields = [
            "uuid",
            "ats_source",
            "external_id",
            "title",
            "company_name",
            "apply_url",
            "location_raw",
            "seniority",
            "contract_type",
            "region_eligibility",
            "salary_min",
            "salary_max",
            "salary_currency",
            "salary_period",
            "tech_stack",
            "is_active",
            "posted_at",
            "created_at",
        ]


class JobPostingDetailSerializer(JobPostingSummarySerializer):
    class Meta(JobPostingSummarySerializer.Meta):
        fields = [
            *JobPostingSummarySerializer.Meta.fields,
            "raw_html_gcs_uri",
            "description_clean",
            "closed_at",
            "modified_at",
        ]


class ManualJobImportSerializer(serializers.Serializer):
    url = serializers.CharField(
        required=False, allow_blank=True, max_length=512, default=""
    )
    title = serializers.CharField(
        required=False, allow_blank=True, max_length=255, default=""
    )
    company_name = serializers.CharField(
        required=False, allow_blank=True, max_length=180, default=""
    )
    apply_url = serializers.CharField(
        required=False, allow_blank=True, max_length=512, default=""
    )
    location_raw = serializers.CharField(
        required=False, allow_blank=True, max_length=255, default=""
    )
    description = serializers.CharField(required=False, allow_blank=True, default="")

    def validate(self, attrs: dict) -> dict:
        url = (attrs.get("url") or "").strip()
        if url:
            attrs["url"] = url
            return attrs

        errors: dict[str, str] = {}
        title = (attrs.get("title") or "").strip()
        company_name = (attrs.get("company_name") or "").strip()
        apply_url = (attrs.get("apply_url") or "").strip()
        description = (attrs.get("description") or "").strip()

        if not title:
            errors["title"] = "Role title is required when not importing from a URL."
        if not company_name:
            errors["company_name"] = (
                "Company name is required when not importing from a URL."
            )
        if not apply_url:
            errors["apply_url"] = (
                "Application URL or email address is required when not importing from a URL."
            )
        if len(description) < 40:
            errors["description"] = "Job description must be at least 40 characters."

        if errors:
            raise serializers.ValidationError(errors)

        attrs["title"] = title
        attrs["company_name"] = company_name
        attrs["apply_url"] = apply_url
        attrs["description"] = description
        return attrs
