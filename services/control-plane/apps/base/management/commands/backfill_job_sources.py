import math
from typing import Any

from django.core.management.base import BaseCommand
from django.db import connection, transaction
from django.db.models import Count
from django.utils import timezone

from apps.jobs.models.jobs import JobPosting, JobPostingSource
from apps.jobs.models.triage import DismissedJob
from apps.matching.models.artifacts import MatchArtifact
from apps.matching.models.matching import MatchScore
from apps.tracker.models import ApplicationLead
from vektryn_contracts import (
    UNKNOWN_LANGUAGE,
    LeadStatus,
    are_regions_compatible,
    compute_description_fingerprint,
    get_source_priority_rank,
    is_generic_company_name,
    normalize_company_for_dedup,
    normalize_title_for_dedup,
    token_jaccard_similarity,
)

DEFAULT_COSINE_THRESHOLD = 0.94
DEFAULT_TITLE_JACCARD_THRESHOLD = 0.75

_LEAD_STAGE_RANK: dict[str, int] = {
    LeadStatus.WITHDRAWN.value: -2,
    LeadStatus.REJECTED.value: -1,
    LeadStatus.DISCOVERED.value: 0,
    LeadStatus.SAVED.value: 1,
    LeadStatus.APPLIED.value: 2,
    LeadStatus.SCREENING.value: 3,
    LeadStatus.INTERVIEWING.value: 4,
    LeadStatus.OFFER.value: 5,
}


def _cosine_similarity(vec_a: Any, vec_b: Any) -> float:
    if vec_a is None or vec_b is None:
        return 0.0
    a = [float(x) for x in vec_a]
    b = [float(x) for x in vec_b]
    if len(a) != len(b) or not a:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if math.isclose(norm_a, 0.0, abs_tol=1e-12) or math.isclose(
        norm_b, 0.0, abs_tol=1e-12
    ):
        return 0.0
    return dot / (norm_a * norm_b)


def _passes_stage0_guardrails(
    canonical: JobPosting,
    candidate: JobPosting,
    *,
    cosine_threshold: float,
) -> bool:
    if (
        canonical.language != UNKNOWN_LANGUAGE
        and candidate.language != UNKNOWN_LANGUAGE
        and canonical.language != candidate.language
    ):
        return False
    if (
        canonical.seniority != "unknown"
        and candidate.seniority != "unknown"
        and canonical.seniority != candidate.seniority
    ):
        return False
    if (
        canonical.work_mode != "unknown"
        and candidate.work_mode != "unknown"
        and canonical.work_mode != candidate.work_mode
    ):
        return False
    if not are_regions_compatible(
        canonical.region_eligibility,
        candidate.region_eligibility,
    ):
        return False

    title_a = canonical.title_normalized or normalize_title_for_dedup(canonical.title)
    title_b = candidate.title_normalized or normalize_title_for_dedup(candidate.title)
    if token_jaccard_similarity(title_a, title_b) < DEFAULT_TITLE_JACCARD_THRESHOLD:
        return False

    return (
        _cosine_similarity(canonical.embedding, candidate.embedding) >= cosine_threshold
    )


def _primary_rank_for_job(job: JobPosting) -> int:
    primary = (
        JobPostingSource.objects.filter(job_posting=job, is_primary=True)
        .values_list("ats_source", flat=True)
        .first()
    )
    return get_source_priority_rank(primary or job.ats_source)


def _transfer_match_artifacts(
    source_match: MatchScore, target_match: MatchScore
) -> None:
    existing_keys = set(
        MatchArtifact.objects.filter(match_score=target_match).values_list(
            "kind", "resume_content_hash"
        )
    )
    for artifact in MatchArtifact.objects.filter(match_score=source_match):
        key = (artifact.kind, artifact.resume_content_hash)
        if key in existing_keys:
            artifact.is_deleted = True
            artifact.save(update_fields=["is_deleted", "modified_at"])
        else:
            artifact.match_score = target_match
            artifact.save(update_fields=["match_score", "modified_at"])
            existing_keys.add(key)


def _copy_match_score_fields(
    source_match: MatchScore, target_match: MatchScore
) -> None:
    target_match.cosine_similarity = source_match.cosine_similarity
    target_match.fit_score = source_match.fit_score
    target_match.matched_skills = list(source_match.matched_skills or [])
    target_match.missing_keywords = list(source_match.missing_keywords or [])
    target_match.talking_points = list(source_match.talking_points or [])
    target_match.gap_summary = source_match.gap_summary
    target_match.fit_highlights = list(source_match.fit_highlights or [])
    target_match.watchout_note = source_match.watchout_note
    target_match.resume_content_hash = source_match.resume_content_hash
    target_match.scoring_model = source_match.scoring_model


