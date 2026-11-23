import hashlib
import time
from io import BytesIO
from typing import BinaryIO, Callable, TypeVar

from django.conf import settings
from django.contrib.auth.models import AbstractBaseUser
from django.db import transaction
from docx import Document
from google import genai
from google.genai import errors as genai_errors
from google.genai import types
from pydantic import BaseModel as PydanticBaseModel
from pypdf import PdfReader

from apps.base.services.base_service import BaseService
from apps.resumes.models.resumes import ResumeProfile
from vektryn_contracts.events import EMBEDDING_DIMENSIONS


T = TypeVar("T")


class GeminiServiceError(Exception):
    """Raised when the upstream Gemini API fails after retries."""
    
    
class _ExtractedSkillsResponse(PydanticBaseModel):
    skills: list[str]


class ResumeService(BaseService):
    SUPPORTED_EXTENSIONS = (".pdf", ".docx", ".txt", ".md")
    PLACEHOLDER_KEYS = {"", "your_gemini_api_key_here"}
    RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}

    def __init__(
        self,
        user: AbstractBaseUser | None = None,
        genai_client: genai.Client | None = None,
    ) -> None:
        super().__init__(user=user)
        self._genai_client = genai_client

    @property
    def genai_client(self) -> genai.Client | None:
        if self._genai_client is not None:
            return self._genai_client
        api_key = (settings.GEMINI_API_KEY or "").strip()
        if api_key in self.PLACEHOLDER_KEYS:
            return None
        self._genai_client = genai.Client(api_key=api_key)
        return self._genai_client
    
    @classmethod
    def _call_with_retry(cls, fn: Callable[[], T], max_attempts: int = 3) -> T:
        last_exc: genai_errors.APIError | None = None
        for attempt in range(max_attempts):
            try:
                return fn()
            except genai_errors.APIError as exc:
                last_exc = exc
                if exc.code not in cls.RETRYABLE_STATUS_CODES or attempt == max_attempts - 1:
                    raise
                time.sleep(1.5 * (2**attempt))
        raise last_exc  # type: ignore[misc]

    @staticmethod
    def compute_text_hash(raw_text: str) -> str:
        normalized = " ".join(raw_text.split()).strip()
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    @classmethod
    def extract_text_from_upload(cls, filename: str, file_obj: BinaryIO) -> str:
        lower_name = filename.lower()
        raw_bytes = file_obj.read()

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
            raise ValueError("Could not extract any readable text from the uploaded file.")
        return text

    def generate_embedding_and_skills(
        self,
        raw_text: str,
    ) -> tuple[list[float] | None, list[str]]:
        client = self.genai_client
        if client is None:
            return None, []

        try:
            embed_res = self._call_with_retry(
                lambda: client.models.embed_content(
                    model=settings.GEMINI_EMBEDDING_MODEL,
                    contents=raw_text,
                    config=types.EmbedContentConfig(
                        task_type="RETRIEVAL_DOCUMENT",
                        output_dimensionality=EMBEDDING_DIMENSIONS,
                    ),
                )
            )
            embedding = list(embed_res.embeddings[0].values)

            prompt = (
                "Extract a deduplicated list of normalized lowercase technical skills "
                "(programming languages, frameworks, databases, message brokers, cloud "
                "providers, DevOps tools) explicitly evidenced in this resume:\n\n"
                f"{raw_text}"
            )
            gen_config = types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=_ExtractedSkillsResponse,
                temperature=0.0,
            )

            try:
                skill_res = self._call_with_retry(
                    lambda: client.models.generate_content(
                        model=settings.GEMINI_SCORING_MODEL,
                        contents=prompt,
                        config=gen_config,
                    )
                )
            except genai_errors.APIError as exc:
                if (
                    exc.code in self.RETRYABLE_STATUS_CODES
                    and settings.GEMINI_FALLBACK_SCORING_MODEL
                ):
                    skill_res = self._call_with_retry(
                        lambda: client.models.generate_content(
                            model=settings.GEMINI_FALLBACK_SCORING_MODEL,
                            contents=prompt,
                            config=gen_config,
                        )
                    )
                else:
                    raise
        except genai_errors.APIError as exc:
            raise GeminiServiceError(
                f"Gemini API error ({exc.code}): {exc.message}"
            ) from exc

        parsed = _ExtractedSkillsResponse.model_validate_json(skill_res.text)
        skills = sorted({s.strip().lower() for s in parsed.skills if s.strip()})
        return embedding, skills

    def _enrich_if_content_changed(
        self,
        *,
        validated_data: dict,
        uploaded_file: BinaryIO | None = None,
        instance: ResumeProfile | None = None,
    ) -> dict:
        data = dict(validated_data)
        raw_text = data.get("raw_text", "")

        if uploaded_file is not None:
            raw_text = self.extract_text_from_upload(uploaded_file.name, uploaded_file)
            data["raw_text"] = raw_text

        if not raw_text and instance is not None:
            raw_text = instance.raw_text

        new_hash = self.compute_text_hash(raw_text)
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

    @transaction.atomic
    def create_profile(
        self,
        *,
        validated_data: dict,
        uploaded_file: BinaryIO | None = None,
    ) -> ResumeProfile:
        if self.user is None:
            raise ValueError("An authenticated user is required to create a ResumeProfile.")
        enriched_data = self._enrich_if_content_changed(
            validated_data=validated_data,
            uploaded_file=uploaded_file,
        )
        return ResumeProfile.objects.create(user=self.user, **enriched_data)

    @transaction.atomic
    def update_profile(
        self,
        *,
        instance: ResumeProfile,
        validated_data: dict,
        uploaded_file: BinaryIO | None = None,
    ) -> ResumeProfile:
        enriched_data = self._enrich_if_content_changed(
            validated_data=validated_data,
            uploaded_file=uploaded_file,
            instance=instance,
        )
        for attr, value in enriched_data.items():
            setattr(instance, attr, value)
        instance.save()
        return instance