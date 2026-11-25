from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from django.db import connection
from django.db.models import Aggregate, Count, FloatField, Q, QuerySet
from django.utils import timezone

from apps.jobs.models.jobs import JobPosting
from apps.matching.models.matching import MatchScore
from apps.resumes.models.resumes import ResumeProfile
from apps.tracker.models.tracker import ApplicationLead
from vektryn_contracts.enums import LeadStatus

ALLOWED_DAY_WINDOWS: dict[str, int | None] = {
    "30": 30,
    "90": 90,
    "all": None,
}
MAX_SKILL_ITEMS = 15

APPLIED_REACHED_STATUSES: tuple[str, ...] = (
    LeadStatus.APPLIED.value,
    LeadStatus.SCREENING.value,
    LeadStatus.INTERVIEWING.value,
    LeadStatus.OFFER.value,
)
SCREENING_REACHED_STATUSES: tuple[str, ...] = (
    LeadStatus.SCREENING.value,
    LeadStatus.INTERVIEWING.value,
    LeadStatus.OFFER.value,
)
INTERVIEW_REACHED_STATUSES: tuple[str, ...] = (
    LeadStatus.INTERVIEWING.value,
    LeadStatus.OFFER.value,
)
TERMINAL_STATUSES: tuple[str, ...] = (
    LeadStatus.REJECTED.value,
    LeadStatus.WITHDRAWN.value,
)
APPLIED_REACHED_Q = Q(status__in=APPLIED_REACHED_STATUSES) | (
    Q(status__in=TERMINAL_STATUSES) & Q(applied_at__isnull=False)
)

_SKILL_COLUMNS: dict[str, str] = {
    "missing_keywords": "missing_keywords",
    "matched_skills": "matched_skills",
}


class _MedianDaysSinceApplied(Aggregate):
    function = "PERCENTILE_CONT"
    template = (
        "PERCENTILE_CONT(0.5) WITHIN GROUP "
        "(ORDER BY GREATEST(0.0, EXTRACT(EPOCH FROM (NOW() - %(expressions)s)) / 86400.0))"
    )
    output_field = FloatField()


