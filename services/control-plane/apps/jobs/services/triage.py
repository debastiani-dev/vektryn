from django.db.models import Exists, F, Func, OuterRef, QuerySet, Value
from django.db.models.functions import Lower, Trim
from rest_framework.request import Request

from apps.jobs.models.triage import DismissedJob, MutedCompany
from apps.tracker.models import ApplicationLead

_TRUTHY_VALUES = frozenset({"1", "true", "yes", "on"})
_FALSY_VALUES = frozenset({"0", "false", "no", "off"})


def parse_bool_query_param(raw: str | None, *, default: bool) -> bool:
    if raw is None:
        return default
    cleaned = raw.strip().lower()
    if cleaned in _TRUTHY_VALUES:
        return True
    if cleaned in _FALSY_VALUES:
        return False
    return default


def normalized_company_sql_expr(field_name: str) -> Trim:
    """Emit BTRIM(REGEXP_REPLACE(LOWER(col), '\\s+', ' ', 'g')) for exact Python parity."""
    return Trim(
        Func(
            Lower(F(field_name)),
            Value(r"\s+"),
            Value(" "),
            Value("g"),
            function="REGEXP_REPLACE",
        )
    )


def apply_triage_filters(
    queryset: QuerySet,
    request: Request,
    *,
    job_id_field: str,
    company_field: str,
) -> QuerySet:
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return queryset

    hide_dismissed = parse_bool_query_param(
        request.query_params.get("hide_dismissed"),
        default=True,
    )
    hide_muted = parse_bool_query_param(
        request.query_params.get("hide_muted"),
        default=True,
    )
    untracked_only = parse_bool_query_param(
        request.query_params.get("untracked_only"),
        default=False,
    )

    if hide_dismissed:
        dismissed_subquery = DismissedJob.objects.filter(
            user=user,
            job_posting_id=OuterRef(job_id_field),
        )
        queryset = queryset.filter(~Exists(dismissed_subquery))

    if hide_muted and MutedCompany.objects.filter(user=user).exists():
        muted_subquery = MutedCompany.objects.filter(
            user=user,
            company_name_normalized=OuterRef("_triage_company_norm"),
        )
        queryset = queryset.annotate(
            _triage_company_norm=normalized_company_sql_expr(company_field)
        ).filter(~Exists(muted_subquery))

    if untracked_only:
        tracked_subquery = ApplicationLead.objects.filter(
            user=user,
            job_posting_id=OuterRef(job_id_field),
        )
        queryset = queryset.filter(~Exists(tracked_subquery))

    return queryset
