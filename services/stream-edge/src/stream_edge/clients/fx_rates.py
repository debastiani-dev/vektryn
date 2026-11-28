from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
import json
import logging
import time
from typing import Any

import httpx
import redis

from stream_edge.config import settings
from vektryn_contracts import (
    BUNDLED_FALLBACK_USD_RATES,
    FX_RATES_REDIS_KEY,
    FX_RATES_REDIS_TTL_SECONDS,
    normalize_currency_code,
)

logger = logging.getLogger(__name__)

PRIMARY_FX_URL = "https://open.er-api.com/v6/latest/USD"
FALLBACK_FX_URL = "https://api.frankfurter.dev/v1/latest?base=USD"
FX_HTTP_TIMEOUT_SECONDS = 10.0
IN_PROCESS_FX_CACHE_TTL_SECONDS = 3600.0

_cached_rates: dict[str, Decimal] | None = None
_cached_rates_expires_at: float = 0.0

_UPSERT_FX_RATE_SQL = """
    INSERT INTO jobs_fxrate (
        currency_code, units_per_usd, source, as_of_date, created_at, modified_at
    )
    VALUES (%s, %s, %s, %s, NOW(), NOW())
    ON CONFLICT (currency_code) DO UPDATE SET
        units_per_usd = EXCLUDED.units_per_usd,
        source = EXCLUDED.source,
        as_of_date = EXCLUDED.as_of_date,
        modified_at = NOW()
"""

_SELECT_FX_RATES_SQL = """
    SELECT currency_code, units_per_usd, source, as_of_date
    FROM jobs_fxrate
"""


@dataclass(frozen=True, slots=True)
class FxRateSnapshot:
    base: str
    as_of_date: str
    source: str
    rates: dict[str, Decimal]


def clear_fx_rate_cache() -> None:
    global _cached_rates, _cached_rates_expires_at
    _cached_rates = None
    _cached_rates_expires_at = 0.0


def _get_sync_redis() -> redis.Redis | None:
    redis_url = (settings.redis_url or "").strip()
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
        logger.debug("Redis unavailable for stream-edge FX cache: %s", exc)
        return None


def _close_redis(client: redis.Redis | None) -> None:
    if client is not None:
        with suppress(Exception):
            client.close()


def _parse_positive_rates(raw_rates: Any) -> dict[str, Decimal]:
    if not isinstance(raw_rates, dict):
        return {}
    parsed: dict[str, Decimal] = {}
    for raw_code, raw_val in raw_rates.items():
        code = normalize_currency_code(str(raw_code))
        if not code:
            continue
        try:
            dec = Decimal(str(raw_val))
        except (InvalidOperation, ValueError):
            continue
        if dec.is_finite() and dec > 0:
            parsed[code] = dec
    if parsed:
        parsed["USD"] = Decimal("1.0")
    return parsed


def _parse_open_er_api_payload(payload: dict[str, Any]) -> FxRateSnapshot | None:
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
    return FxRateSnapshot(
        base="USD", as_of_date=as_of, source="open_er_api", rates=rates
    )


def _parse_frankfurter_payload(payload: dict[str, Any]) -> FxRateSnapshot | None:
    rates = _parse_positive_rates(payload.get("rates"))
    if not rates:
        return None
    as_of = str(payload.get("date") or datetime.now(UTC).date().isoformat())
    return FxRateSnapshot(
        base="USD", as_of_date=as_of, source="frankfurter", rates=rates
    )


def _fetch_json_with_retry(
    url: str,
    *,
    http_client: httpx.Client | None = None,
) -> dict[str, Any] | None:
    for attempt in range(2):
        try:
            if http_client is not None:
                resp = http_client.get(url, timeout=FX_HTTP_TIMEOUT_SECONDS)
            else:
                with httpx.Client(timeout=FX_HTTP_TIMEOUT_SECONDS) as client:
                    resp = client.get(url)
            resp.raise_for_status()
            data = resp.json()
            return data if isinstance(data, dict) else None
        except Exception as exc:
            if attempt == 1:
                logger.warning("FX provider %s failed: %s", url, exc)
    return None


