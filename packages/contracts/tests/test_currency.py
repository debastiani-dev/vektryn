from decimal import Decimal

import pytest

from vektryn_contracts import (
    ANNUALIZATION_MULTIPLIERS,
    BUNDLED_FALLBACK_USD_RATES,
    FX_RATES_REDIS_KEY,
    MAX_PLAUSIBLE_ANNUAL_USD,
    MIN_PLAUSIBLE_ANNUAL_USD,
    NormalizedAnnualUsd,
    SalaryPeriod,
    convert_annual_usd_to_currency,
    convert_salary_bound_to_annual_usd,
    normalize_currency_code,
    normalize_salary_to_annual_usd,
    resolve_annualization_multiplier,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("$", "USD"),
        ("US$", "USD"),
        ("u$s", "USD"),
        (" usd ", "USD"),
        ("R$", "BRL"),
        ("brl", "BRL"),
        ("reais", "BRL"),
        ("€", "EUR"),
        ("EUR", "EUR"),
        ("£", "GBP"),
        ("GBP", "GBP"),
        ("C$", "CAD"),
        ("CAD", "CAD"),
        ("A$", "AUD"),
        ("AUD", "AUD"),
        ("MXN", "MXN"),
        ("COP", "COP"),
        ("CLP", "CLP"),
        ("ARS", "ARS"),
        ("CHF", "CHF"),
        ("PLN", "PLN"),
        ("SEK", "SEK"),
        ("NOK", "NOK"),
        ("DKK", "DKK"),
        ("INR", "INR"),
        ("JPY", "JPY"),
        ("SGD", "SGD"),
        ("NZD", "NZD"),
        ("ILS", "ILS"),
        ("CZK", "CZK"),
        ("", ""),
        ("   ", ""),
        (None, ""),
        ("unknown", ""),
        ("N/A", ""),
        ("TBD", ""),
        ("XYZ", ""),
    ],
)
def test_normalize_currency_code(raw: str | None, expected: str) -> None:
    assert normalize_currency_code(raw) == expected


def test_annualization_multipliers_and_period_resolution() -> None:
    assert ANNUALIZATION_MULTIPLIERS[SalaryPeriod.ANNUAL] == Decimal("1")
    assert ANNUALIZATION_MULTIPLIERS[SalaryPeriod.MONTHLY] == Decimal("12")
    assert ANNUALIZATION_MULTIPLIERS[SalaryPeriod.HOURLY] == Decimal("2080")
    assert resolve_annualization_multiplier("annual") == Decimal("1")
    assert resolve_annualization_multiplier("MONTHLY") == Decimal("12")
    assert resolve_annualization_multiplier(SalaryPeriod.HOURLY) == Decimal("2080")
    assert resolve_annualization_multiplier(None) is None
    assert resolve_annualization_multiplier("weekly") is None
    assert FX_RATES_REDIS_KEY == "vektryn:fx:rates:usd"


def test_normalize_salary_to_annual_usd_across_currencies_and_periods() -> None:
    rates = {
        "USD": Decimal("1.0"),
        "BRL": Decimal("5.0"),
        "EUR": Decimal("0.8"),
        "GBP": Decimal("0.8"),
    }

    # USD hourly: $50-$70/hr * 2080 = $104,000-$145,600/yr (mid $124,800)
    usd_hr = normalize_salary_to_annual_usd(50, 70, "$", SalaryPeriod.HOURLY, rates)
    assert usd_hr == NormalizedAnnualUsd(
        annual_min_usd=Decimal("104000.00"),
        annual_max_usd=Decimal("145600.00"),
        annual_mid_usd=Decimal("124800.00"),
    )

    # BRL monthly: R$ 20,000 - R$ 25,000/mo * 12 / 5.0 = $48,000 - $60,000/yr (mid $54,000)
    brl_mo = normalize_salary_to_annual_usd(
        Decimal("20000"), Decimal("25000"), "R$", "monthly", rates
    )
    assert brl_mo == NormalizedAnnualUsd(
        annual_min_usd=Decimal("48000.00"),
        annual_max_usd=Decimal("60000.00"),
        annual_mid_usd=Decimal("54000.00"),
    )

    # EUR annual: €80,000 / 0.8 = $100,000 single-sided min
    eur_yr = normalize_salary_to_annual_usd(80000, None, "€", "annual", rates)
    assert eur_yr == NormalizedAnnualUsd(
        annual_min_usd=Decimal("100000.00"),
        annual_max_usd=None,
        annual_mid_usd=Decimal("100000.00"),
    )

    # Single-sided max only
    gbp_max = normalize_salary_to_annual_usd(None, 80000, "£", "annual", rates)
    assert gbp_max == NormalizedAnnualUsd(
        annual_min_usd=None,
        annual_max_usd=Decimal("100000.00"),
        annual_mid_usd=Decimal("100000.00"),
    )


