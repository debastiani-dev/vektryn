from django import forms
from django.contrib import admin

from apps.resumes.models import ResumeProfile
from vektryn_contracts import (
    ContractType,
    RegionEligibility,
    SeniorityLevel,
    WorkMode,
)


def _enum_choices(enum_cls) -> list[tuple[str, str]]:
    return [
        (member.value, member.value.replace("_", " ").title()) for member in enum_cls
    ]


class ResumeProfileAdminForm(forms.ModelForm):
    target_seniority = forms.MultipleChoiceField(
        choices=_enum_choices(SeniorityLevel),
        widget=forms.CheckboxSelectMultiple,
        required=False,
    )
    target_contract_types = forms.MultipleChoiceField(
        choices=_enum_choices(ContractType),
        widget=forms.CheckboxSelectMultiple,
        required=False,
    )
    target_regions = forms.MultipleChoiceField(
        choices=_enum_choices(RegionEligibility),
        widget=forms.CheckboxSelectMultiple,
        required=False,
    )
    target_work_modes = forms.MultipleChoiceField(
        choices=_enum_choices(WorkMode),
        widget=forms.CheckboxSelectMultiple,
        required=False,
    )

    class Meta:
        model = ResumeProfile
        fields = "__all__"


@admin.register(ResumeProfile)
class ResumeProfileAdmin(admin.ModelAdmin):
    form = ResumeProfileAdminForm
    list_display = (
        "label",
        "user",
        "target_seniority",
        "target_contract_types",
        "target_regions",
        "target_work_modes",
        "min_alert_score",
        "is_active",
        "created_at",
    )
    list_filter = ("is_active", "is_deleted")
    search_fields = ("label", "user__username", "user__email")
    readonly_fields = ("uuid", "content_hash", "embedding", "created_at", "modified_at")