def fetch_latest_usd_fx_rates(
    *,
    http_client: httpx.Client | None = None,
) -> FxRateSnapshot | None:
    """Fetch USD reference rates from open.er-api.com with frankfurter.dev fallback."""
    primary = _fetch_json_with_retry(PRIMARY_FX_URL, http_client=http_client)
    if primary is not None:
        parsed = _parse_open_er_api_payload(primary)
        if parsed is not None:
            return parsed

    fallback = _fetch_json_with_retry(FALLBACK_FX_URL, http_client=http_client)
    if fallback is not None:
        parsed = _parse_frankfurter_payload(fallback)
        if parsed is not None:
            return parsed
    return None


def persist_fx_rates_postgres(conn: Any, snapshot: FxRateSnapshot) -> int:
    as_of = date.fromisoformat(snapshot.as_of_date[:10])
    params = [
        (code, rate, snapshot.source, as_of)
        for code, rate in sorted(snapshot.rates.items())
    ]
    with conn.cursor() as cur:
        cur.executemany(_UPSERT_FX_RATE_SQL, params)
    return len(params)


def publish_fx_rates_redis(snapshot: FxRateSnapshot) -> bool:
    client = _get_sync_redis()
    if client is None:
        return False
    payload = json.dumps(
        {
            "base": snapshot.base,
            "as_of_date": snapshot.as_of_date,
            "source": snapshot.source,
            "rates": {code: str(rate) for code, rate in snapshot.rates.items()},
        }
    )
    try:
        client.set(FX_RATES_REDIS_KEY, payload, ex=FX_RATES_REDIS_TTL_SECONDS)
        return True
    except Exception as exc:
        logger.warning("Failed publishing FX rates to Redis: %s", exc)
        return False
    finally:
        _close_redis(client)


def load_fx_rates_from_postgres(conn: Any) -> dict[str, Decimal] | None:
    if conn is None:
        return None
    try:
        with conn.cursor() as cur:
            cur.execute(_SELECT_FX_RATES_SQL)
            rows = cur.fetchall()
    except Exception as exc:
        logger.debug("Failed loading FX rates from PostgreSQL: %s", exc)
        return None
    if not rows:
        return None
    rates: dict[str, Decimal] = {"USD": Decimal("1.0")}
    for code, units, *_rest in rows:
        norm = normalize_currency_code(code)
        if norm and units is not None and Decimal(str(units)) > 0:
            rates[norm] = Decimal(str(units))
    return rates if len(rates) > 1 else None


def _load_fx_rates_from_redis() -> dict[str, Decimal] | None:
    client = _get_sync_redis()
    if client is None:
        return None
    try:
        raw = client.get(FX_RATES_REDIS_KEY)
        if not isinstance(raw, str) or not raw:
            return None
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            return None
        rates = _parse_positive_rates(parsed.get("rates"))
        return rates or None
    except Exception as exc:
        logger.debug("Failed reading FX rates from Redis: %s", exc)
        return None
    finally:
        _close_redis(client)


def get_cached_usd_rates(conn: Any = None) -> dict[str, Decimal]:
    """3-tier FX lookup: in-process 1h TTL -> Redis -> PostgreSQL -> bundled static fallback."""
    global _cached_rates, _cached_rates_expires_at
    now = time.monotonic()
    if _cached_rates is not None and now < _cached_rates_expires_at:
        return _cached_rates

    rates = _load_fx_rates_from_redis()
    if rates is None:
        rates = load_fx_rates_from_postgres(conn)
    if rates is None:
        rates = dict(BUNDLED_FALLBACK_USD_RATES)

    _cached_rates = rates
    _cached_rates_expires_at = now + IN_PROCESS_FX_CACHE_TTL_SECONDS
    return rates
