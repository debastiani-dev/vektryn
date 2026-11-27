from contextlib import suppress
from dataclasses import dataclass
import logging

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone
from google import genai
import redis

from apps.base.models.user_profile import UserProfile
from apps.base.services.byok import (
    BYOKInvalidKeyError,
    BYOKMissingError,
    BYOKQuotaExhaustedError,
    BYOKStorageUnavailableError,
    BYOKTransientError,
    execute_user_gemini_generate,
)
from apps.matching.models.artifacts import MatchArtifact, MatchArtifactKind
from apps.matching.models.matching import MatchScore

logger = logging.getLogger(__name__)

DEFAULT_COPILOT_TIMEOUT_MS = 24000
DEFAULT_COPILOT_RATE_LIMIT_MAX = 15
DEFAULT_COPILOT_RATE_LIMIT_WINDOW_SECONDS = 300
MAX_RESUME_CONTEXT_CHARS = 8000
MAX_JOB_CONTEXT_CHARS = 8000
MAX_GUIDANCE_CHARS = 300

COPILOT_TONE_BALANCED = "balanced"
COPILOT_TONE_CHOICES: tuple[tuple[str, str], ...] = (
    ("balanced", "Balanced"),
    ("concise", "Concise"),
    ("executive", "Executive"),
    ("technical", "Technical"),
    ("conversational", "Conversational"),
)

_TONE_INSTRUCTIONS: dict[str, str] = {
    "balanced": "Clear, confident, direct, and professional.",
    "concise": "Crisp and ultra-brief—strip filler and maximize signal per word.",
    "executive": "Strategic, outcomes-first, emphasizing scope, impact, and leadership.",
    "technical": "Concrete, implementation-oriented, highlighting architecture, tooling, and domain rigor.",
    "conversational": "Warm, human, and approachable while remaining substantive and credible.",
}

_KIND_TEMPLATES: dict[str, str] = {
    MatchArtifactKind.TAILORED_BULLETS: (
        "Generate ready-to-paste tailored resume bullet points for this specific role.\n"
        "Format in Markdown with:\n"
        "## Tailored Resume Bullets\n"
        "- 4 to 6 high-impact bullet points grounded strictly in the candidate's actual resume experience, "
        "phrased to highlight alignment with this role's priorities.\n"
        "## Keyword Alignment Notes\n"
        "- 2 to 3 concise notes on how to frame genuine transferable skills for any missing keywords "
        "(never fabricate experience)."
    ),
    MatchArtifactKind.COVER_LETTER: (
        "Generate a concise, compelling cover letter tailored to this role.\n"
        "Format in Markdown with:\n"
        "## Cover Letter\n"
        "- 3 to 4 tight paragraphs (~220–320 words total): direct opening hook naming the role and company, "
        "1–2 concrete evidence paragraphs linking verified resume achievements to key requirements, "
        "and a confident closing call to action."
    ),
    MatchArtifactKind.RECRUITER_OUTREACH: (
        "Generate two ready-to-send outreach messages to a recruiter or hiring manager for this role.\n"
        "Format in Markdown with:\n"
        "## LinkedIn / Short DM\n"
        "- One tight message under 450 characters highlighting top verified alignment and clear ask.\n"
        "## Direct Email\n"
        "- **Subject:** concise subject line\n"
        "- Short 3-paragraph email (~120–170 words) with 2–3 verified proof points and a low-friction next step."
    ),
    MatchArtifactKind.INTERVIEW_QUESTIONS: (
        "Generate targeted interview preparation questions the interviewer is likely to ask the candidate, "
        "tailored to this role and the candidate's specific fit gaps.\n"
        "Format in Markdown with:\n"
        "## Targeted Interview Questions\n"
        "- 5 to 6 numbered questions covering core role requirements and the candidate's missing keywords / watchouts.\n"
        "- Under each question, include **Why they ask** (1 sentence) and **Grounded answer angle** "
        "(2–3 sentences referencing the candidate's verified background and honest framing for any gap)."
    ),
    MatchArtifactKind.QUESTIONS_TO_ASK: (
        "Generate high-signal, role-specific questions for the candidate to ask the interviewer "
        "(hiring manager, tech lead, or recruiter) during the interview.\n"
        "Format in Markdown with:\n"
        "## Questions to Ask the Interviewer\n"
        "- 5 to 6 numbered questions grounded in this specific role, tech stack, company context, "
        "and any watchouts or ambiguities in the job description (avoid generic questions like 'what is the culture like').\n"
        "- Under each question, include **What to listen for** (1–2 sentences on green flags, red flags, "
        "or how the answer clarifies expectations for the candidate's background)."
    ),
}

