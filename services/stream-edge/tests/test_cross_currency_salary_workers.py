"""Tests for Spec #23 cross-currency FX refresh, rollup re-normalization, and matcher ingestion."""

from datetime import UTC, date, datetime
from decimal import Decimal
import json
from unittest.mock import MagicMock, patch
import uuid

import httpx

from stream_edge.clients import fx_rates as fx_client
from stream_edge.workers import matcher, rollup
from vektryn_contracts import (
    BUNDLED_FALLBACK_USD_RATES,
    EMBEDDING_DIMENSIONS,
    FX_RATES_REDIS_KEY,
    ATSSource,
    ContractType,
    JobEnrichedEvent,
    RegionEligibility,
    SalaryPeriod,
    SeniorityLevel,
    WorkMode,
    compute_description_fingerprint,
    compute_job_content_hash,
    normalize_company_for_dedup,
    normalize_title_for_dedup,
)

LONG_DESC = (
    "We are hiring a Senior Backend Python Engineer to build event-driven "
    "microservices with Django, PostgreSQL, pgvector, Redis, and Kafka. "
    "You will lead technical design reviews and own reliability at scale."
)


def test_fx_fetch_primary_fallback_and_fail_open() -> None:
    # 1. Primary open.er-api.com succeeds
    def _primary_handler(request: httpx.Request) -> httpx.Response:
        if "open.er-api.com" in str(request.url):
            return httpx.Response(
                200,
                json={
                    "result": "success",
                    "time_last_update_unix": 1795824000,
                    "rates": {"USD": 1, "BRL": 5.5, "EUR": 0.9, "BAD": -1},
                },
            )
        return httpx.Response(500)

    with httpx.Client(transport=httpx.MockTransport(_primary_handler)) as client:
        snap = fx_client.fetch_latest_usd_fx_rates(http_client=client)
    assert snap is not None
    assert snap.source == "open_er_api"
    assert snap.rates["BRL"] == Decimal("5.5")
    assert snap.rates["USD"] == Decimal("1.0")
    assert "BAD" not in snap.rates

    # 2. Primary fails -> falls back to frankfurter.dev
    def _fallback_handler(request: httpx.Request) -> httpx.Response:
        if "open.er-api.com" in str(request.url):
            return httpx.Response(503)
        return httpx.Response(
            200,
            json={
                "base": "USD",
                "date": "2026-11-28",
                "rates": {"BRL": 5.6, "EUR": 0.92, "GBP": 0.78},
            },
        )

    with httpx.Client(transport=httpx.MockTransport(_fallback_handler)) as client:
        snap_fb = fx_client.fetch_latest_usd_fx_rates(http_client=client)
    assert snap_fb is not None
    assert snap_fb.source == "frankfurter"
    assert snap_fb.as_of_date == "2026-11-28"
    assert snap_fb.rates["BRL"] == Decimal("5.6")
    assert snap_fb.rates["USD"] == Decimal("1.0")

    # 3. Both providers fail -> returns None (fail-open handled by rollup)
    with httpx.Client(
        transport=httpx.MockTransport(lambda _r: httpx.Response(503))
    ) as client:
        assert fx_client.fetch_latest_usd_fx_rates(http_client=client) is None


