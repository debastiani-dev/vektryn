from collections.abc import Iterable
from dataclasses import dataclass
from functools import lru_cache
import json
import logging
import re
import uuid

import psycopg

from stream_edge.collectors.base import CollectedJob
from stream_edge.collectors.taxonomy import TechTaxonomy, load_taxonomy
from stream_edge.config import settings

logger = logging.getLogger(__name__)

_GEO_LOCK_RE = re.compile(
    r"(?:"
    r"\bus\s+citizens?\s+only\b"
    r"|\bunited\s+states\s+only\b"
    r"|\bmust\s+(?:reside|be\s+located|live)\s+in\s+(?:the\s+)?(?:us|usa|united\s+states|uk|europe|eu|canada)\b"
    r"|\b(?:us|usa|uk|eu)\s+work\s+authorization\s+required\b"
    r"|\bon-?site\s+in\s+(?:san\s+francisco|new\s+york|london|berlin|toronto|austin|seattle)\b"
    r")",
    re.IGNORECASE,
)

_NON_AMERICAS_LOCATION_RE = re.compile(
    r"\b(?:emea|apac|europe\s+only|uk\s+only|us\s+only|usa\s+only|canada\s+only|united\s+kingdom|germany|france|netherlands|india|singapore|australia)\b",
    re.IGNORECASE,
)


def _compile_word_patterns(terms: Iterable[str]) -> tuple[re.Pattern[str], ...]:
    return tuple(
        re.compile(rf"(?<![a-z0-9]){re.escape(t)}(?![a-z0-9])", re.IGNORECASE)
        for t in terms
    )


@lru_cache(maxsize=2)
def _discipline_patterns(
    dynamic_stacks: frozenset[str] = frozenset(),
) -> dict[str, tuple[re.Pattern[str], ...]]:
    taxonomy = load_taxonomy(dynamic_stacks)
    return {
        disc: _compile_word_patterns(terms)
        for disc, terms in taxonomy.disciplines.items()
    }


@dataclass(frozen=True)
class ResumeFilterCriteria:
    resume_ids: tuple[str, ...]
    skills: frozenset[str]
    target_seniority: frozenset[str]
    target_contract_types: frozenset[str]
    target_regions: frozenset[str]
    active_disciplines: frozenset[str]

    @property
    def wants_remote_or_latam(self) -> bool:
        return bool(self.target_regions & {"brazil", "latam", "worldwide", "americas"})


def _infer_disciplines(
    text_blob: str,
    dynamic_stacks: frozenset[str] = frozenset(),
) -> frozenset[str]:
    patterns = _discipline_patterns(dynamic_stacks)
    matched = {
        disc
        for disc, disc_pats in patterns.items()
        if any(pat.search(text_blob) for pat in disc_pats)
    }
    return frozenset(matched)


