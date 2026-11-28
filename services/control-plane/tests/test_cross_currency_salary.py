from datetime import date
from decimal import Decimal
from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import IntegrityError, transaction
import pytest
from rest_framework.test import APIClient

from apps.base.models.user_profile import PreferredCurrency, UserProfile
from apps.jobs.models.fx_rate import FxRate
from apps.jobs.models.jobs import JobPosting
from apps.jobs.services import fx_rates as fx_service
from apps.jobs.services.fx_rates import FxSnapshot
from apps.jobs.services.hybrid_search import HybridSearchResult
from apps.matching.models.matching import MatchScore
from apps.resumes.models.resumes import ResumeProfile
from apps.tracker.models import ApplicationLead
from vektryn_contracts import EMBEDDING_DIMENSIONS

User = get_user_model()

TEST_FX_RATES = {
    "USD": Decimal("1.0"),
    "BRL": Decimal("5.0"),
    "EUR": Decimal("0.8"),
    "GBP": Decimal("0.8"),
}

TEST_FX_SNAPSHOT = FxSnapshot(
    base="USD",
    as_of_date="2026-11-28",
    source="open_er_api",
    rates=TEST_FX_RATES,
)


def _create_job(
    *,
    external_id: str,
    title: str = "Senior Backend Engineer",
    company_name: str = "Acme",
    salary_min: Decimal | None = None,
    salary_max: Decimal | None = None,
    salary_currency: str = "",
    salary_period: str | None = None,
    salary_annual_min_usd: Decimal | None = None,
    salary_annual_max_usd: Decimal | None = None,
    salary_annual_mid_usd: Decimal | None = None,
) -> JobPosting:
    return JobPosting.objects.create(
        ats_source="greenhouse",
        external_id=external_id,
        content_hash=f"{external_id:0<64}"[:64],
        title=title,
        company_name=company_name,
        apply_url=f"https://boards.greenhouse.io/acme/jobs/{external_id}",
        raw_html_gcs_uri=f"gs://bucket/{external_id}.html",
        description_clean=f"{title} Python PostgreSQL Kafka distributed systems.",
        salary_min=salary_min,
        salary_max=salary_max,
        salary_currency=salary_currency,
        salary_period=salary_period,
        salary_annual_min_usd=salary_annual_min_usd,
        salary_annual_max_usd=salary_annual_max_usd,
        salary_annual_mid_usd=salary_annual_mid_usd,
        embedding=[0.1] * EMBEDDING_DIMENSIONS,
    )


@pytest.mark.django_db
def test_fx_rate_and_job_salary_db_constraints_and_endpoint():
    FxRate.objects.create(
        currency_code="BRL",
        units_per_usd=Decimal("5.25000000"),
        source="open_er_api",
        as_of_date=date(2026, 11, 28),
    )
    with pytest.raises(IntegrityError), transaction.atomic():
        FxRate.objects.create(
            currency_code="BAD",
            units_per_usd=Decimal("0"),
            source="open_er_api",
            as_of_date=date(2026, 11, 28),
        )

    with pytest.raises(IntegrityError), transaction.atomic():
        _create_job(
            external_id="inv-annual",
            salary_annual_min_usd=Decimal("150000.00"),
            salary_annual_max_usd=Decimal("100000.00"),
            salary_annual_mid_usd=Decimal("125000.00"),
        )

    anon = APIClient()
    assert anon.get("/api/v1/system/fx-rates/").status_code == 403

    user = User.objects.create_user(username="fx_user", password="pw")
    authed = APIClient()
    authed.force_authenticate(user=user)
    with patch.object(fx_service, "_get_redis_client", return_value=None):
        res = authed.get("/api/v1/system/fx-rates/")
    assert res.status_code == 200
    body = res.json()
    assert body["base"] == "USD"
    assert body["source"] == "open_er_api"
    assert body["as_of_date"] == "2026-11-28"
    assert body["rates"]["BRL"] == pytest.approx(5.25)
    assert body["rates"]["USD"] == pytest.approx(1.0)


