from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
import json
import logging
from typing import Any

from django.conf import settings
import httpx
import redis
from rest_framework.exceptions import ValidationError as DRFValidationError

from apps.base.models.user_profile import UserProfile
from apps.jobs.models.fx_rate import FxRate
from vektryn_contracts import (
    BUNDLED_FALLBACK_USD_RATES,
    FX_RATES_REDIS_KEY,
    FX_RATES_REDIS_TTL_SECONDS,
    SalaryPeriod,
    convert_annual_usd_to_currency,
    normalize_currency_code,
    resolve_annualization_multiplier,
)

logger = logging.getLogger(__name__)

PRIMARY_FX_URL = "https://open.er-api.com/v6/latest/USD"
FALLBACK_FX_URL = "https://api.frankfurter.dev/v1/latest?base=USD"
FX_HTTP_TIMEOUT_SECONDS = 10.0

_CENT = Decimal("0.01")
_TWELVE = Decimal("12")
_REQUEST_FX_ATTR = "_vektryn_fx_snapshot"
_REQUEST_CURRENCY_ATTR = "_vektryn_display_currency"


@dataclass(frozen=True, slots=True)
class FxSnapshot:
    base: str
    as_of_date: str
    source: str
    rates: dict[str, Decimal]

    def to_api_dict(self) -> dict[str, Any]:
        return {
            "base": self.base,
            "as_of_date": self.as_of_date,
            "source": self.source,
            "rates": {code: float(rate) for code, rate in sorted(self.rates.items())},
        }


def _get_redis_client() -> redis.Redis | None:
    redis_url = (getattr(settings, "REDIS_URL", "") or "").strip()
    if not redis_url:
        return None
    try:
        return redis.Redis.from_url(
            redis_url,
            decode_responses=True,
            socket_connect_timeout=0.5,
            socket_timeout=0.5,
        )
    except Exception as exc:
        logger.debug("Redis unavailable for FX snapshot cache: %s", exc)
        return None


def _close_redis_safely(client: redis.Redis | None) -> None:
    if client is not None:
        with suppress(Exception):
            client.close()


def _parse_positive_rates(raw_rates: Any) -> dict[str, Decimal]:
    if not isinstance(raw_rates, dict):
        return {}
    parsed: dict[str, Decimal] = {}
    for raw_code, raw_value in raw_rates.items():
        code = normalize_currency_code(str(raw_code))
        if not code:
            continue
        try:
            rate = Decimal(str(raw_value))
        except (InvalidOperation, ValueError):
            continue
        if rate.is_finite() and rate > 0:
            parsed[code] = rate
    if parsed:
        parsed["USD"] = Decimal("1.0")
    return parsed