def _earliest_non_null_dt(dt_a: Any, dt_b: Any) -> Any:
    if dt_a is None:
        return dt_b
    if dt_b is None:
        return dt_a
    return min(dt_a, dt_b)


def _latest_non_null_dt(dt_a: Any, dt_b: Any) -> Any:
    if dt_a is None:
        return dt_b
    if dt_b is None:
        return dt_a
    return max(dt_a, dt_b)


def _soft_delete_duplicate_match(ms_b: MatchScore) -> None:
    ms_b.is_deleted = True
    ms_b.is_routed_winner = False
    ms_b.save(update_fields=["is_deleted", "is_routed_winner", "modified_at"])


def _merge_active_match_scores(ms_a: MatchScore, ms_b: MatchScore) -> None:
    score_a = ms_a.fit_score if ms_a.fit_score is not None else -1
    score_b = ms_b.fit_score if ms_b.fit_score is not None else -1
    b_is_better = score_b > score_a or (
        score_b == score_a and ms_b.cosine_similarity > ms_a.cosine_similarity
    )
    if b_is_better:
        _copy_match_score_fields(ms_b, ms_a)
    ms_a.alert_sent_at = _earliest_non_null_dt(ms_a.alert_sent_at, ms_b.alert_sent_at)
    ms_a.save()


def _merge_single_match_score(canonical: JobPosting, ms_b: MatchScore) -> None:
    ms_a = MatchScore.all_objects.filter(
        job_posting=canonical,
        resume_profile=ms_b.resume_profile,
    ).first()
    if ms_a is None:
        ms_b.job_posting = canonical
        ms_b.save(update_fields=["job_posting", "modified_at"])
        return

    if ms_a.is_deleted:
        ms_a.is_deleted = False
        _copy_match_score_fields(ms_b, ms_a)
        ms_a.alert_sent_at = ms_a.alert_sent_at or ms_b.alert_sent_at
        ms_a.is_routed_winner = ms_a.is_routed_winner or ms_b.is_routed_winner
        ms_a.save()
    else:
        _merge_active_match_scores(ms_a, ms_b)

    _transfer_match_artifacts(ms_b, ms_a)
    _soft_delete_duplicate_match(ms_b)


def _reconcile_match_scores(canonical: JobPosting, duplicate: JobPosting) -> set[int]:
    affected_user_ids: set[int] = set()
    dup_matches = list(
        MatchScore.objects.select_related("resume_profile").filter(
            job_posting=duplicate
        )
    )
    for ms_b in dup_matches:
        affected_user_ids.add(ms_b.resume_profile.user_id)
        _merge_single_match_score(canonical, ms_b)

    affected_user_ids.update(
        MatchScore.objects.filter(job_posting=canonical).values_list(
            "resume_profile__user_id", flat=True
        )
    )
    return affected_user_ids


def _re_elect_routed_winners(canonical: JobPosting, user_ids: set[int]) -> None:
    for user_id in sorted(user_ids):
        with connection.cursor() as cur:
            cur.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                [f"vektryn:winner:{user_id}:{canonical.uuid}"],
            )
        user_matches = list(
            MatchScore.objects.filter(
                job_posting=canonical,
                resume_profile__user_id=user_id,
                resume_profile__is_deleted=False,
            )
        )
        if not user_matches:
            continue
        user_matches.sort(
            key=lambda m: (
                -(m.fit_score if m.fit_score is not None else -1),
                -float(m.cosine_similarity),
                m.created_at,
            )
        )
        winner_uuid = user_matches[0].uuid
        for ms in user_matches:
            should_win = ms.uuid == winner_uuid
            if ms.is_routed_winner != should_win:
                ms.is_routed_winner = should_win
                ms.save(update_fields=["is_routed_winner", "modified_at"])


def _merge_lead_notes(notes_a: str | None, notes_b: str | None) -> str:
    clean_a = (notes_a or "").strip()
    clean_b = (notes_b or "").strip()
    if not clean_b or clean_b == clean_a:
        return clean_a
    return f"{clean_a}\n\n---\n\n{clean_b}" if clean_a else clean_b