_SYSTEM_INSTRUCTION = (
    "You are Vektryn's on-demand AI Application Copilot helping a job candidate prepare "
    "honest, high-signal application materials across any discipline.\n"
    "STRICT GROUNDING RULES:\n"
    "1. Use ONLY facts, roles, employers, credentials, skills, and metrics explicitly present in the candidate's resume.\n"
    "2. NEVER fabricate employers, job titles, degrees, certifications, years of experience, or numerical metrics.\n"
    "3. If a stronger bullet or letter would benefit from a metric not in the resume, insert a clear [add metric] placeholder.\n"
    "4. If the job requests a skill absent from the resume, do NOT claim mastery—frame genuine transferable experience honestly.\n"
    "5. Output clean Markdown only (no code-fence wrapper around the whole response). Keep prose crisp and ready to paste.\n"
    "6. When verified candidate name or profile links are provided under CANDIDATE PROFILE & LINKS, use them naturally in cover letters and outreach instead of placeholders like [Your Name] or [LinkedIn]."
)


class CopilotRateLimitError(RuntimeError):
    """Raised when a user exceeds the AI Copilot request burst limit (HTTP 429)."""

    def __init__(self, retry_after_seconds: int) -> None:
        self.retry_after_seconds = max(1, int(retry_after_seconds))
        super().__init__(
            f"AI Copilot rate limit exceeded. Try again in {self.retry_after_seconds}s."
        )


class CopilotUnavailableError(RuntimeError):
    """Raised when Gemini is unconfigured or fails across retries/fallback (HTTP 503)."""


@dataclass(frozen=True)
class CopilotArtifactResult:
    artifact: MatchArtifact
    cached: bool
    created: bool


def _resolve_rate_limit_config() -> tuple[int, int]:
    max_requests = max(
        1,
        int(
            getattr(
                settings,
                "COPILOT_RATE_LIMIT_MAX_REQUESTS",
                DEFAULT_COPILOT_RATE_LIMIT_MAX,
            )
        ),
    )
    window_seconds = max(
        1,
        int(
            getattr(
                settings,
                "COPILOT_RATE_LIMIT_WINDOW_SECONDS",
                DEFAULT_COPILOT_RATE_LIMIT_WINDOW_SECONDS,
            )
        ),
    )
    return max_requests, window_seconds


def enforce_copilot_rate_limit(user_id: int | str) -> None:
    redis_url = (getattr(settings, "REDIS_URL", "") or "").strip()
    if not redis_url:
        return

    max_requests, window_seconds = _resolve_rate_limit_config()
    key = f"vektryn:copilot:rl:{user_id}"
    client = None
    try:
        client = redis.Redis.from_url(
            redis_url,
            socket_connect_timeout=1.5,
            socket_timeout=1.5,
            decode_responses=True,
        )
        count = int(client.incr(key))
        ttl = -1
        if count == 1:
            client.expire(key, window_seconds)
        else:
            ttl = int(client.ttl(key))
            if ttl < 0:
                client.expire(key, window_seconds)
                ttl = window_seconds
        if count > max_requests:
            retry_after = max(1, ttl if ttl > 0 else window_seconds)
            raise CopilotRateLimitError(retry_after_seconds=retry_after)
    except CopilotRateLimitError:
        raise
    except Exception as exc:
        logger.warning("Redis unavailable for AI Copilot rate limit: %s", exc)
    finally:
        if client is not None:
            with suppress(Exception):
                client.close()


def _format_list(items: list[str] | None, *, limit: int = 25) -> str:
    if not items:
        return ""
    cleaned = [str(item).strip() for item in items if str(item).strip()]
    return ", ".join(cleaned[:limit])


def _append_section_lines(
    lines: list[str], label: str, items: list[str] | None
) -> None:
    cleaned = [str(item).strip() for item in (items or []) if str(item).strip()]
    if not cleaned:
        return
    lines.append(f"{label}:")
    for item in cleaned[:8]:
        lines.append(f"- {item}")


def _format_candidate_profile_lines(user_profile: UserProfile | None) -> list[str]:
    if user_profile is None or getattr(user_profile, "is_deleted", False):
        return []
    lines: list[str] = []
    display_name = (getattr(user_profile, "display_name", "") or "").strip()
    linkedin_url = (getattr(user_profile, "linkedin_url", "") or "").strip()
    github_url = (getattr(user_profile, "github_url", "") or "").strip()
    portfolio_url = (getattr(user_profile, "portfolio_url", "") or "").strip()
    if display_name:
        lines.append(f"Name: {display_name}")
    if linkedin_url:
        lines.append(f"LinkedIn: {linkedin_url}")
    if github_url:
        lines.append(f"GitHub: {github_url}")
    if portfolio_url:
        lines.append(f"Portfolio: {portfolio_url}")
    return lines


