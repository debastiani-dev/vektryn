from collections import defaultdict
from datetime import date, datetime, timezone
from decimal import Decimal
import logging
from statistics import median

import psycopg

from stream_edge.collectors.taxonomy import load_taxonomy
from stream_edge.config import settings
from vektryn_contracts.enums import TechCategory

logger = logging.getLogger(__name__)

_PERIOD_ANNUAL_MULTIPLIERS: dict[str, Decimal] = {
    "annual": Decimal("1"),
    "monthly": Decimal("12"),
    "hourly": Decimal("2080"),
}

_FX_TO_USD: dict[str, Decimal] = {
    "USD": Decimal("1.00"),
    "EUR": Decimal("1.08"),
    "GBP": Decimal("1.27"),
    "CAD": Decimal("0.72"),
    "BRL": Decimal("0.18"),
}

_FETCH_POSTINGS_SQL = """
    SELECT company_name, tech_stack, salary_min, salary_max, salary_currency, salary_period
    FROM jobs_jobposting
    WHERE is_deleted = FALSE
      AND DATE(COALESCE(posted_at, created_at) AT TIME ZONE 'UTC') = %s
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


def _to_annual_usd(
    salary_min: Decimal | None,
    salary_max: Decimal | None,
    currency: str | None,
    period: str | None,
) -> Decimal | None:
    if salary_min is None and salary_max is None:
        return None
    midpoint = (
        (salary_min + salary_max) / Decimal("2")
        if salary_min is not None and salary_max is not None
        else (salary_min or salary_max)
    )
    fx_rate = _FX_TO_USD.get((currency or "USD").upper())
    multiplier = _PERIOD_ANNUAL_MULTIPLIERS.get((period or "annual").lower())
    if midpoint is None or fx_rate is None or multiplier is None:
        return None
    return (midpoint * fx_rate * multiplier).quantize(Decimal("0.01"))


def _aggregate_rows(
    rows: list[tuple],
) -> tuple[dict[str, int], dict[str, set[str]], dict[str, list[Decimal]]]:
    mentions: dict[str, int] = defaultdict(int)
    companies_by_tag: dict[str, set[str]] = defaultdict(set)
    salaries_by_tag: dict[str, list[Decimal]] = defaultdict(list)

    for company, tech_stack, s_min, s_max, currency, period in rows:
        if not tech_stack:
            continue
        annual_usd = _to_annual_usd(s_min, s_max, currency, period)
        company_key = (company or "").strip().lower()

        for raw_tag in set(tech_stack):
            tag = str(raw_tag).strip().lower()
            if not tag:
                continue
            mentions[tag] += 1
            if company_key:
                companies_by_tag[tag].add(company_key)
            if annual_usd is not None:
                salaries_by_tag[tag].append(annual_usd)

    return mentions, companies_by_tag, salaries_by_tag


def run_daily_rollup(target_date: date | None = None) -> int:
    bucket = target_date or datetime.now(timezone.utc).date()
    tag_categories = load_taxonomy().tag_to_category

    with psycopg.connect(settings.postgres_dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(_FETCH_POSTINGS_SQL, (bucket,))
            rows = cur.fetchall()

        mentions, companies_by_tag, salaries_by_tag = _aggregate_rows(rows)

        with conn.cursor() as cur:
            for tag, count in mentions.items():
                sal_list = salaries_by_tag.get(tag, [])
                med_salary = (
                    Decimal(str(median(sal_list))).quantize(Decimal("0.01"))
                    if sal_list
                    else None
                )
                cur.execute(
                    _UPSERT_TREND_SQL,
                    (
                        bucket,
                        tag,
                        tag_categories.get(tag, TechCategory.OTHER.value),
                        count,
                        len(companies_by_tag[tag]),
                        med_salary,
                    ),
                )
        conn.commit()

    logger.info(
        "Upserted %d StackTrendDaily rows for bucket_date=%s", len(mentions), bucket
    )
    return len(mentions)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s"
    )
    run_daily_rollup()
