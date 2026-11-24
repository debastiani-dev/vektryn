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
