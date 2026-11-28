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
from vektryn_contracts import ATSSource, WorkMode

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

_REMOTE_MODE_RE = re.compile(
    r"\b(?:remote|remoto|remota|home[\s_-]*office|work\s+from\s+home|wfh|telecommut\w*|anywhere)\b",
    re.IGNORECASE,
)
_HYBRID_MODE_RE = re.compile(
    r"\b(?:hybrid|h[ií]brid[oa])\b",
    re.IGNORECASE,
)
_ONSITE_MODE_RE = re.compile(
    r"\b(?:on[\s_-]*site|in[\s_-]*office|presencial)\b",
    re.IGNORECASE,
)

_CONTRACT_PATTERNS: dict[str, re.Pattern[str]] = {
    "clt": re.compile(r"\bclt\b", re.IGNORECASE),
    "pj": re.compile(r"\bpj\b|\bpessoa\s+jur[ií]dica\b", re.IGNORECASE),
    "b2b_contractor": re.compile(
        r"\bb2b\b|\bindependent\s+contractor\b|\bcontractor\b", re.IGNORECASE
    ),
    "eor": re.compile(
        r"\beor\b|\bemployer\s+of\s+record\b|\bdeel\b|\bremote\.com\b", re.IGNORECASE
    ),
    "w2": re.compile(r"\bw-?2\b", re.IGNORECASE),
    "c2c": re.compile(r"\bc2c\b|\bcorp[- ]to[- ]corp\b", re.IGNORECASE),
}

_INTERNSHIP_RE = re.compile(
    r"\b(?:intern|internship|est[aá]gio|estagi[aá]rio|trainee)\b", re.IGNORECASE
)


def _compile_word_patterns(terms: Iterable[str]) -> tuple[re.Pattern[str], ...]:
    compiled: list[re.Pattern[str]] = []
    for raw in terms:
        term = raw.strip().lower()
        if not term:
            continue
        left_boundary = r"(?<![a-z0-9])" if term[0].isalnum() else ""
        right_boundary = r"(?![a-z0-9])" if term[-1].isalnum() else ""
        compiled.append(
            re.compile(
                rf"{left_boundary}{re.escape(term)}{right_boundary}",
                re.IGNORECASE,
            )
        )
    return tuple(compiled)


@lru_cache(maxsize=32)
def _cached_word_patterns(
    terms_key: tuple[str, ...],
) -> tuple[re.Pattern[str], ...]:
    return _compile_word_patterns(terms_key)


