from django.contrib import admin

from apps.jobs.models.jobs import JobPosting


@admin.register(JobPosting)
class JobPostingAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "company_name",
        "ats_source",
        "seniority",
        "contract_type",
        "is_active",
        "created_at",
    )
    list_filter = ("ats_source", "seniority", "contract_type", "is_active", "is_deleted")
    search_fields = ("title", "company_name", "external_id")
    readonly_fields = ("uuid", "content_hash", "created_at", "modified_at")