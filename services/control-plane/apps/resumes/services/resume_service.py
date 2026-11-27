import hashlib
from io import BytesIO
import logging
from pathlib import Path
import time
from typing import BinaryIO

from django.conf import settings
from django.contrib.auth.models import AbstractBaseUser
from django.db import transaction
from docx import Document
from google import genai
from pydantic import BaseModel as PydanticBaseModel
from pypdf import PdfReader

from apps.base.services.base_service import BaseService
from apps.base.services.byok import (
    BYOKError,
    BYOKMissingError,
    execute_user_gemini_embed,
    execute_user_gemini_generate,
    user_has_gemini_api_key,
)
from apps.resumes.models.resumes import ResumeProfile
from apps.resumes.services.rescore_publisher import (
    RescoreBrokerError,
    acquire_rescore_cooldown,
    current_trace_id,
    publish_rescore_event,
    release_rescore_cooldown,
)
from vektryn_contracts import JobRescoreEvent

try:
    from google.cloud import storage as gcs_storage
except ImportError:
    gcs_storage = None

logger = logging.getLogger(__name__)


class GeminiServiceError(Exception):
    """Raised when the upstream Gemini API fails after retries or BYOK checks fail."""

    def __init__(self, message: str, *, code: str = "gemini_error") -> None:
        self.code = code
        super().__init__(message)


class _ExtractedSkillsResponse(PydanticBaseModel):
    skills: list[str]


