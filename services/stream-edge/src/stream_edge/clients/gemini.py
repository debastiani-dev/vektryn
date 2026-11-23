import asyncio
from decimal import Decimal
from typing import Callable, TypeVar

from google import genai
from google.genai import errors as genai_errors
from google.genai import types
from pydantic import BaseModel, Field

from stream_edge.config import settings
from vektryn_contracts.enums import ContractType, RegionEligibility, SalaryPeriod, SeniorityLevel
from vektryn_contracts.events import EMBEDDING_DIMENSIONS

T = TypeVar("T")


class ExtractedJobMetadata(BaseModel):
    seniority: SeniorityLevel = SeniorityLevel.UNKNOWN
    contract_type: ContractType = ContractType.UNKNOWN
    region_eligibility: list[RegionEligibility] = Field(default_factory=list)
    salary_min: Decimal | None = None
    salary_max: Decimal | None = None
    salary_currency: str = ""
    salary_period: SalaryPeriod | None = None
    tech_stack: list[str] = Field(default_factory=list)


class ResumeGapEvaluation(BaseModel):
    fit_score: int = Field(ge=0, le=100)
    matched_skills: list[str] = Field(default_factory=list)
    missing_keywords: list[str] = Field(default_factory=list)
    talking_points: list[str] = Field(default_factory=list)
    gap_summary: str = ""


class GeminiStreamClient:
    PLACEHOLDER_KEYS = {"", "your_gemini_api_key_here"}
    RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}

    def __init__(self, api_key: str = settings.gemini_api_key) -> None:
        cleaned = (api_key or "").strip()
        if cleaned in self.PLACEHOLDER_KEYS:
            raise ValueError("A valid GEMINI_API_KEY is required for stream-edge workers.")
        self._client = genai.Client(api_key=cleaned)

    @classmethod
    def _call_with_retry(cls, fn: Callable[[], T], max_attempts: int = 4) -> T:
        import time

        last_exc: genai_errors.APIError | None = None
        for attempt in range(max_attempts):
            try:
                return fn()
            except genai_errors.APIError as exc:
                last_exc = exc
                if exc.code not in cls.RETRYABLE_STATUS_CODES or attempt == max_attempts - 1:
                    raise
                time.sleep(2.0 * (2**attempt))
        raise last_exc  # type: ignore[misc]

    def _generate_structured_sync(
        self,
        *,
        prompt: str,
        schema: type[BaseModel],
    ) -> str:
        config = types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=schema,
            temperature=0.0,
        )
        try:
            res = self._call_with_retry(
                lambda: self._client.models.generate_content(
                    model=settings.gemini_scoring_model,
                    contents=prompt,
                    config=config,
                )
            )
            return res.text
        except genai_errors.APIError as exc:
            if (
                exc.code in self.RETRYABLE_STATUS_CODES
                and settings.gemini_fallback_scoring_model
            ):
                res = self._call_with_retry(
                    lambda: self._client.models.generate_content(
                        model=settings.gemini_fallback_scoring_model,
                        contents=prompt,
                        config=config,
                    )
                )
                return res.text
            raise

    async def extract_job_metadata(
        self,
        *,
        title: str,
        company_name: str,
        location_raw: str,
        description_clean: str,
    ) -> ExtractedJobMetadata:
        prompt = (
            "Analyze this software engineering job posting and extract structured metadata.\n"
            "- Map seniority and legal/tax contract_type (clt, pj, b2b_contractor, w2, c2c, eor, unknown).\n"
            "- Identify all eligible regions in region_eligibility (e.g., brazil, latam, worldwide, north_america, europe, emea, apac, restricted).\n"
            "- Extract salary_min, salary_max, 3-letter ISO salary_currency, and salary_period only if explicitly stated.\n"
            "- Extract normalized lowercase tech_stack tags (languages, frameworks, databases, brokers, cloud, DevOps).\n\n"
            f"Title: {title}\n"
            f"Company: {company_name}\n"
            f"Location: {location_raw}\n\n"
            f"Description:\n{description_clean[:12000]}"
        )
        raw_json = await asyncio.to_thread(
            self._generate_structured_sync,
            prompt=prompt,
            schema=ExtractedJobMetadata,
        )
        return ExtractedJobMetadata.model_validate_json(raw_json)

    def _embed_sync(self, text: str) -> list[float]:
        res = self._call_with_retry(
            lambda: self._client.models.embed_content(
                model=settings.gemini_embedding_model,
                contents=text[:12000],
                config=types.EmbedContentConfig(
                    task_type="RETRIEVAL_DOCUMENT",
                    output_dimensionality=EMBEDDING_DIMENSIONS,
                ),
            )
        )
        return list(res.embeddings[0].values)

    async def embed_job_text(
        self,
        *,
        title: str,
        company_name: str,
        tech_stack: list[str],
        description_clean: str,
    ) -> list[float]:
        composite = (
            f"Role: {title} at {company_name}\n"
            f"Stack: {', '.join(tech_stack)}\n\n"
            f"{description_clean}"
        )
        return await asyncio.to_thread(self._embed_sync, composite)

    async def evaluate_resume_fit(
        self,
        *,
        resume_text: str,
        resume_skills: list[str],
        job_title: str,
        company_name: str,
        job_description: str,
        job_stack: list[str],
    ) -> tuple[ResumeGapEvaluation, str]:
        prompt = (
            "Evaluate how well this candidate resume matches the target software engineering role.\n"
            "Return:\n"
            "- fit_score: integer 0-100 calibrated strictly on core backend/architecture overlap, seniority, and domain fit.\n"
            "- matched_skills: normalized lowercase skills present in both the resume and job requirements.\n"
            "- missing_keywords: important skills/tools requested in the job that are missing or weak in the resume.\n"
            "- talking_points: 3 concise, concrete interview talking points framing the candidate's real experience for this role.\n"
            "- gap_summary: 2-3 sentence objective assessment of strengths and gaps.\n\n"
            f"CANDIDATE RESUME SKILLS: {', '.join(resume_skills)}\n"
            f"CANDIDATE RESUME:\n{resume_text[:10000]}\n\n"
            f"TARGET ROLE: {job_title} @ {company_name}\n"
            f"TARGET STACK: {', '.join(job_stack)}\n"
            f"JOB DESCRIPTION:\n{job_description[:10000]}"
        )
        raw_json = await asyncio.to_thread(
            self._generate_structured_sync,
            prompt=prompt,
            schema=ResumeGapEvaluation,
        )
        return ResumeGapEvaluation.model_validate_json(raw_json), settings.gemini_scoring_model