@pytest.mark.django_db
def test_salary_normalized_native_precision_conversion_and_zero_n_plus_1(
    django_assert_num_queries,
):
    user = User.objects.create_user(username="brl_user", password="pw")
    UserProfile.objects.create(user=user, preferred_currency=PreferredCurrency.BRL)
    resume = ResumeProfile.objects.create(
        user=user,
        label="Backend EN",
        raw_text="Python Django Kafka",
        content_hash="r" * 64,
        embedding=[0.1] * EMBEDDING_DIMENSIONS,
    )

    # Native BRL/mo job (with non-exact FX rate 5.73 -> MUST NOT suffer USD round-trip drift!)
    drifting_fx = FxSnapshot(
        base="USD",
        as_of_date="2026-11-28",
        source="open_er_api",
        rates={"USD": Decimal("1.0"), "BRL": Decimal("5.73"), "EUR": Decimal("0.91")},
    )
    brl_job = _create_job(
        external_id="brl-native",
        salary_min=Decimal("20000.00"),
        salary_max=Decimal("25000.00"),
        salary_currency="BRL",
        salary_period="monthly",
        salary_annual_min_usd=Decimal("41884.82"),
        salary_annual_max_usd=Decimal("52356.02"),
        salary_annual_mid_usd=Decimal("47120.42"),
    )
    usd_hr_job = _create_job(
        external_id="usd-hourly",
        salary_min=Decimal("50.00"),
        salary_max=Decimal("60.00"),
        salary_currency="USD",
        salary_period="hourly",
        salary_annual_min_usd=Decimal("104000.00"),
        salary_annual_max_usd=Decimal("124800.00"),
        salary_annual_mid_usd=Decimal("114400.00"),
    )
    outlier_job = _create_job(
        external_id="outlier-raw",
        salary_min=Decimal("150.00"),
        salary_max=Decimal("200.00"),
        salary_currency="USD",
        salary_period="annual",
        salary_annual_min_usd=None,
        salary_annual_max_usd=None,
        salary_annual_mid_usd=None,
    )

    for idx, job in enumerate([brl_job, usd_hr_job, outlier_job]):
        MatchScore.objects.create(
            job_posting=job,
            resume_profile=resume,
            cosine_similarity=0.90 - idx * 0.01,
            fit_score=90 - idx * 5,
            is_routed_winner=True,
        )
    ApplicationLead.objects.create(
        user=user, job_posting=brl_job, resume_profile=resume
    )

    client = APIClient()
    client.force_authenticate(user=user)

    with patch.object(fx_service, "get_fx_snapshot", return_value=drifting_fx):
        # 1. Native BRL job has exact 20000/25000 monthly & 240000/300000 annual with is_converted=False
        res_matches = client.get("/api/v1/matches/")
        assert res_matches.status_code == 200
        by_ext = {
            item["job_posting"]["external_id"]: item["job_posting"]
            for item in res_matches.json()["results"]
        }
        assert by_ext["brl-native"]["salary_normalized"] == {
            "currency": "BRL",
            "annual_min": 240000.0,
            "annual_max": 300000.0,
            "monthly_min": 20000.0,
            "monthly_max": 25000.0,
            "is_converted": False,
            "fx_as_of_date": "2026-11-28",
        }
        # USD hourly job converted into BRL has is_converted=True
        usd_norm = by_ext["usd-hourly"]["salary_normalized"]
        assert usd_norm["currency"] == "BRL"
        assert usd_norm["is_converted"] is True
        assert usd_norm["annual_min"] == pytest.approx(595920.0)
        # Outlier job preserves raw fields and returns salary_normalized=None
        assert by_ext["outlier-raw"]["salary_min"] == "150.00"
        assert by_ext["outlier-raw"]["salary_normalized"] is None

        # 2. ?display_currency=USD override works; same-currency USD/hr -> is_converted=False
        res_usd = client.get("/api/v1/jobs/?display_currency=USD")
        assert res_usd.status_code == 200
        jobs_by_ext = {j["external_id"]: j for j in res_usd.json()["results"]}
        assert jobs_by_ext["usd-hourly"]["salary_normalized"]["is_converted"] is False
        assert jobs_by_ext["usd-hourly"]["salary_normalized"][
            "annual_min"
        ] == pytest.approx(104000.0)
        assert jobs_by_ext["brl-native"]["salary_normalized"]["is_converted"] is True

        # Invalid ?display_currency= returns 400
        assert client.get("/api/v1/jobs/?display_currency=ZZZ").status_code == 400

        # 3. Leads expose flat salary + salary_normalized
        res_leads = client.get("/api/v1/leads/")
        assert res_leads.status_code == 200
        lead_row = res_leads.json()["results"][0]
        assert lead_row["salary_min"] == "20000.00"
        assert lead_row["salary_normalized"]["currency"] == "BRL"
        assert lead_row["salary_normalized"]["is_converted"] is False

        # 4. Zero N+1 verification: query count must stay identical after adding 5 more matched jobs
        with django_assert_num_queries(5):
            r_small = client.get("/api/v1/matches/")
            assert r_small.status_code == 200

        for i in range(5):
            extra = _create_job(
                external_id=f"extra-n1-{i}",
                salary_min=Decimal("100000.00"),
                salary_max=Decimal("130000.00"),
                salary_currency="USD",
                salary_period="annual",
                salary_annual_min_usd=Decimal("100000.00"),
                salary_annual_max_usd=Decimal("130000.00"),
                salary_annual_mid_usd=Decimal("115000.00"),
            )
            MatchScore.objects.create(
                job_posting=extra,
                resume_profile=resume,
                cosine_similarity=0.80,
                fit_score=80,
                is_routed_winner=True,
            )

        with django_assert_num_queries(5):
            r_large = client.get("/api/v1/matches/")
            assert r_large.status_code == 200
            assert len(r_large.json()["results"]) == 8


