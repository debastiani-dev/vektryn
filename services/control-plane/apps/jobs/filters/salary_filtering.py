from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from django.db.models import F, Q
from django.db.models.functions import Coalesce
from rest_framework.exceptions import ValidationError as DRFValidationError
from rest_framework.filters import OrderingFilter

from apps.jobs.services.fx_rates import (
    FxSnapshot,
    resolve_user_preferred_currency,
)
from vektryn_contracts import (
    SalaryPeriod,
    convert_salary_bound_to_annual_usd,
    normalize_currency_code,
    resolve_annualization_multiplier,
)

_TRUTHY_STRINGS = frozenset({"1", "true", "yes"})
_FALSY_STRINGS = frozenset({"0", "false", "no"})


@dataclass(frozen=True, slots=True)
class SalaryFilterBounds:
    min_annual_usd: Decimal | None
    max_annual_usd: Decimal | None
    disclosed_salary_only: bool

    @property
    def is_active(self) -> bool:
        return (
            self.min_annual_usd is not None
            or self.max_annual_usd is not None
            or self.disclosed_salary_only
        )


def _parse_non_negative_decimal(raw: Any, field_name: str) -> Decimal | None:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    try:
        value = Decimal(text)
    except InvalidOperation as exc:
        raise DRFValidationError({field_name: "Must be a valid number."}) from exc
    if not value.is_finite() or value < 0:
        raise DRFValidationError({field_name: "Must be greater than or equal to 0."})
    return value


def _parse_bool_flag(raw: Any, field_name: str) -> bool:
    if raw is None:
        return False
    if isinstance(raw, bool):
        return raw
    text = str(raw).strip().lower()
    if not text:
        return False
    if text in _TRUTHY_STRINGS:
        return True
    if text in _FALSY_STRINGS:
        return False
    raise DRFValidationError({field_name: "Must be a boolean ('true' or 'false')."})


def _parse_filter_currency(
    raw_currency: Any,
    *,
    user: Any,
    fx_snapshot: FxSnapshot,
) -> str:
    text = str(raw_currency).strip() if raw_currency is not None else ""
    if text:
        code = normalize_currency_code(text)
        if not code or code not in fx_snapshot.rates:
            raise DRFValidationError(
                {"salary_currency": f"Unsupported currency code: {text!r}."}
            )
        return code
    preferred = resolve_user_preferred_currency(user)
    return preferred if preferred in fx_snapshot.rates else "USD"


def _parse_filter_period(raw_period: Any) -> SalaryPeriod:
    text = str(raw_period).strip().lower() if raw_period is not None else ""
    if not text:
        return SalaryPeriod.ANNUAL
    if resolve_annualization_multiplier(text) is None:
        raise DRFValidationError(
            {
                "salary_period": (
                    f"Invalid salary_period {text!r}. Expected one of: hourly, monthly, annual."
                )
            }
        )
    return SalaryPeriod(text)


def parse_and_validate_salary_filter_params(
    query_params: Any,
    *,
    user: Any,
    fx_snapshot: FxSnapshot,
) -> SalaryFilterBounds:
    """Validate cross-currency salary query parameters and convert bounds to annual USD."""
    raw_min = query_params.get("min_salary")
    raw_max = query_params.get("max_salary")
    raw_currency = query_params.get("salary_currency")
    raw_period = query_params.get("salary_period")
    raw_disclosed = query_params.get("disclosed_salary_only")

    min_val = _parse_non_negative_decimal(raw_min, "min_salary")
    max_val = _parse_non_negative_decimal(raw_max, "max_salary")
    disclosed_only = _parse_bool_flag(raw_disclosed, "disclosed_salary_only")

    if min_val is not None and max_val is not None and max_val < min_val:
        raise DRFValidationError(
            {"max_salary": "max_salary must be greater than or equal to min_salary."}
        )

    # Always validate currency/period when explicitly provided, even without min/max
    has_explicit_currency = raw_currency is not None and str(raw_currency).strip() != ""
    has_explicit_period = raw_period is not None and str(raw_period).strip() != ""
    if (
        min_val is None
        and max_val is None
        and not has_explicit_currency
        and not has_explicit_period
    ):
        return SalaryFilterBounds(
            min_annual_usd=None,
            max_annual_usd=None,
            disclosed_salary_only=disclosed_only,
        )

    currency = _parse_filter_currency(raw_currency, user=user, fx_snapshot=fx_snapshot)
    period = _parse_filter_period(raw_period)

    min_usd = (
        convert_salary_bound_to_annual_usd(min_val, currency, period, fx_snapshot.rates)
        if min_val is not None
        else None
    )
    max_usd = (
        convert_salary_bound_to_annual_usd(max_val, currency, period, fx_snapshot.rates)
        if max_val is not None
        else None
    )
    return SalaryFilterBounds(
        min_annual_usd=min_usd,
        max_annual_usd=max_usd,
        disclosed_salary_only=disclosed_only,
    )


def apply_salary_filters(
    queryset,
    bounds: SalaryFilterBounds,
    *,
    field_prefix: str = "",
):
    """Apply range-overlap filtering against canonical annual USD columns."""
    if not bounds.is_active:
        return queryset

    min_col = f"{field_prefix}salary_annual_min_usd"
    max_col = f"{field_prefix}salary_annual_max_usd"
    mid_col = f"{field_prefix}salary_annual_mid_usd"

    queryset = queryset.filter(**{f"{mid_col}__isnull": False})

    annotations: dict[str, Any] = {}
    conditions = Q()
    if bounds.min_annual_usd is not None:
        annotations["_salary_eff_max_usd"] = Coalesce(F(max_col), F(min_col))
        conditions &= Q(_salary_eff_max_usd__gte=bounds.min_annual_usd)
    if bounds.max_annual_usd is not None:
        annotations["_salary_eff_min_usd"] = Coalesce(F(min_col), F(max_col))
        conditions &= Q(_salary_eff_min_usd__lte=bounds.max_annual_usd)

    if annotations:
        queryset = queryset.annotate(**annotations).filter(conditions)
    return queryset


class NullsLastOrderingFilter(OrderingFilter):
    """Apply NULLS LAST for nullable ordering fields so undisclosed/unscored rows sort to the bottom."""

    nulls_last_fields: frozenset[str] = frozenset(
        {
            "fit_score",
            "posted_at",
            "salary_max",
            "salary_annual_mid_usd",
            "salary_annual_max_usd",
            "job_posting__posted_at",
            "job_posting__salary_annual_mid_usd",
            "job_posting__salary_annual_max_usd",
        }
    )

    def filter_queryset(self, request, queryset, view):
        ordering = self.get_ordering(request, queryset, view)
        if not ordering:
            return queryset

        expressions = []
        for term in ordering:
            descending = term.startswith("-")
            field_name = term.lstrip("-")
            if field_name in self.nulls_last_fields:
                expr = F(field_name)
                expressions.append(
                    expr.desc(nulls_last=True)
                    if descending
                    else expr.asc(nulls_last=True)
                )
            else:
                expressions.append(term)
        return queryset.order_by(*expressions)