def load_resume_criteria(
    resume_id: str | None = None,
    *,
    dynamic_stacks: frozenset[str] = frozenset(),
) -> ResumeFilterCriteria | None:
    """Load target constraints, skills, and inferred disciplines from active resume(s)."""
    query = """
        SELECT uuid, label, raw_text, extracted_skills, target_seniority, target_contract_types, target_regions
        FROM resumes_resumeprofile
        WHERE is_deleted = FALSE
          AND is_active = TRUE
    """
    params: list = []
    if resume_id:
        parsed_id = uuid.UUID(str(resume_id).strip())
        query += " AND uuid = %s"
        params.append(parsed_id)

    with psycopg.connect(settings.postgres_dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(query, params)
            rows = cur.fetchall()

    if not rows:
        if resume_id:
            raise ValueError(f"Active ResumeProfile not found for uuid={resume_id}")
        logger.warning("No active ResumeProfile found in DB; falling back to generic engineering filter.")
        return None

    resume_ids: list[str] = []
    skills: set[str] = set()
    seniorities: set[str] = set()
    contracts: set[str] = set()
    regions: set[str] = set()
    discipline_blobs: list[str] = []

    for row_uuid, label, raw_text, raw_skills, raw_sen, raw_contract, raw_region in rows:
        resume_ids.append(str(row_uuid))
        parsed_skills = raw_skills if isinstance(raw_skills, list) else json.loads(raw_skills or "[]")
        clean_skills = [s.strip().lower() for s in parsed_skills if isinstance(s, str) and s.strip()]
        skills.update(clean_skills)
        seniorities.update(s.strip().lower() for s in (raw_sen or []) if s)
        contracts.update(c.strip().lower() for c in (raw_contract or []) if c)
        regions.update(r.strip().lower() for r in (raw_region or []) if r)
        discipline_blobs.append(f"{label or ''}\n{' '.join(clean_skills)}\n{(raw_text or '')[:1500]}")

    active_disciplines = _infer_disciplines("\n".join(discipline_blobs), dynamic_stacks)

    criteria = ResumeFilterCriteria(
        resume_ids=tuple(resume_ids),
        skills=frozenset(skills),
        target_seniority=frozenset(seniorities),
        target_contract_types=frozenset(contracts),
        target_regions=frozenset(regions),
        active_disciplines=active_disciplines,
    )
    logger.info(
        "Loaded pre-filter criteria from %d resume(s): skills=%d, disciplines=%s, seniority=%s, regions=%s",
        len(resume_ids),
        len(criteria.skills),
        sorted(criteria.active_disciplines),
        sorted(criteria.target_seniority),
        sorted(criteria.target_regions),
    )
    return criteria


def _is_software_role(title_lower: str, taxonomy: TechTaxonomy) -> bool:
    return any(kw in title_lower for kw in taxonomy.software_role_keywords)


def _passes_discipline_gate(
    title_lower: str,
    active_disciplines: frozenset[str],
    dynamic_stacks: frozenset[str],
) -> bool:
    if not active_disciplines:
        return True
    title_disciplines = _infer_disciplines(title_lower, dynamic_stacks)
    if not title_disciplines:
        return True
    return bool(title_disciplines & active_disciplines)


_HYBRID_OR_ONSITE_RE = re.compile(
    r"\b(?:hybrid|híbrido|hibrido|presencial|on-?site)\b",
    re.IGNORECASE,
)


def _passes_seniority_gate(
    title_lower: str,
    target_seniority: frozenset[str],
    taxonomy: TechTaxonomy,
) -> bool:
    if not target_seniority:
        return True

    title_tiers = {
        tier
        for tier, markers in taxonomy.seniority_markers.items()
        if any(p.search(title_lower) for p in _compile_word_patterns(markers))
    }
    if not title_tiers:
        # Generic titles without an explicit seniority label pass to skill matching
        return True

    return bool(title_tiers & target_seniority)


def _passes_location_gate(
    title_lower: str,
    location_lower: str,
    description_lower: str,
    criteria: ResumeFilterCriteria,
) -> bool:
    if not criteria.wants_remote_or_latam:
        return True

    if _NON_AMERICAS_LOCATION_RE.search(f"{title_lower}\n{location_lower}"):
        return False

    if _HYBRID_OR_ONSITE_RE.search(title_lower) and not any(
        m in title_lower for m in ("remote", "remoto", "remota", "anywhere")
    ):
        return False

    allows_explicitly = any(
        m in location_lower for m in ("brazil", "brasil", "latam", "worldwide", "anywhere")
    )
    if allows_explicitly:
        return True

    combined = f"{title_lower}\n{location_lower}\n{description_lower[:2500]}"
    return not _GEO_LOCK_RE.search(combined)


@dataclass(frozen=True)
class _CompiledFilterContext:
    taxonomy: TechTaxonomy
    criteria: ResumeFilterCriteria
    dynamic_stacks: frozenset[str]
    min_skill_matches: int
    all_skill_patterns: tuple[re.Pattern[str], ...]
    required_core_patterns: tuple[re.Pattern[str], ...]
    competing_core_patterns: tuple[re.Pattern[str], ...]


def _has_competing_title_stack(
    title_lower: str,
    required_core_patterns: tuple[re.Pattern[str], ...],
    competing_core_patterns: tuple[re.Pattern[str], ...],
) -> bool:
    if not competing_core_patterns:
        return False
    mentions_competing = any(p.search(title_lower) for p in competing_core_patterns)
    mentions_required = any(p.search(title_lower) for p in required_core_patterns)
    return mentions_competing and not mentions_required


def _score_job(job: CollectedJob, ctx: _CompiledFilterContext) -> int | None:
    title_lower = job.title.lower()
    location_lower = job.location_raw.lower()
    desc_lower = job.description_clean.lower()

    if not _passes_discipline_gate(title_lower, ctx.criteria.active_disciplines, ctx.dynamic_stacks):
        return None
    if not _passes_seniority_gate(title_lower, ctx.criteria.target_seniority, ctx.taxonomy):
        return None
    if not _passes_location_gate(title_lower, location_lower, desc_lower, ctx.criteria):
        return None
    if _has_competing_title_stack(title_lower, ctx.required_core_patterns, ctx.competing_core_patterns):
        return None

    searchable = f"{title_lower}\n{location_lower}\n{desc_lower}"
    if ctx.required_core_patterns and not any(p.search(searchable) for p in ctx.required_core_patterns):
        return None

    overlap = sum(1 for pat in ctx.all_skill_patterns if pat.search(searchable))
    if ctx.all_skill_patterns and overlap < ctx.min_skill_matches:
        return None

    remote_bonus = 1 if any(m in location_lower for m in ctx.taxonomy.remote_markers) else 0
    return overlap * 10 + remote_bonus


def filter_and_rank_jobs(
    jobs: list[CollectedJob],
    criteria: ResumeFilterCriteria | None,
    *,
    dynamic_stacks: frozenset[str] = frozenset(),
    min_skill_matches: int = 1,
) -> list[CollectedJob]:
    """Filter collected ATS postings dynamically against resume profile and rank by skill overlap."""
    taxonomy = load_taxonomy(dynamic_stacks)
    role_jobs = [job for job in jobs if _is_software_role(job.title.lower(), taxonomy)]
    if criteria is None:
        return role_jobs

    user_core_skills = criteria.skills & taxonomy.primary_stacks
    competing_core_skills = taxonomy.primary_stacks - criteria.skills

    ctx = _CompiledFilterContext(
        taxonomy=taxonomy,
        criteria=criteria,
        dynamic_stacks=dynamic_stacks,
        min_skill_matches=min_skill_matches,
        all_skill_patterns=_compile_word_patterns(criteria.skills),
        required_core_patterns=_compile_word_patterns(user_core_skills),
        competing_core_patterns=_compile_word_patterns(competing_core_skills),
    )

    scored = [
        (score, job)
        for job in role_jobs
        if (score := _score_job(job, ctx)) is not None
    ]
    scored.sort(key=lambda item: item[0], reverse=True)
    return [job for _, job in scored]