@pytest.mark.django_db
def test_cross_currency_range_overlap_filtering_sorting_rrf_and_saved_filters():
    user = User.objects.create_user(username="comp_user", password="pw")
    UserProfile.objects.create(user=user, preferred_currency=PreferredCurrency.USD)
    resume = ResumeProfile.objects.create(
        user=user,
        label="Staff Backend",
        raw_text="Python Distributed Systems",
        content_hash="s" * 64,
        embedding=[0.1] * EMBEDDING_DIMENSIONS,
    )

    # 1. USD hourly: $50-$70/hr -> $104k-$145.6k/yr (mid $124.8k)
    j_usd_hr = _create_job(
        external_id="usd-hr",
        title="Python Streaming Engineer",
        salary_min=Decimal("50"),
        salary_max=Decimal("70"),
        salary_currency="USD",
        salary_period="hourly",
        salary_annual_min_usd=Decimal("104000.00"),
        salary_annual_max_usd=Decimal("145600.00"),
        salary_annual_mid_usd=Decimal("124800.00"),
    )
    # 2. BRL monthly: R$20k-R$25k/mo @ 5.0 -> $48k-$60k/yr (mid $54k)
    j_brl_mo = _create_job(
        external_id="brl-mo",
        title="Python Backend Brasil",
        salary_min=Decimal("20000"),
        salary_max=Decimal("25000"),
        salary_currency="BRL",
        salary_period="monthly",
        salary_annual_min_usd=Decimal("48000.00"),
        salary_annual_max_usd=Decimal("60000.00"),
        salary_annual_mid_usd=Decimal("54000.00"),
    )
    # 3. EUR annual: €80k-€112k/yr @ 0.8 -> $100k-$140k/yr (mid $120k)
    j_eur_yr = _create_job(
        external_id="eur-yr",
        title="Python Platform Europe",
        salary_min=Decimal("80000"),
        salary_max=Decimal("112000"),
        salary_currency="EUR",
        salary_period="annual",
        salary_annual_min_usd=Decimal("100000.00"),
        salary_annual_max_usd=Decimal("140000.00"),
        salary_annual_mid_usd=Decimal("120000.00"),
    )
    # 4. Undisclosed salary
    j_none = _create_job(external_id="undisclosed", title="Python No Salary")

    for job in (j_usd_hr, j_brl_mo, j_eur_yr, j_none):
        MatchScore.objects.create(
            job_posting=job,
            resume_profile=resume,
            cosine_similarity=0.85,
            fit_score=85,
            is_routed_winner=True,
        )

    client = APIClient()
    client.force_authenticate(user=user)

    with patch.object(fx_service, "get_fx_snapshot", return_value=TEST_FX_SNAPSHOT):
        # Range overlap: min_salary=R$ 50,000/mo BRL (= $120,000/yr USD)
        # Matches j_usd_hr (max $145.6k >= $120k) and j_eur_yr (max $140k >= $120k), excludes j_brl_mo & j_none
        r_floor = client.get(
            "/api/v1/matches/?min_salary=50000&salary_currency=BRL&salary_period=monthly"
        )
        assert r_floor.status_code == 200
        assert {m["job_posting"]["external_id"] for m in r_floor.json()["results"]} == {
            "usd-hr",
            "eur-yr",
        }

        # Ceiling: max_salary=70000 USD annual -> only j_brl_mo (min $48k <= $70k)
        r_ceil = client.get(
            "/api/v1/jobs/?max_salary=70000&salary_currency=USD&salary_period=annual"
        )
        assert r_ceil.status_code == 200
        assert [j["external_id"] for j in r_ceil.json()["results"]] == ["brl-mo"]

        # disclosed_salary_only=true excludes j_none
        r_disc = client.get("/api/v1/matches/?disclosed_salary_only=true")
        assert r_disc.status_code == 200
        assert len(r_disc.json()["results"]) == 3

        # Invalid params -> 400
        assert client.get("/api/v1/matches/?min_salary=-10").status_code == 400
        assert (
            client.get("/api/v1/matches/?min_salary=100&max_salary=50").status_code
            == 400
        )
        assert client.get("/api/v1/matches/?salary_currency=NOPE").status_code == 400
        assert client.get("/api/v1/matches/?salary_period=weekly").status_code == 400

        # NULLS LAST sorting on /jobs/ and /matches/ (including sort_by=salary alias)
        r_job_sort = client.get("/api/v1/jobs/?ordering=-salary_annual_mid_usd")
        assert [j["external_id"] for j in r_job_sort.json()["results"]] == [
            "usd-hr",
            "eur-yr",
            "brl-mo",
            "undisclosed",
        ]

        r_match_sort = client.get("/api/v1/matches/?sort_by=salary")
        assert [
            m["job_posting"]["external_id"] for m in r_match_sort.json()["results"]
        ] == [
            "usd-hr",
            "eur-yr",
            "brl-mo",
            "undisclosed",
        ]

        # Hybrid RRF + sort_by=salary orders RRF candidates by salary_annual_mid_usd DESC NULLS LAST
        rrf_result = HybridSearchResult(
            rrf_scores={
                j_none.uuid: 0.99,
                j_brl_mo.uuid: 0.80,
                j_eur_yr.uuid: 0.50,
            },
            search_mode="hybrid",
        )
        with patch(
            "apps.matching.views.matching.execute_hybrid_search",
            return_value=rrf_result,
        ):
            r_rrf_salary = client.get("/api/v1/matches/?search=python&sort_by=salary")
        assert r_rrf_salary.status_code == 200
        assert [
            m["job_posting"]["external_id"] for m in r_rrf_salary.json()["results"]
        ] == ["eur-yr", "brl-mo", "undisclosed"]

        # SavedFilter round-trip + 400 validation
        create_ok = client.post(
            "/api/v1/jobs/filters/",
            {
                "name": "High Comp BRL",
                "query_params": {
                    "min_salary": 20000,
                    "max_salary": 40000,
                    "salary_currency": "brl",
                    "salary_period": "monthly",
                    "disclosed_salary_only": True,
                    "sort_by": "salary",
                },
            },
            format="json",
        )
        assert create_ok.status_code == 201
        assert create_ok.json()["query_params"]["salary_currency"] == "BRL"
        assert create_ok.json()["query_params"]["disclosed_salary_only"] is True

        create_bad = client.post(
            "/api/v1/jobs/filters/",
            {
                "name": "Bad Comp",
                "query_params": {"min_salary": 50000, "max_salary": 10000},
            },
            format="json",
        )
        assert create_bad.status_code == 400