def _merge_existing_lead(lead_a: ApplicationLead, lead_b: ApplicationLead) -> None:
    if _LEAD_STAGE_RANK.get(lead_b.status, 0) > _LEAD_STAGE_RANK.get(lead_a.status, 0):
        lead_a.status = lead_b.status
        if lead_b.resume_profile_id and not lead_a.resume_profile_id:
            lead_a.resume_profile_id = lead_b.resume_profile_id

    lead_a.applied_at = _earliest_non_null_dt(lead_a.applied_at, lead_b.applied_at)
    lead_a.last_activity_at = _latest_non_null_dt(
        lead_a.last_activity_at, lead_b.last_activity_at
    )
    lead_a.notes = _merge_lead_notes(lead_a.notes, lead_b.notes)
    lead_a.save()

    lead_b.is_deleted = True
    lead_b.save(update_fields=["is_deleted", "modified_at"])


def _reconcile_leads(canonical: JobPosting, duplicate: JobPosting) -> None:
    for lead_b in ApplicationLead.objects.filter(job_posting=duplicate):
        lead_a = ApplicationLead.objects.filter(
            user_id=lead_b.user_id,
            job_posting=canonical,
        ).first()
        if lead_a is None:
            lead_b.job_posting = canonical
            lead_b.save(update_fields=["job_posting", "modified_at"])
        else:
            _merge_existing_lead(lead_a, lead_b)


def _reconcile_dismissals(canonical: JobPosting, duplicate: JobPosting) -> None:
    for dismissed_b in DismissedJob.objects.filter(job_posting=duplicate):
        exists_on_a = DismissedJob.objects.filter(
            user_id=dismissed_b.user_id,
            job_posting=canonical,
        ).exists()
        if exists_on_a:
            dismissed_b.is_deleted = True
            dismissed_b.save(update_fields=["is_deleted", "modified_at"])
        else:
            dismissed_b.job_posting = canonical
            dismissed_b.save(update_fields=["job_posting", "modified_at"])


def _repoint_and_promote_sources(
    canonical: JobPosting,
    duplicate: JobPosting,
    *,
    now: Any,
) -> None:
    JobPostingSource.objects.filter(job_posting=duplicate, is_primary=True).update(
        is_primary=False,
        modified_at=now,
    )
    JobPostingSource.objects.filter(job_posting=duplicate).update(
        job_posting=canonical,
        modified_at=now,
    )

    canonical_sources = list(
        JobPostingSource.objects.filter(job_posting=canonical).order_by(
            "-is_active", "first_seen_at"
        )
    )
    best_pool = [s for s in canonical_sources if s.is_active] or canonical_sources
    if not best_pool:
        return

    best_source = min(
        best_pool,
        key=lambda s: (get_source_priority_rank(s.ats_source), s.first_seen_at),
    )
    current_primary = next((s for s in canonical_sources if s.is_primary), None)
    should_swap = (
        current_primary is None
        or (not current_primary.is_active and best_source.is_active)
        or get_source_priority_rank(best_source.ats_source)
        < get_source_priority_rank(current_primary.ats_source)
    )
    if should_swap and (
        current_primary is None or current_primary.uuid != best_source.uuid
    ):
        JobPostingSource.objects.filter(job_posting=canonical, is_primary=True).update(
            is_primary=False, modified_at=now
        )
        best_source.is_primary = True
        best_source.save(update_fields=["is_primary", "modified_at"])
        canonical.apply_url = best_source.apply_url


def _backfill_unknown_field(
    canonical: JobPosting,
    duplicate: JobPosting,
    field_name: str,
    unknown_value: str = "unknown",
) -> None:
    if (
        getattr(canonical, field_name) == unknown_value
        and getattr(duplicate, field_name) != unknown_value
    ):
        setattr(canonical, field_name, getattr(duplicate, field_name))


def _backfill_canonical_metadata(
    canonical: JobPosting,
    duplicate: JobPosting,
) -> None:
    if (
        canonical.salary_min is None
        and canonical.salary_max is None
        and (duplicate.salary_min is not None or duplicate.salary_max is not None)
    ):
        canonical.salary_min = duplicate.salary_min
        canonical.salary_max = duplicate.salary_max
        canonical.salary_currency = duplicate.salary_currency
        canonical.salary_period = duplicate.salary_period
        canonical.salary_annual_min_usd = duplicate.salary_annual_min_usd
        canonical.salary_annual_max_usd = duplicate.salary_annual_max_usd
        canonical.salary_annual_mid_usd = duplicate.salary_annual_mid_usd

    for field_name, unknown_val in (
        ("work_mode", "unknown"),
        ("language", UNKNOWN_LANGUAGE),
        ("seniority", "unknown"),
        ("contract_type", "unknown"),
    ):
        _backfill_unknown_field(canonical, duplicate, field_name, unknown_val)

    canonical.tech_stack = list(
        dict.fromkeys([*(canonical.tech_stack or []), *(duplicate.tech_stack or [])])
    )
    canonical.region_eligibility = list(
        dict.fromkeys(
            [
                *(canonical.region_eligibility or []),
                *(duplicate.region_eligibility or []),
            ]
        )
    )
    if duplicate.repost_count:
        canonical.repost_count += duplicate.repost_count
        canonical.last_reposted_at = _latest_non_null_dt(
            canonical.last_reposted_at, duplicate.last_reposted_at
        )