def test_rollup_refreshes_fx_renormalizes_without_bumping_modified_at_and_uses_mid_usd(
    monkeypatch,
) -> None:
    job_brl_uuid = uuid.uuid4()
    executed: list[tuple[str, object]] = []
    redis_sets: list[tuple[str, str, int]] = []

    class _FakeRedis:
        def set(self, key: str, value: str, ex: int = 0) -> None:
            redis_sets.append((key, value, ex))

        def close(self) -> None:
            # In-memory double: nothing to close.
            pass

    class _FakeCur:
        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return False

        def execute(self, sql, params=None):
            executed.append((sql, params))
            self._sql = sql

        def executemany(self, sql, seq_params):
            executed.append((sql, list(seq_params)))

        def fetchall(self):
            if "UPPER(salary_currency) <> 'USD'" in self._sql:
                return [
                    (
                        job_brl_uuid,
                        Decimal("20000"),
                        Decimal("25000"),
                        "BRL",
                        "monthly",
                        Decimal("40000.00"),
                        Decimal("50000.00"),
                        Decimal("45000.00"),
                    )
                ]
            if "PERCENTILE_CONT(0.5)" in self._sql:
                return [("python", 4, 3, 54000.0)]
            return []

    class _FakeConn:
        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return False

        def cursor(self):
            return _FakeCur()

        def commit(self):
            # In-memory double: no backing database transaction.
            pass

    def _primary_handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "result": "success",
                "time_last_update_unix": 1795824000,
                "rates": {"USD": 1, "BRL": 5.0, "EUR": 0.8},
            },
        )

    monkeypatch.setattr(rollup.psycopg, "connect", lambda *_a, **_kw: _FakeConn())
    monkeypatch.setattr(fx_client, "_get_sync_redis", lambda: _FakeRedis())

    with httpx.Client(transport=httpx.MockTransport(_primary_handler)) as http_client:
        upserted = rollup.run_daily_rollup(
            target_date=date(2026, 11, 28),
            http_client=http_client,
        )

    assert upserted == 1
    assert len(redis_sets) == 1
    assert redis_sets[0][0] == FX_RATES_REDIS_KEY
    cached_payload = json.loads(redis_sets[0][1])
    assert cached_payload["rates"]["BRL"] == "5.0"

    # Re-normalization SQL MUST NOT touch modified_at (Refinement #4)
    renorm_sql, renorm_params = next(
        (s, p) for s, p in executed if "SET salary_annual_min_usd = %s" in s
    )
    assert "modified_at" not in renorm_sql
    assert renorm_params == [
        (
            Decimal("48000.00"),
            Decimal("60000.00"),
            Decimal("54000.00"),
            job_brl_uuid,
        )
    ]

    # Trend upsert received median from PERCENTILE_CONT(0.5) over salary_annual_mid_usd
    trend_call = next(
        p for s, p in executed if "INSERT INTO analytics_stacktrenddaily" in s
    )
    assert trend_call[1] == "python"
    assert trend_call[5] == Decimal("54000.00")


def test_rollup_fails_open_when_both_fx_providers_fail() -> None:
    class _DbFallbackCur:
        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return False

        def execute(self, sql, params=None):
            self._sql = sql

        def fetchall(self):
            if "FROM jobs_fxrate" in self._sql:
                return [("BRL", Decimal("5.40"), "open_er_api", date(2026, 11, 27))]
            return []

    class _DbFallbackConn:
        def cursor(self):
            return _DbFallbackCur()

    with httpx.Client(
        transport=httpx.MockTransport(lambda _r: httpx.Response(503))
    ) as client:
        rates = rollup.refresh_daily_fx_rates(_DbFallbackConn(), http_client=client)
    assert rates["BRL"] == Decimal("5.40")

    # Empty DB falls back cleanly to bundled static rates
    class _EmptyConn:
        def cursor(self):
            cur = MagicMock()
            cur.__enter__.return_value = cur
            cur.fetchall.return_value = []
            return cur

    with httpx.Client(
        transport=httpx.MockTransport(lambda _r: httpx.Response(503))
    ) as client:
        bundled = rollup.refresh_daily_fx_rates(_EmptyConn(), http_client=client)
    assert bundled["BRL"] == BUNDLED_FALLBACK_USD_RATES["BRL"]


