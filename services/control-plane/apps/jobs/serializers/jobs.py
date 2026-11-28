from typing import Any

from rest_framework import serializers

from apps.jobs.models.jobs import JobPosting, JobPostingSource
from apps.jobs.services.fx_rates import (
    build_salary_normalized_payload,
    get_request_fx_snapshot,
    resolve_display_currency,
)
from vektryn_contracts import get_source_priority_rank


def get_prefetched_job_sources(job: JobPosting) -> list[JobPostingSource]:
    prefetched = getattr(job, "prefetched_sources", None)
    if prefetched is not None:
        return list(prefetched)
    return list(
        job.sources.filter(is_deleted=False).order_by("-is_primary", "first_seen_at")
    )


def resolve_primary_source(
    job: JobPosting,
    sources: list[JobPostingSource] | None = None,
) -> str:
    rows = get_prefetched_job_sources(job) if sources is None else sources
    for source in rows:
        if source.is_primary:
            return source.ats_source
    for source in rows:
        if source.is_active:
            return source.ats_source
    return job.ats_source


class JobPostingSourceSerializer(serializers.ModelSerializer):
    class Meta:
        model = JobPostingSource
        fields = [
            "uuid",
            "ats_source",
            "apply_url",
            "is_primary",
            "is_active",
            "first_seen_at",
            "last_seen_at",
        ]


class JobPostingSummarySerializer(serializers.ModelSerializer):
    sources_count = serializers.SerializerMethodField()
    primary_source = serializers.SerializerMethodField()
    observed_sources = serializers.SerializerMethodField()
    salary_normalized = serializers.SerializerMethodField()

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
            "work_mode",
            "language",
            "region_eligibility",
            "salary_min",
            "salary_max",
            "salary_currency",
            "salary_period",
            "salary_annual_min_usd",
            "salary_annual_max_usd",
            "salary_annual_mid_usd",
            "salary_normalized",
            "tech_stack",
            "is_active",
            "posted_at",
            "created_at",
            "repost_count",
            "last_reposted_at",
            "sources_count",
            "primary_source",
            "observed_sources",
        ]
        read_only_fields = [
            "salary_annual_min_usd",
            "salary_annual_max_usd",
            "salary_annual_mid_usd",
        ]

    def get_salary_normalized(self, obj: JobPosting) -> dict[str, Any] | None:
        fx_snapshot = self.context.get("fx_snapshot")
        display_currency = self.context.get("display_currency")
        if fx_snapshot is None or not display_currency:
            request = self.context.get("request")
            fx_snapshot = get_request_fx_snapshot(request)
            display_currency = resolve_display_currency(request, fx_snapshot)
            self.context["fx_snapshot"] = fx_snapshot
            self.context["display_currency"] = display_currency
        return build_salary_normalized_payload(
            obj,
            display_currency=display_currency,
            fx_snapshot=fx_snapshot,
        )

    def get_sources_count(self, obj: JobPosting) -> int:
        rows = get_prefetched_job_sources(obj)
        if not rows:
            return 1 if obj.is_active else 0
        return sum(1 for row in rows if row.is_active)

    def get_primary_source(self, obj: JobPosting) -> str:
        return resolve_primary_source(obj)

    def get_observed_sources(self, obj: JobPosting) -> list[str]:
        rows = get_prefetched_job_sources(obj)
        active_rows = [row for row in rows if row.is_active]
        if not active_rows:
            return [obj.ats_source] if not rows and obj.is_active else []
        ordered = sorted(
            active_rows,
            key=lambda row: (
                0 if row.is_primary else 1,
                get_source_priority_rank(row.ats_source),
                row.first_seen_at,
            ),
        )
        seen: set[str] = set()
        result: list[str] = []
        for row in ordered:
            if row.ats_source not in seen:
                seen.add(row.ats_source)
                result.append(row.ats_source)
        return result


class JobPostingDetailSerializer(JobPostingSummarySerializer):
    sources = serializers.SerializerMethodField()

    class Meta(JobPostingSummarySerializer.Meta):
        fields = [
            *JobPostingSummarySerializer.Meta.fields,
            "raw_html_gcs_uri",
            "description_clean",
            "closed_at",
            "modified_at",
            "sources",
        ]

    def get_sources(self, obj: JobPosting) -> list[dict]:
        rows = get_prefetched_job_sources(obj)
        return JobPostingSourceSerializer(rows, many=True).data


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