def merge_duplicate_job_into_canonical(
    canonical: JobPosting,
    duplicate: JobPosting,
) -> None:
    """Safely merge duplicate JobPosting B into canonical JobPosting A inside an active tx."""
    now = timezone.now()
    _repoint_and_promote_sources(canonical, duplicate, now=now)
    _backfill_canonical_metadata(canonical, duplicate)
    canonical.save()

    affected_users = _reconcile_match_scores(canonical, duplicate)
    _re_elect_routed_winners(canonical, affected_users)
    _reconcile_leads(canonical, duplicate)
    _reconcile_dismissals(canonical, duplicate)

    duplicate.is_deleted = True
    duplicate.is_active = False
    duplicate.closed_at = duplicate.closed_at or now
    duplicate.save(
        update_fields=["is_deleted", "is_active", "closed_at", "modified_at"]
    )


def _normalize_job_dedup_keys(job: JobPosting, now: Any) -> bool:
    comp_norm = normalize_company_for_dedup(job.company_name)[:255]
    title_norm = normalize_title_for_dedup(job.title)[:255]
    desc_fp, _ = compute_description_fingerprint(job.description_clean)
    changed = (
        job.company_name_normalized != comp_norm
        or job.title_normalized != title_norm
        or job.description_fingerprint != desc_fp
    )
    if changed:
        job.company_name_normalized = comp_norm
        job.title_normalized = title_norm
        job.description_fingerprint = desc_fp
        job.modified_at = now
    return changed


def _flush_backfill_batch(
    pending_jobs: list[JobPosting],
    batch_jobs: list[JobPosting],
    *,
    dry_run: bool,
) -> int:
    if pending_jobs and not dry_run:
        JobPosting.objects.bulk_update(
            pending_jobs,
            [
                "company_name_normalized",
                "title_normalized",
                "description_fingerprint",
                "modified_at",
            ],
        )
    pending_jobs.clear()

    if not batch_jobs:
        return 0

    existing_primary_job_ids = set(
        JobPostingSource.objects.filter(
            job_posting_id__in=[j.uuid for j in batch_jobs],
            is_primary=True,
        ).values_list("job_posting_id", flat=True)
    )
    existing_pairs = set(
        JobPostingSource.objects.filter(
            ats_source__in={j.ats_source for j in batch_jobs},
            external_id__in={j.external_id for j in batch_jobs},
        ).values_list("ats_source", "external_id")
    )
    to_create: list[JobPostingSource] = []
    for j in batch_jobs:
        pair = (j.ats_source, j.external_id)
        if pair in existing_pairs:
            continue
        to_create.append(
            JobPostingSource(
                job_posting=j,
                ats_source=j.ats_source,
                external_id=j.external_id,
                apply_url=j.apply_url,
                raw_html_gcs_uri=j.raw_html_gcs_uri,
                is_primary=j.uuid not in existing_primary_job_ids,
                is_active=j.is_active,
                first_seen_at=j.created_at,
                last_seen_at=j.modified_at or j.created_at,
            )
        )
        existing_pairs.add(pair)
        existing_primary_job_ids.add(j.uuid)

    if to_create and not dry_run:
        JobPostingSource.objects.bulk_create(to_create, ignore_conflicts=True)
    batch_jobs.clear()
    return len(to_create)


def _find_matching_canonical(
    canonicals: list[JobPosting],
    candidate: JobPosting,
    *,
    cosine_threshold: float,
) -> JobPosting | None:
    return next(
        (
            canonical
            for canonical in canonicals
            if _passes_stage0_guardrails(
                canonical, candidate, cosine_threshold=cosine_threshold
            )
        ),
        None,
    )