def test_matcher_persists_normalized_annual_usd_on_upsert_and_stage0_backfill() -> None:
    fx_client.clear_fx_rate_cache()
    now = datetime(2026, 11, 28, 12, 0, tzinfo=UTC)
    new_uuid = uuid.uuid4()
    executed_insert: list[tuple[str, tuple | None]] = []

    class _InsertCur:
        def execute(self, sql, params=None):
            executed_insert.append((sql, params))
            self._sql = sql

        def fetchone(self):
            if "INSERT INTO jobs_jobposting (" in self._sql:
                return (new_uuid,)
            return None

        def fetchall(self):
            return []

    enriched = JobEnrichedEvent(
        ats_source=ATSSource.GREENHOUSE,
        external_id="gh-brl-1",
        content_hash=compute_job_content_hash(
            ATSSource.GREENHOUSE,
            "Senior Backend Python Engineer",
            "Acme",
            LONG_DESC,
        ),
        title="Senior Backend Python Engineer",
        company_name="Acme",
        apply_url="https://boards.greenhouse.io/acme/jobs/1",
        raw_html_gcs_uri="gs://bucket/1.html",
        location_raw="Remote - Brazil",
        description_clean=LONG_DESC,
        seniority=SeniorityLevel.SENIOR,
        contract_type=ContractType.PJ,
        work_mode=WorkMode.REMOTE,
        language="pt",
        region_eligibility=[RegionEligibility.BRAZIL],
        salary_min=Decimal("20000"),
        salary_max=Decimal("25000"),
        salary_currency="BRL",
        salary_period=SalaryPeriod.MONTHLY,
        tech_stack=["python", "django"],
        embedding=[0.1] * EMBEDDING_DIMENSIONS,
    )

    with patch.object(
        matcher,
        "get_cached_usd_rates",
        return_value={"USD": Decimal("1.0"), "BRL": Decimal("5.0")},
    ):
        res = matcher._upsert_or_merge_canonical_job(_InsertCur(), enriched, now)

    assert res.uuid == new_uuid
    ins_sql, ins_params = next(
        (s, p) for s, p in executed_insert if "INSERT INTO jobs_jobposting (" in s
    )
    assert "salary_annual_min_usd" in ins_sql
    assert Decimal("48000.00") in ins_params
    assert Decimal("60000.00") in ins_params
    assert Decimal("54000.00") in ins_params

    # Stage 0 non-destructive salary backfill (canonical has no salary, incoming has max-only EUR/yr)
    canonical_uuid = uuid.uuid4()
    fp, _ = compute_description_fingerprint(LONG_DESC)
    canonical_row = (
        canonical_uuid,
        "remotive",
        "rem-1",
        "Senior Backend Python Engineer",
        "Acme",
        "https://remotive.com/jobs/1",
        LONG_DESC,
        "senior",
        "pj",
        "remote",
        "en",
        ["worldwide"],
        None,
        None,
        "",
        None,
        ["python"],
        True,
        0,
        None,
        now,
        normalize_company_for_dedup("Acme"),
        normalize_title_for_dedup("Senior Backend Python Engineer"),
        fp,
    )
    executed_merge: list[tuple[str, tuple | None]] = []

    class _MergeCur:
        def execute(self, sql, params=None):
            executed_merge.append((sql, params))
            self._sql = sql

        def fetchone(self):
            if "SELECT uuid, job_posting_id, is_primary" in self._sql:
                return None
            if "SELECT uuid, ats_source, is_active" in self._sql:
                return (uuid.uuid4(), "remotive", True)
            return None

    incoming_max_only = enriched.model_copy(
        update={
            "external_id": "gh-eur-max",
            "salary_min": None,
            "salary_max": Decimal("80000"),
            "salary_currency": "EUR",
            "salary_period": SalaryPeriod.ANNUAL,
        }
    )
    with patch.object(
        matcher,
        "get_cached_usd_rates",
        return_value={"USD": Decimal("1.0"), "EUR": Decimal("0.8")},
    ):
        matcher._merge_into_canonical_job(
            _MergeCur(),
            canonical_row=canonical_row,
            enriched=incoming_max_only,
            company_norm=normalize_company_for_dedup("Acme"),
            title_norm=normalize_title_for_dedup("Senior Backend Python Engineer"),
            desc_fp=fp,
            now=now,
        )

    upd_sql, upd_params = next(
        (s, p) for s, p in executed_merge if "UPDATE jobs_jobposting\n" in s
    )
    assert "salary_annual_mid_usd = %s" in upd_sql
    assert Decimal("100000.00") in upd_params
