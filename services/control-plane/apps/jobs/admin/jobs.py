from django.contrib import admin

from apps.jobs.models.jobs import JobPosting
from apps.jobs.models.saved_filter import SavedFilter
from apps.jobs.models.triage import DismissedJob, MutedCompany


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
    list_filter = (
        "ats_source",
        "seniority",
        "contract_type",
        "is_active",
        "is_deleted",
    )
    search_fields = ("title", "company_name", "external_id")
    readonly_fields = ("uuid", "content_hash", "created_at", "modified_at")


@admin.register(SavedFilter)
class SavedFilterAdmin(admin.ModelAdmin):
    list_display = ("name", "user", "created_at", "modified_at", "is_deleted")
    list_filter = ("is_deleted",)
    search_fields = ("name", "user__username")
    readonly_fields = ("uuid", "created_at", "modified_at")


@admin.register(DismissedJob)
class DismissedJobAdmin(admin.ModelAdmin):
    list_display = ("job_posting", "user", "created_at", "is_deleted")
    list_filter = ("is_deleted",)
    search_fields = (
        "job_posting__title",
        "job_posting__company_name",
        "user__username",
    )
    readonly_fields = ("uuid", "created_at", "modified_at")


@admin.register(MutedCompany)
class MutedCompanyAdmin(admin.ModelAdmin):
    list_display = (
        "company_name_display",
        "company_name_normalized",
        "user",
        "created_at",
        "is_deleted",
    )
    list_filter = ("is_deleted",)
    search_fields = (
        "company_name_display",
        "company_name_normalized",
        "user__username",
    )
    readonly_fields = ("uuid", "created_at", "modified_at")