def _merge_company_duplicates(
    company_norm: str,
    *,
    dry_run: bool,
    cosine_threshold: float,
) -> int:
    merged_count = 0
    with transaction.atomic():
        with connection.cursor() as cur:
            cur.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                [f"vektryn:job_dedup:{company_norm}"],
            )
        postings = list(
            JobPosting.objects.filter(
                is_active=True,
                embedding__isnull=False,
                company_name_normalized=company_norm,
            ).order_by("created_at")
        )
        postings.sort(key=lambda p: (_primary_rank_for_job(p), p.created_at))

        canonicals: list[JobPosting] = []
        for candidate in postings:
            matched = _find_matching_canonical(
                canonicals, candidate, cosine_threshold=cosine_threshold
            )
            if matched is None:
                canonicals.append(candidate)
                continue
            merged_count += 1
            if not dry_run:
                merge_duplicate_job_into_canonical(matched, candidate)
    return merged_count


class Command(BaseCommand):
    help = (
        "Idempotently backfill JobPosting dedup keys and initial JobPostingSource rows, "
        "with optional --merge-duplicates historical cleanup at $0 LLM cost."
    )

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--batch-size",
            type=int,
            default=500,
            help="Number of JobPosting rows processed per batch (default: 500).",
        )
        parser.add_argument(
            "--merge-duplicates",
            action="store_true",
            help="Detect and safely merge active cross-source near-duplicate JobPostings.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Preview backfill and merge counts without writing to PostgreSQL.",
        )
        parser.add_argument(
            "--cosine-threshold",
            type=float,
            default=DEFAULT_COSINE_THRESHOLD,
            help=f"Cosine threshold for --merge-duplicates (default: {DEFAULT_COSINE_THRESHOLD}).",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        batch_size = max(1, int(options["batch_size"]))
        merge_duplicates = bool(options["merge_duplicates"])
        dry_run = bool(options["dry_run"])
        cosine_threshold = float(options["cosine_threshold"])

        self._backfill_keys_and_sources(batch_size=batch_size, dry_run=dry_run)
        if merge_duplicates:
            self._merge_historical_duplicates(
                dry_run=dry_run,
                cosine_threshold=cosine_threshold,
            )

    def _backfill_keys_and_sources(self, *, batch_size: int, dry_run: bool) -> None:
        qs = JobPosting.objects.only(
            "uuid",
            "ats_source",
            "external_id",
            "title",
            "company_name",
            "apply_url",
            "raw_html_gcs_uri",
            "description_clean",
            "is_active",
            "created_at",
            "modified_at",
            "company_name_normalized",
            "title_normalized",
            "description_fingerprint",
        ).order_by("created_at")
        scanned = 0
        updated_jobs = 0
        created_sources = 0
        pending_jobs: list[JobPosting] = []
        batch_jobs: list[JobPosting] = []
        now = timezone.now()

        for job in qs.iterator(chunk_size=batch_size):
            scanned += 1
            if _normalize_job_dedup_keys(job, now):
                pending_jobs.append(job)
                updated_jobs += 1

            batch_jobs.append(job)
            if len(batch_jobs) >= batch_size:
                created_sources += _flush_backfill_batch(
                    pending_jobs, batch_jobs, dry_run=dry_run
                )

        created_sources += _flush_backfill_batch(
            pending_jobs, batch_jobs, dry_run=dry_run
        )
        mode = "DRY-RUN" if dry_run else "APPLIED"
        self.stdout.write(
            f"[{mode}] backfill_job_sources: scanned={scanned} "
            f"updated_jobs={updated_jobs} created_sources={created_sources}"
        )

    def _merge_historical_duplicates(
        self,
        *,
        dry_run: bool,
        cosine_threshold: float,
    ) -> None:
        company_groups = list(
            JobPosting.objects.filter(
                is_active=True,
                embedding__isnull=False,
            )
            .exclude(company_name_normalized="")
            .values("company_name_normalized")
            .annotate(total=Count("uuid"))
            .filter(total__gte=2)
            .order_by("company_name_normalized")
            .values_list("company_name_normalized", flat=True)
        )

        merged_count = 0
        companies_checked = 0

        for company_norm in company_groups:
            if is_generic_company_name(company_norm):
                continue
            companies_checked += 1
            merged_count += _merge_company_duplicates(
                company_norm,
                dry_run=dry_run,
                cosine_threshold=cosine_threshold,
            )

        mode = "DRY-RUN" if dry_run else "APPLIED"
        self.stdout.write(
            f"[{mode}] merge_duplicates: companies_checked={companies_checked} "
            f"merged_duplicates={merged_count}"
        )