def test_normalize_salary_rejects_invalid_inverted_zero_and_outliers() -> None:
    rates = BUNDLED_FALLBACK_USD_RATES

    # Missing period or unknown currency
    assert normalize_salary_to_annual_usd(100000, 120000, "USD", None, rates) is None
    assert (
        normalize_salary_to_annual_usd(100000, 120000, "USD", "unknown", rates) is None
    )
    assert normalize_salary_to_annual_usd(100000, 120000, "", "annual", rates) is None
    assert (
        normalize_salary_to_annual_usd(100000, 120000, "TWD", "annual", rates) is None
    )

    # Zero, negative, inverted ranges
    assert normalize_salary_to_annual_usd(0, 100000, "USD", "annual", rates) is None
    assert normalize_salary_to_annual_usd(-5000, 100000, "USD", "annual", rates) is None
    assert (
        normalize_salary_to_annual_usd(150000, 120000, "USD", "annual", rates) is None
    )

    # Plausibility bounds: [$3,000, $1,000,000]
    assert (
        normalize_salary_to_annual_usd(
            MIN_PLAUSIBLE_ANNUAL_USD - Decimal("0.01"), None, "USD", "annual", rates
        )
        is None
    )
    assert normalize_salary_to_annual_usd(
        MIN_PLAUSIBLE_ANNUAL_USD, None, "USD", "annual", rates
    ) == NormalizedAnnualUsd(
        annual_min_usd=Decimal("3000.00"),
        annual_max_usd=None,
        annual_mid_usd=Decimal("3000.00"),
    )
    assert normalize_salary_to_annual_usd(
        None, MAX_PLAUSIBLE_ANNUAL_USD, "USD", "annual", rates
    ) == NormalizedAnnualUsd(
        annual_min_usd=None,
        annual_max_usd=Decimal("1000000.00"),
        annual_mid_usd=Decimal("1000000.00"),
    )
    assert (
        normalize_salary_to_annual_usd(
            100000,
            MAX_PLAUSIBLE_ANNUAL_USD + Decimal("0.01"),
            "USD",
            "annual",
            rates,
        )
        is None
    )
    # Catch $150 tagged annual or R$ 200,000/mo (~$417k OK? Wait: R$ 600,000/mo > $1M)
    assert normalize_salary_to_annual_usd(150, None, "USD", "annual", rates) is None
    assert normalize_salary_to_annual_usd(600000, None, "BRL", "monthly", rates) is None


def test_convert_annual_usd_and_filter_bounds() -> None:
    rates = {"USD": Decimal("1.0"), "BRL": Decimal("5.0"), "EUR": Decimal("0.9")}

    assert convert_annual_usd_to_currency(
        Decimal("120000"), "BRL", SalaryPeriod.MONTHLY, rates
    ) == Decimal("50000.00")
    assert convert_annual_usd_to_currency(
        Decimal("104000"), "USD", SalaryPeriod.HOURLY, rates
    ) == Decimal("50.00")
    assert convert_annual_usd_to_currency(
        Decimal("100000"), "EUR", SalaryPeriod.ANNUAL, rates
    ) == Decimal("90000.00")
    assert convert_annual_usd_to_currency(None, "USD", "annual", rates) is None
    assert convert_annual_usd_to_currency(-1, "USD", "annual", rates) is None

    # Filter bound allows values below $3,000 (e.g., 0 or 2000) without plausibility rejection
    assert convert_salary_bound_to_annual_usd(0, "USD", "annual", rates) == Decimal(
        "0.00"
    )
    assert convert_salary_bound_to_annual_usd(
        Decimal("20000"), "BRL", "monthly", rates
    ) == Decimal("48000.00")