@pytest.mark.django_db
def test_backfill_normalized_salaries_command_idempotent_dry_run_and_refresh_fx():
    j_ok = _create_job(
        external_id="bf-brl",
        salary_min=Decimal("20000"),
        salary_max=Decimal("25000"),
        salary_currency="R$",
        salary_period="monthly",
    )
    j_outlier = _create_job(
        external_id="bf-outlier",
        salary_min=Decimal("100"),
        salary_max=Decimal("200"),
        salary_currency="USD",
        salary_period="annual",
    )

    # Dry run writes nothing
    out_dry = StringIO()
    with patch(
        "apps.base.management.commands.backfill_normalized_salaries.get_fx_snapshot",
        return_value=TEST_FX_SNAPSHOT,
    ):
        call_command("backfill_normalized_salaries", "--dry-run", stdout=out_dry)
    assert "[DRY-RUN]" in out_dry.getvalue()
    j_ok.refresh_from_db()
    assert j_ok.salary_annual_mid_usd is None

    # Apply with --refresh-fx populates normalized columns and normalizes R$ -> BRL
    out_apply = StringIO()
    with patch(
        "apps.base.management.commands.backfill_normalized_salaries.refresh_fx_rates_sync",
        return_value=TEST_FX_SNAPSHOT,
    ) as mock_refresh:
        call_command("backfill_normalized_salaries", "--refresh-fx", stdout=out_apply)
    mock_refresh.assert_called_once()
    j_ok.refresh_from_db()
    j_outlier.refresh_from_db()
    assert j_ok.salary_currency == "BRL"
    assert j_ok.salary_annual_min_usd == Decimal("48000.00")
    assert j_ok.salary_annual_max_usd == Decimal("60000.00")
    assert j_ok.salary_annual_mid_usd == Decimal("54000.00")
    assert j_outlier.salary_annual_mid_usd is None

    # Second run is a clean idempotent no-op (updated_jobs=0)
    out_second = StringIO()
    with patch(
        "apps.base.management.commands.backfill_normalized_salaries.get_fx_snapshot",
        return_value=TEST_FX_SNAPSHOT,
    ):
        call_command("backfill_normalized_salaries", stdout=out_second)
    assert "updated_jobs=0" in out_second.getvalue()