@lru_cache(maxsize=2)
def _discipline_patterns(
    dynamic_stacks: frozenset[str] = frozenset(),
) -> dict[str, tuple[re.Pattern[str], ...]]:
    taxonomy = load_taxonomy(dynamic_stacks)
    return {
        disc: _cached_word_patterns(tuple(terms))
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
    target_work_modes: frozenset[str] = frozenset()

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


def _infer_seniorities(
    text_blob: str,
    taxonomy: TechTaxonomy,
) -> set[str]:
    inferred = {
        tier
        for tier, markers in taxonomy.seniority_markers.items()
        if any(p.search(text_blob) for p in _cached_word_patterns(tuple(markers)))
    }
    return inferred or {"mid", "senior", "staff"}


def _parse_str_list(raw_val: object) -> list[str]:
    if isinstance(raw_val, list):
        return [s.strip().lower() for s in raw_val if isinstance(s, str) and s.strip()]
    if isinstance(raw_val, str) and raw_val.strip():
        parsed = json.loads(raw_val)
        if isinstance(parsed, list):
            return [
                s.strip().lower() for s in parsed if isinstance(s, str) and s.strip()
            ]
    return []


def _merge_gate_union(target: set[str], unrestricted: bool, raw_values: object) -> bool:
    parsed = _parse_str_list(raw_values)
    if not parsed:
        return True
    target.update(parsed)
    return unrestricted


def _finalize_gate_union(target: set[str], unrestricted: bool) -> set[str]:
    return set() if unrestricted else target


def _collect_profile_rows(
    rows: list[tuple[object, ...]],
) -> tuple[list[str], set[str], set[str], set[str], set[str], set[str], list[str]]:
    resume_ids: list[str] = []
    skills: set[str] = set()
    seniorities: set[str] = set()
    contracts: set[str] = set()
    regions: set[str] = set()
    work_modes: set[str] = set()
    has_unrestricted_seniority = False
    has_unrestricted_contract = False
    has_unrestricted_region = False
    has_unrestricted_work_mode = False
    discipline_blobs: list[str] = []

    for row in rows:
        (
            row_uuid,
            label,
            raw_text,
            raw_skills,
            raw_sen,
            raw_contract,
            raw_region,
            *extra,
        ) = row
        resume_ids.append(str(row_uuid))
        clean_skills = _parse_str_list(raw_skills)
        skills.update(clean_skills)

        has_unrestricted_seniority = _merge_gate_union(
            seniorities, has_unrestricted_seniority, raw_sen
        )
        has_unrestricted_contract = _merge_gate_union(
            contracts, has_unrestricted_contract, raw_contract
        )
        has_unrestricted_region = _merge_gate_union(
            regions, has_unrestricted_region, raw_region
        )
        raw_work_modes = extra[0] if extra else None
        has_unrestricted_work_mode = _merge_gate_union(
            work_modes, has_unrestricted_work_mode, raw_work_modes
        )

        discipline_blobs.append(
            f"{label or ''}\n{' '.join(clean_skills)}\n{(raw_text or '')[:1500]}"
        )

    return (
        resume_ids,
        skills,
        _finalize_gate_union(seniorities, has_unrestricted_seniority),
        _finalize_gate_union(contracts, has_unrestricted_contract),
        _finalize_gate_union(regions, has_unrestricted_region),
        _finalize_gate_union(work_modes, has_unrestricted_work_mode),
        discipline_blobs,
    )


def load_resume_criteria(
    resume_id: str | None = None,
    *,
    dynamic_stacks: frozenset[str] = frozenset(),
) -> ResumeFilterCriteria | None:
    """Load DB target constraints first, falling back to resume text inference when empty."""
    query = """
        SELECT r.uuid, r.label, r.raw_text, r.extracted_skills, r.target_seniority, r.target_contract_types, r.target_regions, r.target_work_modes
        FROM resumes_resumeprofile r
        INNER JOIN auth_user u
          ON u.id = r.user_id
         AND u.is_active = TRUE
        WHERE r.is_deleted = FALSE
          AND r.is_active = TRUE
    """
    params: list[object] = []
    if resume_id:
        query += " AND r.uuid = %s"
        params.append(uuid.UUID(str(resume_id).strip()))

    with psycopg.connect(settings.postgres_dsn) as conn, conn.cursor() as cur:
        cur.execute(query, params)
        rows = cur.fetchall()

    if not rows:
        if resume_id:
            raise ValueError(f"Active ResumeProfile not found for uuid={resume_id}")
        logger.warning(
            "No active ResumeProfile found in DB; falling back to generic engineering filter."
        )
        return None

    taxonomy = load_taxonomy(dynamic_stacks)
    (
        resume_ids,
        skills,
        db_seniorities,
        db_contracts,
        db_regions,
        db_work_modes,
        blobs,
    ) = _collect_profile_rows(rows)
    combined_blob = "\n".join(blobs)

    resolved_seniorities = db_seniorities or _infer_seniorities(combined_blob, taxonomy)
    resolved_regions = db_regions or {"brazil", "latam", "worldwide"}
    active_disciplines = _infer_disciplines(combined_blob, dynamic_stacks)

    criteria = ResumeFilterCriteria(
        resume_ids=tuple(resume_ids),
        skills=frozenset(skills),
        target_seniority=frozenset(resolved_seniorities),
        target_contract_types=frozenset(db_contracts),
        target_regions=frozenset(resolved_regions),
        active_disciplines=active_disciplines,
        target_work_modes=frozenset(db_work_modes),
    )
    logger.info(
        "Loaded pre-filter criteria from %d resume(s): skills=%d, disciplines=%s, seniority=%s, contracts=%s, regions=%s, work_modes=%s",
        len(resume_ids),
        len(criteria.skills),
        sorted(criteria.active_disciplines),
        sorted(criteria.target_seniority),
        sorted(criteria.target_contract_types),
        sorted(criteria.target_regions),
        sorted(criteria.target_work_modes) if criteria.target_work_modes else ["*"],
    )
    return criteria


def _is_software_role(title_lower: str, taxonomy: TechTaxonomy) -> bool:
    return any(kw.lower() in title_lower for kw in taxonomy.software_role_keywords)


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
        if any(p.search(title_lower) for p in _cached_word_patterns(tuple(markers)))
    }
    if not title_tiers:
        return True

    return bool(title_tiers & target_seniority)


def _passes_contract_gate(
    title_lower: str,
    location_lower: str,
    description_lower: str,
    target_contract_types: frozenset[str],
) -> bool:
    if not target_contract_types:
        return True

    if "intern" not in target_contract_types and _INTERNSHIP_RE.search(title_lower):
        return False

    header_and_excerpt = f"{title_lower}\n{location_lower}\n{description_lower[:1500]}"
    detected_contracts = {
        ctype
        for ctype, pat in _CONTRACT_PATTERNS.items()
        if pat.search(header_and_excerpt)
    }
    if not detected_contracts:
        return True

    return bool(detected_contracts & target_contract_types)