def _deserialize_fx_snapshot(raw_json: str) -> FxSnapshot | None:
    try:
        payload = json.loads(raw_json)
    except (ValueError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None
    rates = _parse_positive_rates(payload.get("rates"))
    if not rates:
        return None
    return FxSnapshot(
        base=str(payload.get("base") or "USD"),
        as_of_date=str(
            payload.get("as_of_date") or datetime.now(UTC).date().isoformat()
        ),
        source=str(payload.get("source") or "redis_cache"),
        rates=rates,
    )


def _serialize_fx_snapshot(snapshot: FxSnapshot) -> str:
    return json.dumps(
        {
            "base": snapshot.base,
            "as_of_date": snapshot.as_of_date,
            "source": snapshot.source,
            "rates": {code: str(rate) for code, rate in snapshot.rates.items()},
        }
    )


def _cache_snapshot_in_redis(client: redis.Redis | None, snapshot: FxSnapshot) -> None:
    if client is None:
        return
    try:
        client.set(
            FX_RATES_REDIS_KEY,
            _serialize_fx_snapshot(snapshot),
            ex=FX_RATES_REDIS_TTL_SECONDS,
        )
    except Exception as exc:
        logger.debug("Failed caching FX snapshot in Redis: %s", exc)


def _load_snapshot_from_postgres() -> FxSnapshot | None:
    rows = list(
        FxRate.objects.values_list(
            "currency_code", "units_per_usd", "source", "as_of_date"
        )
    )
    if not rows:
        return None
    rates: dict[str, Decimal] = {"USD": Decimal("1.0")}
    latest_date: date | None = None
    source = "postgres"
    for code, units, row_source, row_date in rows:
        norm = normalize_currency_code(code)
        if norm and units is not None and units > 0:
            rates[norm] = Decimal(units)
        if latest_date is None or (row_date is not None and row_date > latest_date):
            latest_date = row_date
            source = row_source or source
    return FxSnapshot(
        base="USD",
        as_of_date=(latest_date or datetime.now(UTC).date()).isoformat(),
        source=source,
        rates=rates,
    )


def _bundled_fallback_snapshot() -> FxSnapshot:
    return FxSnapshot(
        base="USD",
        as_of_date=datetime.now(UTC).date().isoformat(),
        source="static_fallback",
        rates=dict(BUNDLED_FALLBACK_USD_RATES),
    )


def get_fx_snapshot() -> FxSnapshot:
    """Resolve active USD FX rates via 3-tier cache: Redis -> PostgreSQL -> bundled static fallback."""
    client = _get_redis_client()
    try:
        if client is not None:
            try:
                cached_raw = client.get(FX_RATES_REDIS_KEY)
            except Exception as exc:
                logger.debug("Redis read failed for FX snapshot: %s", exc)
                cached_raw = None
            if isinstance(cached_raw, str) and cached_raw:
                cached = _deserialize_fx_snapshot(cached_raw)
                if cached is not None:
                    return cached

        db_snapshot = _load_snapshot_from_postgres()
        if db_snapshot is not None:
            _cache_snapshot_in_redis(client, db_snapshot)
            return db_snapshot
        return _bundled_fallback_snapshot()
    finally:
        _close_redis_safely(client)


def _parse_open_er_api_payload(payload: dict[str, Any]) -> FxSnapshot | None:
    if payload.get("result") != "success":
        return None
    rates = _parse_positive_rates(payload.get("rates"))
    if not rates or "BRL" not in rates:
        return None
    raw_unix = payload.get("time_last_update_unix")
    if isinstance(raw_unix, (int, float)) and raw_unix > 0:
        as_of = datetime.fromtimestamp(raw_unix, tz=UTC).date().isoformat()
    else:
        as_of = datetime.now(UTC).date().isoformat()
    return FxSnapshot(base="USD", as_of_date=as_of, source="open_er_api", rates=rates)


def _parse_frankfurter_payload(payload: dict[str, Any]) -> FxSnapshot | None:
    rates = _parse_positive_rates(payload.get("rates"))
    if not rates:
        return None
    as_of = str(payload.get("date") or datetime.now(UTC).date().isoformat())
    return FxSnapshot(base="USD", as_of_date=as_of, source="frankfurter", rates=rates)


def _fetch_provider_json(url: str) -> dict[str, Any] | None:
    for attempt in range(2):
        try:
            with httpx.Client(timeout=FX_HTTP_TIMEOUT_SECONDS) as http:
                resp = http.get(url)
                resp.raise_for_status()
                data = resp.json()
                return data if isinstance(data, dict) else None
        except Exception as exc:
            if attempt == 1:
                logger.warning("FX provider %s failed: %s", url, exc)
    return None


def refresh_fx_rates_sync() -> FxSnapshot:
    """Fetch live USD FX rates (open.er-api -> frankfurter), persist to DB + Redis, or fail open."""
    snapshot: FxSnapshot | None = None
    primary_data = _fetch_provider_json(PRIMARY_FX_URL)
    if primary_data is not None:
        snapshot = _parse_open_er_api_payload(primary_data)

    if snapshot is None:
        fallback_data = _fetch_provider_json(FALLBACK_FX_URL)
        if fallback_data is not None:
            snapshot = _parse_frankfurter_payload(fallback_data)

    if snapshot is None:
        logger.warning("All external FX providers unavailable; keeping existing rates.")
        return get_fx_snapshot()

    as_of_date = date.fromisoformat(snapshot.as_of_date[:10])
    for code, units in snapshot.rates.items():
        FxRate.objects.update_or_create(
            currency_code=code,
            defaults={
                "units_per_usd": units,
                "source": snapshot.source,
                "as_of_date": as_of_date,
            },
        )

    client = _get_redis_client()
    try:
        _cache_snapshot_in_redis(client, snapshot)
    finally:
        _close_redis_safely(client)
    return snapshot


def get_request_fx_snapshot(request: Any | None) -> FxSnapshot:
    """Resolve and cache FxSnapshot once on the current DRF/Django request object."""
    if request is not None:
        cached = getattr(request, _REQUEST_FX_ATTR, None)
        if isinstance(cached, FxSnapshot):
            return cached
    snapshot = get_fx_snapshot()
    if request is not None:
        setattr(request, _REQUEST_FX_ATTR, snapshot)
    return snapshot


def resolve_user_preferred_currency(user: Any) -> str:
    if user is None or not getattr(user, "is_authenticated", False):
        return "USD"
    try:
        profile = user.profile
    except UserProfile.DoesNotExist:
        return "USD"
    except Exception:
        return "USD"
    code = normalize_currency_code(getattr(profile, "preferred_currency", None))
    return code or "USD"


def _extract_display_currency_override(request: Any | None) -> str:
    if request is None or not hasattr(request, "query_params"):
        return ""
    return (request.query_params.get("display_currency") or "").strip()


def _validate_display_currency_override(
    raw_override: str, fx_snapshot: FxSnapshot
) -> str:
    code = normalize_currency_code(raw_override)
    if not code or code not in fx_snapshot.rates:
        raise DRFValidationError(
            {"display_currency": f"Unsupported currency code: {raw_override!r}."}
        )
    return code


def resolve_display_currency(request: Any | None, fx_snapshot: FxSnapshot) -> str:
    """Resolve and cache target display currency for the request (validating ?display_currency=)."""
    cached = getattr(request, _REQUEST_CURRENCY_ATTR, None)
    if isinstance(cached, str) and cached:
        return cached

    raw_override = _extract_display_currency_override(request)
    if raw_override:
        resolved = _validate_display_currency_override(raw_override, fx_snapshot)
    else:
        user_pref = resolve_user_preferred_currency(getattr(request, "user", None))
        resolved = user_pref if user_pref in fx_snapshot.rates else "USD"

    if request is not None:
        setattr(request, _REQUEST_CURRENCY_ATTR, resolved)
    return resolved


def _quantize_float(value: Decimal | None) -> float | None:
    if value is None:
        return None
    return float(value.quantize(_CENT, rounding=ROUND_HALF_UP))


def _native_period_bounds(
    salary_min: Decimal | None,
    salary_max: Decimal | None,
    period: str | None,
) -> tuple[float | None, float | None, float | None, float | None]:
    """Compute annual and monthly bounds directly from raw salary without USD round-trip drift."""
    multiplier = resolve_annualization_multiplier(period)
    if multiplier is None:
        return None, None, None, None
    annual_min = salary_min * multiplier if salary_min is not None else None
    annual_max = salary_max * multiplier if salary_max is not None else None
    if period == SalaryPeriod.MONTHLY.value:
        monthly_min = salary_min
        monthly_max = salary_max
    else:
        monthly_min = annual_min / _TWELVE if annual_min is not None else None
        monthly_max = annual_max / _TWELVE if annual_max is not None else None
    return (
        _quantize_float(annual_min),
        _quantize_float(annual_max),
        _quantize_float(monthly_min),
        _quantize_float(monthly_max),
    )


def build_salary_normalized_payload(
    job: Any,
    *,
    display_currency: str,
    fx_snapshot: FxSnapshot,
) -> dict[str, Any] | None:
    """Build normalized compensation payload in display_currency with zero USD round-trip drift for native currency."""
    if job is None or getattr(job, "salary_annual_mid_usd", None) is None:
        return None

    job_currency = normalize_currency_code(getattr(job, "salary_currency", ""))
    is_converted = job_currency != display_currency

    if not is_converted:
        annual_min, annual_max, monthly_min, monthly_max = _native_period_bounds(
            getattr(job, "salary_min", None),
            getattr(job, "salary_max", None),
            getattr(job, "salary_period", None),
        )
    else:
        raw_min_usd = getattr(job, "salary_annual_min_usd", None)
        raw_max_usd = getattr(job, "salary_annual_max_usd", None)
        annual_min = _quantize_float(
            convert_annual_usd_to_currency(
                raw_min_usd, display_currency, SalaryPeriod.ANNUAL, fx_snapshot.rates
            )
        )
        annual_max = _quantize_float(
            convert_annual_usd_to_currency(
                raw_max_usd, display_currency, SalaryPeriod.ANNUAL, fx_snapshot.rates
            )
        )
        monthly_min = _quantize_float(
            convert_annual_usd_to_currency(
                raw_min_usd, display_currency, SalaryPeriod.MONTHLY, fx_snapshot.rates
            )
        )
        monthly_max = _quantize_float(
            convert_annual_usd_to_currency(
                raw_max_usd, display_currency, SalaryPeriod.MONTHLY, fx_snapshot.rates
            )
        )

    return {
        "currency": display_currency,
        "annual_min": annual_min,
        "annual_max": annual_max,
        "monthly_min": monthly_min,
        "monthly_max": monthly_max,
        "is_converted": is_converted,
        "fx_as_of_date": fx_snapshot.as_of_date,
    }
