from datetime import date, datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
import logging
from typing import Any

import httpx
import psycopg

from stream_edge.clients.fx_rates import (
    fetch_latest_usd_fx_rates,
    load_fx_rates_from_postgres,
    persist_fx_rates_postgres,
    publish_fx_rates_redis,
)
from stream_edge.collectors.taxonomy import load_taxonomy
from stream_edge.config import settings
from stream_edge.telemetry import (
    capture_worker_exception,
    configure_sentry,
    flush_sentry,
)
from vektryn_contracts import (
    BUNDLED_FALLBACK_USD_RATES,
    normalize_currency_code,
    normalize_salary_to_annual_usd,
)
from vektryn_contracts.enums import TechCategory

logger = logging.getLogger(__name__)

_SELECT_ACTIVE_NON_USD_SQL = """
    SELECT
        uuid,
        salary_min,
        salary_max,
        salary_currency,
        salary_period,
        salary_annual_min_usd,
        salary_annual_max_usd,
        salary_annual_mid_usd
    FROM jobs_jobposting
    WHERE is_deleted = FALSE
      AND is_active = TRUE
      AND salary_currency <> ''
      AND UPPER(salary_currency) <> 'USD'
      AND (salary_min IS NOT NULL OR salary_max IS NOT NULL)
"""

# Intentionally does NOT bump modified_at so daily FX refreshes never skew
# Spec #22's 90-day modified_at near-duplicate lookback window.
_UPDATE_RENORMALIZED_SALARY_SQL = """
    UPDATE jobs_jobposting
    SET salary_annual_min_usd = %s,
        salary_annual_max_usd = %s,
        salary_annual_mid_usd = %s
    WHERE uuid = %s
"""

_AGGREGATE_TRENDS_SQL = """
    SELECT
        tags.tag,
        COUNT(*) AS mention_count,
        COUNT(DISTINCT NULLIF(LOWER(BTRIM(j.company_name)), '')) AS unique_companies_count,
        PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY j.salary_annual_mid_usd)
            FILTER (WHERE j.salary_annual_mid_usd IS NOT NULL) AS median_annual_usd
    FROM jobs_jobposting j
    CROSS JOIN LATERAL (
        SELECT DISTINCT LOWER(BTRIM(elem)) AS tag
        FROM jsonb_array_elements_text(j.tech_stack) AS elem
        WHERE BTRIM(elem) <> ''
    ) AS tags
    WHERE j.is_deleted = FALSE
      AND DATE(j.created_at AT TIME ZONE 'UTC') = %s
    GROUP BY tags.tag
"""

_UPSERT_TREND_SQL = """
    INSERT INTO analytics_stacktrenddaily
        (bucket_date, tag, category, mention_count, unique_companies_count, median_annual_usd, created_at, modified_at)
    VALUES (%s, %s, %s, %s, %s, %s, NOW(), NOW())
    ON CONFLICT (bucket_date, tag) DO UPDATE SET
        category = EXCLUDED.category,
        mention_count = EXCLUDED.mention_count,
        unique_companies_count = EXCLUDED.unique_companies_count,
        median_annual_usd = EXCLUDED.median_annual_usd,
        modified_at = NOW()
"""

_CENT = Decimal("0.01")


def refresh_daily_fx_rates(
    conn: Any,
    *,
    http_client: httpx.Client | None = None,
) -> dict[str, Decimal]:
    """Refresh daily FX rates (open.er-api -> frankfurter), persist to DB + Redis, or fail open."""
    snapshot = fetch_latest_usd_fx_rates(http_client=http_client)
    if snapshot is not None:
        persisted = persist_fx_rates_postgres(conn, snapshot)
        published = publish_fx_rates_redis(snapshot)
        logger.info(
            "Refreshed %d FX rates from %s (as_of=%s, redis_cached=%s)",
            persisted,
            snapshot.source,
            snapshot.as_of_date,
            published,
        )
        return snapshot.rates

    logger.warning(
        "Daily FX refresh failed across all providers; failing open to existing DB/bundled rates."
    )
    existing = load_fx_rates_from_postgres(conn)
    if existing is not None:
        return existing
    return dict(BUNDLED_FALLBACK_USD_RATES)


def renormalize_active_non_usd_jobs(
    conn: Any,
    usd_rates: dict[str, Decimal],
) -> int:
    """Recompute canonical annual USD bounds for active non-USD postings without touching modified_at."""
    with conn.cursor() as cur:
        cur.execute(_SELECT_ACTIVE_NON_USD_SQL)
        rows = cur.fetchall()

    updates: list[tuple[Decimal | None, Decimal | None, Decimal | None, Any]] = []
    for (
        job_uuid,
        sal_min,
        sal_max,
        sal_currency,
        sal_period,
        cur_min_usd,
        cur_max_usd,
        cur_mid_usd,
    ) in rows:
        normalized = normalize_salary_to_annual_usd(
            sal_min,
            sal_max,
            normalize_currency_code(sal_currency),
            sal_period,
            usd_rates,
        )
        next_min = normalized.annual_min_usd if normalized is not None else None
        next_max = normalized.annual_max_usd if normalized is not None else None
        next_mid = normalized.annual_mid_usd if normalized is not None else None
        if (
            cur_min_usd != next_min
            or cur_max_usd != next_max
            or cur_mid_usd != next_mid
        ):
            updates.append((next_min, next_max, next_mid, job_uuid))

    if updates:
        with conn.cursor() as cur:
            cur.executemany(_UPDATE_RENORMALIZED_SALARY_SQL, updates)
    logger.info(
        "Re-normalized %d/%d active non-USD JobPosting rows",
        len(updates),
        len(rows),
    )
    return len(updates)


def _quantize_median(raw_median: Any) -> Decimal | None:
    if raw_median is None:
        return None
    return Decimal(str(raw_median)).quantize(_CENT, rounding=ROUND_HALF_UP)


def run_daily_rollup(
    target_date: date | None = None,
    *,
    http_client: httpx.Client | None = None,
) -> int:
    bucket = target_date or datetime.now(timezone.utc).date()
    tag_categories = load_taxonomy().tag_to_category

    with psycopg.connect(settings.postgres_dsn) as conn:
        usd_rates = refresh_daily_fx_rates(conn, http_client=http_client)
        renormalize_active_non_usd_jobs(conn, usd_rates)

        with conn.cursor() as cur:
            cur.execute(_AGGREGATE_TRENDS_SQL, (bucket,))
            trend_rows = cur.fetchall()

        with conn.cursor() as cur:
            for tag, mention_count, unique_companies, raw_median in trend_rows:
                cur.execute(
                    _UPSERT_TREND_SQL,
                    (
                        bucket,
                        tag,
                        tag_categories.get(tag, TechCategory.OTHER.value),
                        int(mention_count),
                        int(unique_companies),
                        _quantize_median(raw_median),
                    ),
                )
        conn.commit()

    logger.info(
        "Upserted %d StackTrendDaily rows for bucket_date=%s",
        len(trend_rows),
        bucket,
    )
    return len(trend_rows)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s"
    )
    configure_sentry("vektryn-rollup")
    try:
        run_daily_rollup()
    except Exception as exc:
        capture_worker_exception(exc, worker="vektryn-rollup", topic="rollup")
        raise
    finally:
        flush_sentry(timeout=5.0)


if __name__ == "__main__":
    main()