def _classify_work_mode_text(text: str) -> WorkMode:
    if not text or not text.strip():
        return WorkMode.UNKNOWN
    has_hybrid = bool(_HYBRID_MODE_RE.search(text))
    has_onsite = bool(_ONSITE_MODE_RE.search(text))
    has_remote = bool(_REMOTE_MODE_RE.search(text))
    if has_hybrid:
        return WorkMode.HYBRID
    if has_onsite and not has_remote:
        return WorkMode.ONSITE
    if has_remote and not has_onsite:
        return WorkMode.REMOTE
    return WorkMode.UNKNOWN


def detect_deterministic_work_mode(job: CollectedJob) -> WorkMode:
    """Detect high-confidence workplace signals from ATS metadata and title/location."""
    hint_mode = _classify_work_mode_text(job.work_mode_hint)
    if hint_mode != WorkMode.UNKNOWN:
        return hint_mode
    return _classify_work_mode_text(f"{job.title}\n{job.location_raw}")


def _passes_work_mode_gate(
    job: CollectedJob,
    criteria: ResumeFilterCriteria,
) -> bool:
    if job.ats_source == ATSSource.MANUAL:
        return True
    if not criteria.target_work_modes:
        return True
    detected = detect_deterministic_work_mode(job)
    if detected in (WorkMode.ONSITE, WorkMode.HYBRID):
        return detected.value in criteria.target_work_modes
    return True


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

    allows_explicitly = any(
        m in location_lower
        for m in ("brazil", "brasil", "latam", "worldwide", "anywhere")
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
    if job.ats_source == ATSSource.MANUAL:
        return 1000
    title_lower = job.title.lower()
    location_lower = job.location_raw.lower()
    desc_lower = job.description_clean.lower()

    if not _passes_work_mode_gate(job, ctx.criteria):
        return None
    if not _passes_discipline_gate(
        title_lower, ctx.criteria.active_disciplines, ctx.dynamic_stacks
    ):
        return None
    if not _passes_seniority_gate(
        title_lower, ctx.criteria.target_seniority, ctx.taxonomy
    ):
        return None
    if not _passes_contract_gate(
        title_lower, location_lower, desc_lower, ctx.criteria.target_contract_types
    ):
        return None
    if not _passes_location_gate(title_lower, location_lower, desc_lower, ctx.criteria):
        return None
    if _has_competing_title_stack(
        title_lower, ctx.required_core_patterns, ctx.competing_core_patterns
    ):
        return None

    searchable = f"{title_lower}\n{location_lower}\n{desc_lower}"
    if ctx.required_core_patterns and not any(
        p.search(searchable) for p in ctx.required_core_patterns
    ):
        return None

    overlap = sum(1 for pat in ctx.all_skill_patterns if pat.search(searchable))
    if ctx.all_skill_patterns and overlap < ctx.min_skill_matches:
        return None

    remote_bonus = (
        1 if any(m in location_lower for m in ctx.taxonomy.remote_markers) else 0
    )
    return overlap * 10 + remote_bonus


def filter_and_score_jobs(
    jobs: list[CollectedJob],
    criteria: ResumeFilterCriteria | None,
    *,
    dynamic_stacks: frozenset[str] = frozenset(),
    min_skill_matches: int = 1,
) -> list[tuple[int, CollectedJob]]:
    """Filter collected ATS postings dynamically and return (relevance_score, job) pairs."""
    taxonomy = load_taxonomy(dynamic_stacks)
    role_jobs = [
        job
        for job in jobs
        if job.ats_source == ATSSource.MANUAL
        or _is_software_role(job.title.lower(), taxonomy)
    ]
    if criteria is None:
        return [(0, job) for job in role_jobs]

    user_core_skills = criteria.skills & taxonomy.primary_stacks
    competing_core_skills = taxonomy.primary_stacks - criteria.skills

    ctx = _CompiledFilterContext(
        taxonomy=taxonomy,
        criteria=criteria,
        dynamic_stacks=dynamic_stacks,
        min_skill_matches=min_skill_matches,
        all_skill_patterns=_cached_word_patterns(tuple(sorted(criteria.skills))),
        required_core_patterns=_cached_word_patterns(tuple(sorted(user_core_skills))),
        competing_core_patterns=_cached_word_patterns(
            tuple(sorted(competing_core_skills))
        ),
    )

    scored = [
        (score, job) for job in role_jobs if (score := _score_job(job, ctx)) is not None
    ]
    scored.sort(key=lambda item: item[0], reverse=True)
    return scored


def filter_and_rank_jobs(
    jobs: list[CollectedJob],
    criteria: ResumeFilterCriteria | None,
    *,
    dynamic_stacks: frozenset[str] = frozenset(),
    min_skill_matches: int = 1,
) -> list[CollectedJob]:
    """Filter collected ATS postings dynamically against resume profile and rank by skill overlap."""
    scored = filter_and_score_jobs(
        jobs,
        criteria,
        dynamic_stacks=dynamic_stacks,
        min_skill_matches=min_skill_matches,
    )
    return [job for _, job in scored]
