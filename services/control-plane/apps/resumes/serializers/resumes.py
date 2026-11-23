from rest_framework import serializers

from apps.resumes.models.resumes import ResumeProfile
from apps.resumes.services.resume_service import GeminiServiceError, ResumeService


class ResumeProfileSerializer(serializers.ModelSerializer):
    file = serializers.FileField(write_only=True, required=False, allow_null=True)
    raw_text = serializers.CharField(required=False, allow_blank=True)
    min_alert_score = serializers.IntegerField(min_value=0, max_value=100, default=75)
    has_embedding = serializers.SerializerMethodField()

    class Meta:
        model = ResumeProfile
        fields = [
            "uuid",
            "label",
            "target_seniority",
            "target_contract_types",
            "target_regions",
            "min_alert_score",
            "raw_text",
            "file",
            "source_file_gcs_uri",
            "content_hash",
            "extracted_skills",
            "has_embedding",
            "is_active",
            "created_at",
            "modified_at",
        ]
        read_only_fields = [
            "uuid",
            "source_file_gcs_uri",
            "content_hash",
            "extracted_skills",
            "has_embedding",
            "created_at",
            "modified_at",
        ]

    def to_internal_value(self, data):
        if hasattr(data, "copy"):
            data = data.copy()
        if data.get("file") in (None, "", "string"):
            data.pop("file", None)
        return super().to_internal_value(data)

    def get_has_embedding(self, obj: ResumeProfile) -> bool:
        return obj.embedding is not None

    def validate(self, attrs: dict) -> dict:
        uploaded_file = attrs.get("file")
        raw_text = attrs.get("raw_text", "")
        if self.instance is None and not uploaded_file and not raw_text.strip():
            raise serializers.ValidationError(
                "Provide either 'raw_text' or an uploaded 'file' (.pdf, .docx, .txt)."
            )
        return attrs
    
    def validate_label(self, value: str) -> str:
        user = self.context["request"].user
        qs = ResumeProfile.objects.filter(user=user, label=value)
        if self.instance is not None:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError(
                f"You already have an active resume profile labeled '{value}'."
            )
        return value

    def create(self, validated_data: dict) -> ResumeProfile:
        uploaded_file = validated_data.pop("file", None)
        service = ResumeService(user=self.context["request"].user)
        try:
            return service.create_profile(
                validated_data=validated_data,
                uploaded_file=uploaded_file,
            )
        except ValueError as exc:
            raise serializers.ValidationError({"file": str(exc)}) from exc
        except GeminiServiceError as exc:
            raise serializers.ValidationError(str(exc)) from exc

    def update(self, instance: ResumeProfile, validated_data: dict) -> ResumeProfile:
        uploaded_file = validated_data.pop("file", None)
        service = ResumeService(user=instance.user)
        try:
            return service.update_profile(
                instance=instance,
                validated_data=validated_data,
                uploaded_file=uploaded_file,
            )
        except ValueError as exc:
            raise serializers.ValidationError({"file": str(exc)}) from exc
        except GeminiServiceError as exc:
            raise serializers.ValidationError(str(exc)) from exc