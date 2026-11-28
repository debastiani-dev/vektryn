from rest_framework import serializers

from apps.resumes.models.resumes import ResumeProfile
from apps.resumes.services.resume_service import (
    ActiveResumeLimitError,
    ResumeService,
)
from vektryn_contracts.language import normalize_language_code


def _as_list(value: object) -> list:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return list(value)
    return [value]


def _expand_multi_value_items(raw_items: list) -> list:
    expanded = []
    for item in raw_items:
        if item is None:
            continue
        if isinstance(item, str):
            expanded.extend(part.strip() for part in item.split(",") if part.strip())
            continue
        expanded.append(item)
    return expanded


class ResumeRescoreRequestSerializer(serializers.Serializer):
    max_jobs = serializers.IntegerField(min_value=1, max_value=100, default=50)
    force = serializers.BooleanField(default=False)


class ResumeProfileSerializer(serializers.ModelSerializer):
    file = serializers.FileField(write_only=True, required=False, allow_null=True)
    raw_text = serializers.CharField(required=False, allow_blank=True)
    language = serializers.CharField(
        required=False, allow_blank=True, allow_null=True, max_length=16
    )
    min_alert_score = serializers.IntegerField(min_value=0, max_value=100, default=70)
    has_embedding = serializers.SerializerMethodField()

    class Meta:
        model = ResumeProfile
        fields = [
            "uuid",
            "label",
            "target_seniority",
            "target_contract_types",
            "target_regions",
            "target_work_modes",
            "language",
            "strict_language_match",
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
        mutable = data.copy() if hasattr(data, "copy") else dict(data)
        if mutable.get("file") in (None, "", "string"):
            mutable.pop("file", None)

        for field_name in (
            "target_seniority",
            "target_contract_types",
            "target_regions",
            "target_work_modes",
        ):
            if field_name not in mutable:
                continue
            raw_items = (
                mutable.getlist(field_name)
                if hasattr(mutable, "getlist")
                else _as_list(mutable[field_name])
            )
            expanded = _expand_multi_value_items(raw_items)
            if hasattr(mutable, "setlist"):
                mutable.setlist(field_name, expanded)
            else:
                mutable[field_name] = expanded

        return super().to_internal_value(mutable)

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

    def validate_language(self, value: str | None) -> str:
        try:
            return normalize_language_code(value, strict=True)
        except ValueError as exc:
            raise serializers.ValidationError(str(exc)) from exc

    def create(self, validated_data: dict) -> ResumeProfile:
        uploaded_file = validated_data.pop("file", None)
        service = ResumeService(user=self.context["request"].user)
        try:
            return service.create_profile(
                validated_data=validated_data,
                uploaded_file=uploaded_file,
            )
        except ActiveResumeLimitError as exc:
            raise serializers.ValidationError({"is_active": str(exc)}) from exc
        except ValueError as exc:
            raise serializers.ValidationError({"file": str(exc)}) from exc

    def update(self, instance: ResumeProfile, validated_data: dict) -> ResumeProfile:
        uploaded_file = validated_data.pop("file", None)
        service = ResumeService(user=instance.user)
        try:
            return service.update_profile(
                instance=instance,
                validated_data=validated_data,
                uploaded_file=uploaded_file,
            )
        except ActiveResumeLimitError as exc:
            raise serializers.ValidationError({"is_active": str(exc)}) from exc
        except ValueError as exc:
            raise serializers.ValidationError({"file": str(exc)}) from exc