class ResumeService(BaseService):
    SUPPORTED_EXTENSIONS = (".pdf", ".docx", ".txt", ".md")
    PENDING_EMBED_MAX_RESUMES = 3
    PENDING_EMBED_BUDGET_SECONDS = 10.0
    PENDING_EMBED_CALL_TIMEOUT_MS = 5000

    def __init__(
        self,
        user: AbstractBaseUser | None = None,
        genai_client: genai.Client | None = None,
    ) -> None:
        super().__init__(user=user)
        self._genai_client = genai_client

    @staticmethod
    def compute_text_hash(raw_text: str) -> str:
        normalized = " ".join(raw_text.split()).strip()
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    @classmethod
    def extract_text_from_bytes(cls, filename: str, raw_bytes: bytes) -> str:
        lower_name = filename.lower()

        if lower_name.endswith(".pdf"):
            reader = PdfReader(BytesIO(raw_bytes))
            text = "\n".join(page.extract_text() or "" for page in reader.pages).strip()
        elif lower_name.endswith(".docx"):
            doc = Document(BytesIO(raw_bytes))
            text = "\n".join(p.text for p in doc.paragraphs if p.text.strip()).strip()
        elif lower_name.endswith((".txt", ".md")):
            text = raw_bytes.decode("utf-8", errors="replace").strip()
        else:
            raise ValueError(
                "Unsupported file format. Upload a .pdf, .docx, .txt, or .md file."
            )

        if not text:
            raise ValueError(
                "Could not extract any readable text from the uploaded file."
            )
        return text

    @classmethod
    def extract_text_from_upload(cls, filename: str, file_obj: BinaryIO) -> str:
        return cls.extract_text_from_bytes(filename, file_obj.read())

    @staticmethod
    def save_uploaded_resume(
        *,
        user_id: str,
        filename: str,
        content_hash: str,
        raw_bytes: bytes,
    ) -> str:
        safe_name = Path(filename).name.replace("/", "_").replace(" ", "_") or "resume"
        object_path = f"resumes/{user_id}/{content_hash[:16]}_{safe_name}"

        bucket_name = (getattr(settings, "GCS_RESUMES_BUCKET", "") or "").strip()
        storage_backend = (
            (getattr(settings, "STORAGE_BACKEND", "") or "").strip().lower()
        )
        if bucket_name and storage_backend != "local" and gcs_storage is not None:
            client = gcs_storage.Client()
            blob = client.bucket(bucket_name).blob(object_path)
            blob.upload_from_string(raw_bytes, content_type="application/octet-stream")
            return f"gs://{bucket_name}/{object_path}"

        local_dir = Path(getattr(settings, "LOCAL_STORAGE_DIR", Path(".local_storage")))
        target_path = local_dir / object_path
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_bytes(raw_bytes)
        return target_path.resolve().as_uri()

    def generate_embedding_and_skills(
        self,
        raw_text: str,
        *,
        deadline: float | None = None,
        embed_timeout_ms: int = 8000,
        embed_max_attempts: int = 2,
        skill_deadline_seconds: float = 15.0,
        allow_skills_fallback_empty: bool = False,
    ) -> tuple[list[float] | None, list[str]]:
        if self._genai_client is None and not user_has_gemini_api_key(self.user):
            return None, []

        try:
            embedding = execute_user_gemini_embed(
                user=self.user,
                contents=raw_text,
                task_type="RETRIEVAL_DOCUMENT",
                timeout_ms=embed_timeout_ms,
                max_attempts=embed_max_attempts,
                genai_client=self._genai_client,
                deadline=deadline,
            )
        except BYOKMissingError:
            return None, []
        except BYOKError as exc:
            raise GeminiServiceError(str(exc), code=exc.code) from exc

        prompt = (
            "Extract a deduplicated list of normalized lowercase technical skills "
            "(programming languages, frameworks, databases, message brokers, cloud "
            "providers, DevOps tools) explicitly evidenced in this resume:\n\n"
            f"{raw_text}"
        )
        effective_skill_deadline = skill_deadline_seconds
        if deadline is not None:
            remaining = deadline - time.monotonic()
            if remaining < 1.5:
                return embedding, []
            effective_skill_deadline = min(skill_deadline_seconds, remaining)

        try:
            skill_res, _used_model = execute_user_gemini_generate(
                user=self.user,
                task="resume_skills",
                contents=prompt,
                response_mime_type="application/json",
                response_schema=_ExtractedSkillsResponse,
                deadline_seconds=effective_skill_deadline,
                per_attempt_timeout_ms=embed_timeout_ms,
                max_transient_retries=0 if deadline is not None else 1,
                genai_client=self._genai_client,
            )
        except BYOKError as exc:
            if allow_skills_fallback_empty:
                logger.warning(
                    "Resume skill extraction skipped after embedding succeeded: %s", exc
                )
                return embedding, []
            raise GeminiServiceError(str(exc), code=exc.code) from exc

        parsed = _ExtractedSkillsResponse.model_validate_json(skill_res.text)
        skills = sorted({s.strip().lower() for s in parsed.skills if s.strip()})
        return embedding, skills

    def embed_pending_resumes(
        self,
        *,
        max_resumes: int = PENDING_EMBED_MAX_RESUMES,
        budget_seconds: float = PENDING_EMBED_BUDGET_SECONDS,
    ) -> dict[str, object]:
        """Embed up to `max_resumes` unembedded active resumes within a bounded request budget."""
        if self.user is None:
            return {
                "pending_resumes_embedded": 0,
                "pending_resumes_remaining": 0,
                "embedding_warning": None,
            }

        pending = list(
            ResumeProfile.objects.filter(
                user=self.user,
                is_active=True,
                embedding__isnull=True,
            ).order_by("-modified_at")
        )
        total_pending = len(pending)
        if total_pending == 0:
            return {
                "pending_resumes_embedded": 0,
                "pending_resumes_remaining": 0,
                "embedding_warning": None,
            }

        deadline = time.monotonic() + max(2.0, float(budget_seconds))
        embedded = 0
        warning: str | None = None

        for resume in pending[: max(1, int(max_resumes))]:
            if deadline - time.monotonic() < 1.0:
                warning = (
                    "Key saved, but pending resume embedding reached the request time budget. "
                    "Open Resumes to generate embeddings for the remaining profiles."
                )
                break
            try:
                embedding, extracted_skills = self.generate_embedding_and_skills(
                    resume.raw_text,
                    deadline=deadline,
                    embed_timeout_ms=self.PENDING_EMBED_CALL_TIMEOUT_MS,
                    embed_max_attempts=1,
                    skill_deadline_seconds=5.0,
                    allow_skills_fallback_empty=True,
                )
            except GeminiServiceError as exc:
                warning = str(exc)
                break

            if embedding is None:
                break

            resume.embedding = embedding
            resume.extracted_skills = extracted_skills
            resume.content_hash = self.compute_text_hash(resume.raw_text)
            resume.save(update_fields=["embedding", "extracted_skills", "content_hash"])
            embedded += 1

            event = JobRescoreEvent(
                trace_id=current_trace_id(),
                resume_profile_uuid=resume.uuid,
                user_id=resume.user_id,
                max_jobs=self.DEFAULT_RESCORE_MAX_JOBS,
                force=False,
            )
            try:
                publish_rescore_event(event, require_broker=False)
            except RescoreBrokerError as exc:
                logger.warning(
                    "Post-key-save rescore publish failed for profile=%s: %s",
                    resume.uuid,
                    exc,
                )

        remaining = max(0, total_pending - embedded)
        if remaining > 0 and not warning:
            warning = (
                f"Embedded {embedded} resume(s); {remaining} remaining. "
                "Open Resumes and click Generate embedding for the remaining profiles."
            )
        return {
            "pending_resumes_embedded": embedded,
            "pending_resumes_remaining": remaining,
            "embedding_warning": warning,
        }

    def _enrich_if_content_changed(
        self,
        *,
        validated_data: dict,
        uploaded_file: BinaryIO | None = None,
        instance: ResumeProfile | None = None,
    ) -> dict:
        data = dict(validated_data)
        raw_text = data.get("raw_text", "")
        uploaded_bytes: bytes | None = None
        uploaded_name = ""

        if uploaded_file is not None:
            uploaded_bytes = uploaded_file.read()
            uploaded_name = getattr(uploaded_file, "name", "resume.txt")
            raw_text = self.extract_text_from_bytes(uploaded_name, uploaded_bytes)
            data["raw_text"] = raw_text

        if not raw_text and instance is not None:
            raw_text = instance.raw_text

        new_hash = self.compute_text_hash(raw_text)
        if uploaded_bytes is not None:
            owner_id = str(
                getattr(self.user, "id", None)
                or (instance.user_id if instance is not None else "anonymous")
            )
            data["source_file_gcs_uri"] = self.save_uploaded_resume(
                user_id=owner_id,
                filename=uploaded_name,
                content_hash=new_hash,
                raw_bytes=uploaded_bytes,
            )
        content_changed = (
            instance is None
            or instance.content_hash != new_hash
            or instance.embedding is None
        )

        if content_changed:
            embedding, extracted_skills = self.generate_embedding_and_skills(raw_text)
            data["content_hash"] = new_hash
            data["embedding"] = embedding
            data["extracted_skills"] = extracted_skills

        return data

    DEFAULT_RESCORE_MAX_JOBS = 50

    @staticmethod
    def _targeting_signature(
        profile: ResumeProfile,
    ) -> tuple[list[str], list[str], list[str]]:
        return (
            list(profile.target_seniority or []),
            list(profile.target_contract_types or []),
            list(profile.target_regions or []),
        )

    def _schedule_auto_rescore(
        self,
        profile: ResumeProfile,
        *,
        force: bool = False,
    ) -> None:
        if not profile.is_active or profile.embedding is None:
            return
        event = JobRescoreEvent(
            trace_id=current_trace_id(),
            resume_profile_uuid=profile.uuid,
            user_id=profile.user_id,
            max_jobs=self.DEFAULT_RESCORE_MAX_JOBS,
            force=force,
        )

        def _publish() -> None:
            try:
                publish_rescore_event(event, require_broker=False)
            except RescoreBrokerError as exc:
                logger.warning(
                    "Auto-rescore publish failed for profile=%s: %s",
                    profile.uuid,
                    exc,
                )

        transaction.on_commit(_publish)

    def trigger_rescore(
        self,
        *,
        instance: ResumeProfile,
        max_jobs: int = DEFAULT_RESCORE_MAX_JOBS,
        force: bool = False,
    ) -> JobRescoreEvent:
        if not instance.is_active:
            raise ValueError(
                "Activate this resume profile before rescoring active jobs."
            )
        if not user_has_gemini_api_key(instance.user):
            raise ValueError(
                "Add your Google AI Studio Gemini API key in Account Settings before rescoring active jobs."
            )
        if instance.embedding is None:
            raise ValueError(
                "This resume profile has no embedding yet. Save or re-upload the resume first."
            )

        cooldown_acquired = acquire_rescore_cooldown(instance.uuid)
        event = JobRescoreEvent(
            trace_id=current_trace_id(),
            resume_profile_uuid=instance.uuid,
            user_id=instance.user_id,
            max_jobs=max_jobs,
            force=force,
        )
        try:
            publish_rescore_event(event, require_broker=True)
        except RescoreBrokerError:
            if cooldown_acquired:
                release_rescore_cooldown(instance.uuid)
            raise
        return event

    @transaction.atomic
    def create_profile(
        self,
        *,
        validated_data: dict,
        uploaded_file: BinaryIO | None = None,
    ) -> ResumeProfile:
        if self.user is None:
            raise ValueError(
                "An authenticated user is required to create a ResumeProfile."
            )
        enriched_data = self._enrich_if_content_changed(
            validated_data=validated_data,
            uploaded_file=uploaded_file,
        )
        profile = ResumeProfile.objects.create(user=self.user, **enriched_data)
        self._schedule_auto_rescore(profile, force=False)
        return profile

    @transaction.atomic
    def update_profile(
        self,
        *,
        instance: ResumeProfile,
        validated_data: dict,
        uploaded_file: BinaryIO | None = None,
    ) -> ResumeProfile:
        prev_hash = instance.content_hash
        prev_active = instance.is_active
        prev_filters = self._targeting_signature(instance)

        enriched_data = self._enrich_if_content_changed(
            validated_data=validated_data,
            uploaded_file=uploaded_file,
            instance=instance,
        )
        for attr, value in enriched_data.items():
            setattr(instance, attr, value)
        instance.save()

        hash_changed = instance.content_hash != prev_hash
        activated = not prev_active and instance.is_active
        filters_changed = self._targeting_signature(instance) != prev_filters

        if instance.is_active and instance.embedding is not None:
            if hash_changed or activated:
                self._schedule_auto_rescore(instance, force=False)
            elif filters_changed:
                self._schedule_auto_rescore(instance, force=True)

        return instance
