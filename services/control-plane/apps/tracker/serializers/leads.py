from rest_framework import serializers

from apps.jobs.serializers.jobs import resolve_primary_source
from apps.tracker.models import ApplicationLead
from apps.tracker.services.leads import create_lead, update_lead


class ApplicationLeadSerializer(serializers.ModelSerializer):
    job_title = serializers.CharField(source="job_posting.title", read_only=True)
    company_name = serializers.CharField(
        source="job_posting.company_name", read_only=True
    )
    apply_url = serializers.CharField(source="job_posting.apply_url", read_only=True)
    ats_source = serializers.CharField(source="job_posting.ats_source", read_only=True)
    primary_source = serializers.SerializerMethodField()
    work_mode = serializers.CharField(source="job_posting.work_mode", read_only=True)
    language = serializers.CharField(source="job_posting.language", read_only=True)
    repost_count = serializers.IntegerField(
        source="job_posting.repost_count", read_only=True
    )
    last_reposted_at = serializers.DateTimeField(
        source="job_posting.last_reposted_at", read_only=True
    )
    resume_profile_summary = serializers.SerializerMethodField()

    class Meta:
        model = ApplicationLead
        fields = [
            "uuid",
            "job_posting",
            "resume_profile",
            "resume_profile_summary",
            "job_title",
            "company_name",
            "apply_url",
            "ats_source",
            "primary_source",
            "work_mode",
            "language",
            "repost_count",
            "last_reposted_at",
            "status",
            "priority",
            "notes",
            "next_action_at",
            "applied_at",
            "last_activity_at",
            "created_at",
            "modified_at",
        ]
        read_only_fields = [
            "uuid",
            "applied_at",
            "last_activity_at",
            "created_at",
            "modified_at",
        ]

    def get_primary_source(self, obj: ApplicationLead) -> str:
        return resolve_primary_source(obj.job_posting)

    def get_resume_profile_summary(self, obj: ApplicationLead) -> dict[str, str] | None:
        profile = obj.resume_profile
        if profile is None or profile.is_deleted:
            return None
        return {
            "uuid": str(profile.uuid),
            "label": profile.label,
            "language": profile.language,
        }

    def validate_resume_profile(self, value):
        request = self.context.get("request")
        if (
            value is not None
            and request is not None
            and value.user_id != request.user.id
        ):
            raise serializers.ValidationError(
                "You can only link your own resume profiles."
            )
        return value

    def create(self, validated_data: dict) -> ApplicationLead:
        return create_lead(
            user=self.context["request"].user, validated_data=validated_data
        )

    def update(
        self, instance: ApplicationLead, validated_data: dict
    ) -> ApplicationLead:
        return update_lead(instance, validated_data=validated_data)