def _safe_pct(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return round((numerator / denominator) * 100.0, 1)


def _build_pipeline_funnel(leads_qs: QuerySet[ApplicationLead]) -> dict[str, Any]:
    status_counts: dict[str, int] = {member.value: 0 for member in LeadStatus}
    for row in leads_qs.values("status").annotate(total=Count("uuid")):
        status_key = str(row["status"])
        if status_key in status_counts:
            status_counts[status_key] = int(row["total"])

    reach = leads_qs.aggregate(
        tracked=Count("uuid"),
        applied=Count("uuid", filter=APPLIED_REACHED_Q),
        screening=Count("uuid", filter=Q(status__in=SCREENING_REACHED_STATUSES)),
        interviewing=Count("uuid", filter=Q(status__in=INTERVIEW_REACHED_STATUSES)),
        offer=Count("uuid", filter=Q(status=LeadStatus.OFFER.value)),
    )
    tracked = int(reach["tracked"] or 0)
    applied = int(reach["applied"] or 0)
    screening = int(reach["screening"] or 0)
    interviewing = int(reach["interviewing"] or 0)
    offer = int(reach["offer"] or 0)

    median_raw = leads_qs.filter(applied_at__isnull=False).aggregate(
        median=_MedianDaysSinceApplied("applied_at")
    )["median"]
    median_days = (
        round(max(0.0, float(median_raw)), 1) if median_raw is not None else None
    )

    stages = [
        {
            "key": "tracked",
            "label": "Tracked",
            "count": tracked,
            "conversion_from_previous_pct": None,
        },
        {
            "key": "applied",
            "label": "Applied",
            "count": applied,
            "conversion_from_previous_pct": _safe_pct(applied, tracked),
        },
        {
            "key": "screening",
            "label": "Screening",
            "count": screening,
            "conversion_from_previous_pct": _safe_pct(screening, applied),
        },
        {
            "key": "interviewing",
            "label": "Interviewing",
            "count": interviewing,
            "conversion_from_previous_pct": _safe_pct(interviewing, screening),
        },
        {
            "key": "offer",
            "label": "Offer",
            "count": offer,
            "conversion_from_previous_pct": _safe_pct(offer, interviewing),
        },
    ]

    return {
        "total_leads": tracked,
        "status_counts": status_counts,
        "stages": stages,
        "applied_to_offer_pct": _safe_pct(offer, applied),
        "median_days_since_applied": median_days,
    }


def _build_channel_performance(
    leads_qs: QuerySet[ApplicationLead],
    group_field: str,
) -> list[dict[str, Any]]:
    rows = (
        leads_qs.values(group_field)
        .annotate(
            total_leads=Count("uuid"),
            applied_count=Count("uuid", filter=APPLIED_REACHED_Q),
            response_count=Count(
                "uuid", filter=Q(status__in=SCREENING_REACHED_STATUSES)
            ),
            interview_count=Count(
                "uuid", filter=Q(status__in=INTERVIEW_REACHED_STATUSES)
            ),
            offer_count=Count("uuid", filter=Q(status=LeadStatus.OFFER.value)),
        )
        .order_by("-applied_count", "-total_leads", group_field)
    )

    results: list[dict[str, Any]] = []
    for row in rows:
        key = str(row[group_field] or "unknown")
        total_leads = int(row["total_leads"] or 0)
        applied_count = int(row["applied_count"] or 0)
        response_count = int(row["response_count"] or 0)
        interview_count = int(row["interview_count"] or 0)
        offer_count = int(row["offer_count"] or 0)
        results.append(
            {
                "key": key,
                "total_leads": total_leads,
                "applied_count": applied_count,
                "response_count": response_count,
                "interview_count": interview_count,
                "offer_count": offer_count,
                "response_rate_pct": _safe_pct(response_count, applied_count),
                "interview_rate_pct": _safe_pct(interview_count, applied_count),
            }
        )
    return results


def _build_match_filter_clauses(
    *,
    user_id: int | str,
    cutoff: datetime | None,
    resume_profile_uuid: UUID | None,
) -> tuple[str, list[Any]]:
    clauses = [
        "rp.user_id = %s",
        "ms.is_deleted = FALSE",
        "rp.is_deleted = FALSE",
        "jp.is_deleted = FALSE",
        "ms.fit_score IS NOT NULL",
        "ms.fit_score >= rp.min_alert_score",
    ]
    params: list[Any] = [user_id]
    if cutoff is not None:
        clauses.append("ms.modified_at >= %s")
        params.append(cutoff)
    if resume_profile_uuid is not None:
        clauses.append("ms.resume_profile_id = %s")
        params.append(str(resume_profile_uuid))
    return " AND ".join(clauses), params


def _query_top_skills(
    *,
    column_key: str,
    where_sql: str,
    where_params: list[Any],
    high_fit_count: int,
    match_table: str,
    resume_table: str,
    job_table: str,
) -> list[dict[str, Any]]:
    col_name = connection.ops.quote_name(_SKILL_COLUMNS[column_key])
    normalized_expr = r"BTRIM(REGEXP_REPLACE(LOWER(kw.raw_kw), '\s+', ' ', 'g'))"
    sql = f"""
        WITH dedup AS (
            SELECT DISTINCT
                ms.uuid AS match_uuid,
                ms.fit_score AS fit_score,
                {normalized_expr} AS skill
            FROM {match_table} AS ms
            INNER JOIN {resume_table} AS rp ON rp.uuid = ms.resume_profile_id
            INNER JOIN {job_table} AS jp ON jp.uuid = ms.job_posting_id
            CROSS JOIN LATERAL jsonb_array_elements_text(ms.{col_name}) AS kw(raw_kw)
            WHERE {where_sql}
              AND jsonb_typeof(ms.{col_name}) = 'array'
              AND {normalized_expr} <> ''
        )
        SELECT
            skill,
            COUNT(*) AS match_count,
            AVG(fit_score)::float AS avg_fit_score
        FROM dedup
        GROUP BY skill
        ORDER BY match_count DESC, skill ASC
        LIMIT %s
    """
    with connection.cursor() as cur:
        cur.execute(sql, [*where_params, MAX_SKILL_ITEMS])
        rows = cur.fetchall()

    items: list[dict[str, Any]] = []
    for skill, match_count_raw, avg_fit_raw in rows:
        match_count = int(match_count_raw or 0)
        avg_fit = round(float(avg_fit_raw), 1) if avg_fit_raw is not None else None
        items.append(
            {
                "skill": str(skill),
                "match_count": match_count,
                "pct_of_high_fit": _safe_pct(match_count, high_fit_count),
                "avg_fit_score": avg_fit,
            }
        )
    return items


def _build_skill_gaps(
    *,
    user_id: int | str,
    cutoff: datetime | None,
    resume_profile_uuid: UUID | None,
) -> dict[str, Any]:
    match_table = connection.ops.quote_name(MatchScore._meta.db_table)
    resume_table = connection.ops.quote_name(ResumeProfile._meta.db_table)
    job_table = connection.ops.quote_name(JobPosting._meta.db_table)
    where_sql, where_params = _build_match_filter_clauses(
        user_id=user_id,
        cutoff=cutoff,
        resume_profile_uuid=resume_profile_uuid,
    )

    count_sql = f"""
        SELECT COUNT(*)
        FROM {match_table} AS ms
        INNER JOIN {resume_table} AS rp ON rp.uuid = ms.resume_profile_id
        INNER JOIN {job_table} AS jp ON jp.uuid = ms.job_posting_id
        WHERE {where_sql}
    """
    with connection.cursor() as cur:
        cur.execute(count_sql, where_params)
        row = cur.fetchone()
        high_fit_count = int(row[0] or 0) if row else 0

    if high_fit_count == 0:
        return {
            "high_fit_match_count": 0,
            "missing_keywords": [],
            "matched_skills": [],
        }

    missing_keywords = _query_top_skills(
        column_key="missing_keywords",
        where_sql=where_sql,
        where_params=where_params,
        high_fit_count=high_fit_count,
        match_table=match_table,
        resume_table=resume_table,
        job_table=job_table,
    )
    matched_skills = _query_top_skills(
        column_key="matched_skills",
        where_sql=where_sql,
        where_params=where_params,
        high_fit_count=high_fit_count,
        match_table=match_table,
        resume_table=resume_table,
        job_table=job_table,
    )

    return {
        "high_fit_match_count": high_fit_count,
        "missing_keywords": missing_keywords,
        "matched_skills": matched_skills,
    }


def build_personal_analytics_payload(
    *,
    user,
    days_param: str = "30",
    resume_profile_uuid: UUID | None = None,
) -> dict[str, Any]:
    days_value = ALLOWED_DAY_WINDOWS[days_param]
    cutoff = (
        timezone.now() - timedelta(days=days_value) if days_value is not None else None
    )

    leads_qs = ApplicationLead.objects.filter(
        user=user,
        job_posting__is_deleted=False,
    )
    if cutoff is not None:
        leads_qs = leads_qs.filter(created_at__gte=cutoff)
    if resume_profile_uuid is not None:
        leads_qs = leads_qs.filter(resume_profile_id=resume_profile_uuid)

    funnel = _build_pipeline_funnel(leads_qs)
    channels = {
        "by_ats_source": _build_channel_performance(
            leads_qs, "job_posting__ats_source"
        ),
        "by_contract_type": _build_channel_performance(
            leads_qs, "job_posting__contract_type"
        ),
    }
    skill_gaps = _build_skill_gaps(
        user_id=user.pk,
        cutoff=cutoff,
        resume_profile_uuid=resume_profile_uuid,
    )

    window_label = f"{days_value}d" if days_value is not None else "all"
    return {
        "window": {
            "days": days_value,
            "label": window_label,
            "resume_profile_uuid": (
                str(resume_profile_uuid) if resume_profile_uuid is not None else None
            ),
        },
        "funnel": funnel,
        "channels": channels,
        "skill_gaps": skill_gaps,
    }