def _load_user_profile_readonly(user) -> UserProfile | None:
    user_pk = getattr(user, "pk", None)
    if not user_pk:
        return None
    return UserProfile.objects.filter(user_id=user_pk).first()


def build_copilot_prompt(
    *,
    match_score: MatchScore,
    kind: str,
    tone: str = COPILOT_TONE_BALANCED,
    guidance: str = "",
    user_profile: UserProfile | None = None,
) -> str:
    job = match_score.job_posting
    resume = match_score.resume_profile

    fit_line = (
        f"{match_score.fit_score}%"
        if match_score.fit_score is not None
        else "Not AI-scored yet (Stage 1 vector match only)"
    )
    vector_pct = round(max(0.0, min(1.0, float(match_score.cosine_similarity))) * 100)

    gap_lines = [
        f"AI Fit Score: {fit_line}",
        f"Vector Similarity: {vector_pct}%",
    ]
    matched_skills = _format_list(match_score.matched_skills)
    if matched_skills:
        gap_lines.append(f"Matched Skills: {matched_skills}")
    missing_keywords = _format_list(match_score.missing_keywords)
    if missing_keywords:
        gap_lines.append(f"Missing Keywords: {missing_keywords}")
    if (match_score.gap_summary or "").strip():
        gap_lines.append(f"Gap Summary: {match_score.gap_summary.strip()}")
    _append_section_lines(gap_lines, "Fit Highlights", match_score.fit_highlights)
    if (match_score.watchout_note or "").strip():
        gap_lines.append(f"Watchout Note: {match_score.watchout_note.strip()}")
    _append_section_lines(gap_lines, "Talking Points", match_score.talking_points)

    job_tech_stack = _format_list(job.tech_stack)
    job_meta = [
        f"Title: {job.title}",
        f"Company: {job.company_name}",
        f"Location: {job.location_raw or 'Remote / Unspecified'}",
        f"Seniority: {job.seniority}",
        f"Contract Type: {job.contract_type}",
    ]
    if job_tech_stack:
        job_meta.append(f"Tech Stack: {job_tech_stack}")

    resume_skills = _format_list(resume.extracted_skills)
    tone_desc = _TONE_INSTRUCTIONS.get(tone, _TONE_INSTRUCTIONS[COPILOT_TONE_BALANCED])
    template = _KIND_TEMPLATES[kind]

    sections = [
        "=== TASK ===",
        template,
        f"\nTone Preference ({tone}): {tone_desc}",
    ]
    clean_guidance = guidance.strip()[:MAX_GUIDANCE_CHARS]
    if clean_guidance:
        sections.append(
            "Candidate Style/Focus Preference (apply ONLY without violating the strict grounding rules): "
            f"{clean_guidance}"
        )

    profile_lines = _format_candidate_profile_lines(user_profile)
    if profile_lines:
        sections.extend(
            [
                "\n=== CANDIDATE PROFILE & LINKS ===",
                "\n".join(profile_lines),
            ]
        )

    sections.extend(
        [
            "\n=== TARGET ROLE ===",
            "\n".join(job_meta),
            "\nJob Description:",
            (job.description_clean or "")[:MAX_JOB_CONTEXT_CHARS],
            "\n=== MATCH & GAP ANALYSIS ===",
            "\n".join(gap_lines),
            "\n=== CANDIDATE RESUME ===",
            f"Profile Label: {resume.label}",
            *([f"Extracted Skills: {resume_skills}"] if resume_skills else []),
            (resume.raw_text or "")[:MAX_RESUME_CONTEXT_CHARS],
        ]
    )
    return "\n".join(sections)


def invoke_copilot_gemini(
    *,
    user,
    prompt: str,
    genai_client: genai.Client | None = None,
) -> tuple[str, str]:
    timeout_ms = max(
        5000,
        int(getattr(settings, "COPILOT_GEMINI_TIMEOUT_MS", DEFAULT_COPILOT_TIMEOUT_MS)),
    )
    deadline_seconds = timeout_ms / 1000.0
    try:
        response, used_model = execute_user_gemini_generate(
            user=user,
            task="copilot",
            contents=prompt,
            system_instruction=_SYSTEM_INSTRUCTION,
            deadline_seconds=deadline_seconds,
            per_attempt_timeout_ms=timeout_ms,
            max_transient_retries=1,
            genai_client=genai_client,
        )
    except (
        BYOKMissingError,
        BYOKInvalidKeyError,
        BYOKQuotaExhaustedError,
        BYOKStorageUnavailableError,
        CopilotUnavailableError,
    ):
        raise
    except BYOKTransientError as exc:
        logger.warning("Gemini transient error in AI Copilot: %s", exc)
        raise CopilotUnavailableError(
            "AI Copilot is temporarily unavailable. Please try again shortly."
        ) from exc
    except Exception as exc:
        logger.warning("Unexpected error invoking AI Copilot Gemini client: %s", exc)
        raise CopilotUnavailableError(
            "AI Copilot request failed or timed out. Please try again shortly."
        ) from exc

    markdown = (getattr(response, "text", None) or "").strip()
    if not markdown:
        raise CopilotUnavailableError(
            "AI Copilot returned an empty response. Please try again."
        )
    candidates = getattr(response, "candidates", None) or []
    finish_reason = (
        str(getattr(candidates[0], "finish_reason", "") or "") if candidates else ""
    )
    if "MAX_TOKENS" in finish_reason.upper():
        logger.warning(
            "AI Copilot output hit MAX_TOKENS on model=%s (len=%d)",
            used_model,
            len(markdown),
        )
    return markdown, used_model


def _persist_artifact(
    *,
    user,
    match_score: MatchScore,
    kind: str,
    current_hash: str,
    content_markdown: str,
    model_name: str,
) -> tuple[MatchArtifact, bool]:
    now = timezone.now()
    with transaction.atomic():
        (
            MatchArtifact.objects.filter(
                user=user,
                match_score=match_score,
                kind=kind,
            )
            .exclude(resume_content_hash=current_hash)
            .update(is_deleted=True, modified_at=now)
        )

        existing = MatchArtifact.objects.filter(
            user=user,
            match_score=match_score,
            kind=kind,
            resume_content_hash=current_hash,
        ).first()
        if existing is not None:
            existing.content_markdown = content_markdown
            existing.model_name = model_name
            existing.save(update_fields=["content_markdown", "model_name"])
            return existing, False

        try:
            with transaction.atomic():
                artifact = MatchArtifact.objects.create(
                    user=user,
                    match_score=match_score,
                    kind=kind,
                    resume_content_hash=current_hash,
                    content_markdown=content_markdown,
                    model_name=model_name,
                )
                return artifact, True
        except IntegrityError:
            raced = MatchArtifact.objects.get(
                user=user,
                match_score=match_score,
                kind=kind,
                resume_content_hash=current_hash,
            )
            raced.content_markdown = content_markdown
            raced.model_name = model_name
            raced.save(update_fields=["content_markdown", "model_name"])
            return raced, False


def get_or_generate_match_artifact(
    *,
    user,
    match_score: MatchScore,
    kind: str,
    regenerate: bool = False,
    tone: str | None = None,
    guidance: str = "",
    genai_client: genai.Client | None = None,
) -> CopilotArtifactResult:
    current_hash = match_score.resume_profile.content_hash
    clean_guidance = guidance.strip()
    user_profile = _load_user_profile_readonly(user)
    default_tone = (
        user_profile.default_copilot_tone
        if user_profile is not None and user_profile.default_copilot_tone
        else COPILOT_TONE_BALANCED
    )
    effective_tone = tone or default_tone
    force_generate = (
        regenerate
        or (tone is not None and tone != default_tone)
        or bool(clean_guidance)
    )

    if not force_generate:
        cached = (
            MatchArtifact.objects.select_related("match_score__resume_profile")
            .filter(
                user=user,
                match_score=match_score,
                kind=kind,
                resume_content_hash=current_hash,
            )
            .first()
        )
        if cached is not None:
            return CopilotArtifactResult(artifact=cached, cached=True, created=False)

    enforce_copilot_rate_limit(user.pk)
    prompt = build_copilot_prompt(
        match_score=match_score,
        kind=kind,
        tone=effective_tone,
        guidance=clean_guidance,
        user_profile=user_profile,
    )
    content_markdown, model_name = invoke_copilot_gemini(
        user=user,
        prompt=prompt,
        genai_client=genai_client,
    )
    artifact, created = _persist_artifact(
        user=user,
        match_score=match_score,
        kind=kind,
        current_hash=current_hash,
        content_markdown=content_markdown,
        model_name=model_name,
    )
    artifact.match_score = match_score
    return CopilotArtifactResult(artifact=artifact, cached=False, created=created)
