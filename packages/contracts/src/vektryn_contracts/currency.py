from collections.abc import Mapping
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Final

from vektryn_contracts.enums import SalaryPeriod

MIN_PLAUSIBLE_ANNUAL_USD: Final[Decimal] = Decimal("3000")
MAX_PLAUSIBLE_ANNUAL_USD: Final[Decimal] = Decimal("1000000")
FX_RATES_REDIS_KEY: Final[str] = "vektryn:fx:rates:usd"
FX_RATES_REDIS_TTL_SECONDS: Final[int] = 26 * 3600

_CENT: Final[Decimal] = Decimal("0.01")
_TWO: Final[Decimal] = Decimal("2")
_ZERO: Final[Decimal] = Decimal("0")

ANNUALIZATION_MULTIPLIERS: Final[dict[SalaryPeriod, Decimal]] = {
    SalaryPeriod.ANNUAL: Decimal("1"),
    SalaryPeriod.MONTHLY: Decimal("12"),
    SalaryPeriod.HOURLY: Decimal("2080"),
}

# Conservative static fallback rates (units of currency per 1.00 USD) used strictly
# when both Redis and PostgreSQL FxRate are unavailable (e.g., offline CI tests or
# fresh bootstrap before the first FX fetch).
BUNDLED_FALLBACK_USD_RATES: Final[dict[str, Decimal]] = {
    "USD": Decimal("1.0"),
    "BRL": Decimal("5.75"),
    "EUR": Decimal("0.92"),
    "GBP": Decimal("0.79"),
    "CAD": Decimal("1.39"),
    "AUD": Decimal("1.53"),
    "CHF": Decimal("0.88"),
    "MXN": Decimal("20.20"),
    "COP": Decimal("4350.00"),
    "CLP": Decimal("965.00"),
    "ARS": Decimal("1010.00"),
    "PLN": Decimal("4.05"),
    "SEK": Decimal("10.85"),
    "NOK": Decimal("11.05"),
    "DKK": Decimal("6.88"),
    "INR": Decimal("84.50"),
    "JPY": Decimal("154.00"),
    "SGD": Decimal("1.34"),
    "NZD": Decimal("1.68"),
    "ZAR": Decimal("18.10"),
    "ILS": Decimal("3.72"),
    "CZK": Decimal("23.40"),
    "UYU": Decimal("42.50"),
    "PEN": Decimal("3.77"),
}

SUPPORTED_ISO_CURRENCIES: Final[frozenset[str]] = frozenset(
    {
        *BUNDLED_FALLBACK_USD_RATES.keys(),
        "AED",
        "BGN",
        "BHD",
        "BOB",
        "CNY",
        "CRC",
        "DOP",
        "EGP",
        "GTQ",
        "HKD",
        "HUF",
        "IDR",
        "ISK",
        "JOD",
        "KES",
        "KRW",
        "KWD",
        "MAD",
        "MYR",
        "NGN",
        "OMR",
        "PAB",
        "PHP",
        "PKR",
        "PYG",
        "QAR",
        "RON",
        "RSD",
        "SAR",
        "THB",
        "TRY",
        "TWD",
        "UAH",
        "VND",
    }
)

_CURRENCY_ALIASES: Final[dict[str, str]] = {
    "$": "USD",
    "US$": "USD",
    "U$S": "USD",
    "USD$": "USD",
    "U$": "USD",
    "DOLLAR": "USD",
    "DOLLARS": "USD",
    "R$": "BRL",
    "BR$": "BRL",
    "REAL": "BRL",
    "REAIS": "BRL",
    "€": "EUR",
    "EURO": "EUR",
    "EUROS": "EUR",
    "£": "GBP",
    "POUND": "GBP",
    "POUNDS": "GBP",
    "C$": "CAD",
    "CA$": "CAD",
    "CAD$": "CAD",
    "A$": "AUD",
    "AU$": "AUD",
    "AUD$": "AUD",
    "NZ$": "NZD",
    "S$": "SGD",
    "MX$": "MXN",
    "¥": "JPY",
    "₹": "INR",
    "₪": "ILS",
    "CHF": "CHF",
}


@dataclass(frozen=True, slots=True)
class NormalizedAnnualUsd:
    annual_min_usd: Decimal | None
    annual_max_usd: Decimal | None
    annual_mid_usd: Decimal


def _to_decimal(value: Decimal | int | float | str | None) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, Decimal):
        return value if value.is_finite() else None
    try:
        parsed = Decimal(str(value).strip())
    except InvalidOperation:
        return None
    return parsed if parsed.is_finite() else None


def _quantize_money(value: Decimal) -> Decimal:
    return value.quantize(_CENT, rounding=ROUND_HALF_UP)


def normalize_currency_code(raw: str | None) -> str:
    """Normalize currency symbols, aliases, or ISO 4217 codes to uppercase 3-letter ISO."""
    if not raw:
        return ""
    cleaned = str(raw).strip()
    if not cleaned:
        return ""

    upper = cleaned.upper()
    if upper in _CURRENCY_ALIASES:
        return _CURRENCY_ALIASES[upper]

    # Strip trailing punctuation such as "USD." or "BRL,"
    trimmed = upper.strip(".,;:/()[]")
    if trimmed in _CURRENCY_ALIASES:
        return _CURRENCY_ALIASES[trimmed]

    if len(trimmed) == 3 and trimmed.isalpha() and trimmed in SUPPORTED_ISO_CURRENCIES:
        return trimmed
    return ""


def resolve_annualization_multiplier(
    period: SalaryPeriod | str | None,
) -> Decimal | None:
    """Return deterministic annualization multiplier for SalaryPeriod or None if unknown."""
    if period is None:
        return None
    if isinstance(period, SalaryPeriod):
        return ANNUALIZATION_MULTIPLIERS.get(period)
    cleaned = str(period).strip().lower()
    if not cleaned:
        return None
    try:
        enum_period = SalaryPeriod(cleaned)
    except ValueError:
        return None
    return ANNUALIZATION_MULTIPLIERS.get(enum_period)


def _lookup_positive_rate(
    currency_code: str,
    usd_rates: Mapping[str, Decimal | int | float | str],
) -> Decimal | None:
    if not currency_code:
        return None
    raw_rate = usd_rates.get(currency_code)
    rate = _to_decimal(raw_rate)
    if rate is None or rate <= _ZERO:
        return None
    return rate


def _is_plausible_annual_usd(amount: Decimal) -> bool:
    return MIN_PLAUSIBLE_ANNUAL_USD <= amount <= MAX_PLAUSIBLE_ANNUAL_USD


def _parse_positive_salary_bounds(
    salary_min: Decimal | int | float | str | None,
    salary_max: Decimal | int | float | str | None,
) -> tuple[Decimal | None, Decimal | None] | None:
    dec_min = _to_decimal(salary_min)
    dec_max = _to_decimal(salary_max)
    if dec_min is None and dec_max is None:
        return None
    if dec_min is not None and dec_min <= _ZERO:
        return None
    if dec_max is not None and dec_max <= _ZERO:
        return None
    if dec_min is not None and dec_max is not None and dec_max < dec_min:
        return None
    return dec_min, dec_max


def _to_plausible_annual_usd(
    value: Decimal | None,
    multiplier: Decimal,
    rate: Decimal,
) -> tuple[bool, Decimal | None]:
    if value is None:
        return True, None
    annual = _quantize_money((value * multiplier) / rate)
    if not _is_plausible_annual_usd(annual):
        return False, None
    return True, annual


def normalize_salary_to_annual_usd(
    salary_min: Decimal | int | float | str | None,
    salary_max: Decimal | int | float | str | None,
    currency: str | None,
    period: SalaryPeriod | str | None,
    usd_rates: Mapping[str, Decimal | int | float | str],
) -> NormalizedAnnualUsd | None:
    """Normalize a disclosed posting salary range to canonical annual USD.

    Returns None for missing/unrecognized currency or period, non-positive bounds,
    inverted ranges (max < min), or values outside [MIN_PLAUSIBLE_ANNUAL_USD, MAX_PLAUSIBLE_ANNUAL_USD].
    """
    rate = _lookup_positive_rate(normalize_currency_code(currency), usd_rates)
    multiplier = resolve_annualization_multiplier(period)
    if rate is None or multiplier is None:
        return None

    parsed_bounds = _parse_positive_salary_bounds(salary_min, salary_max)
    if parsed_bounds is None:
        return None

    dec_min, dec_max = parsed_bounds
    min_ok, annual_min = _to_plausible_annual_usd(dec_min, multiplier, rate)
    max_ok, annual_max = _to_plausible_annual_usd(dec_max, multiplier, rate)
    if not min_ok or not max_ok:
        return None

    if annual_min is not None and annual_max is not None:
        annual_mid = _quantize_money((annual_min + annual_max) / _TWO)
    else:
        annual_mid = annual_min if annual_min is not None else annual_max

    if annual_mid is None:
        return None

    return NormalizedAnnualUsd(
        annual_min_usd=annual_min,
        annual_max_usd=annual_max,
        annual_mid_usd=annual_mid,
    )


def convert_annual_usd_to_currency(
    amount_annual_usd: Decimal | int | float | str | None,
    target_currency: str | None,
    period: SalaryPeriod | str | None,
    usd_rates: Mapping[str, Decimal | int | float | str],
) -> Decimal | None:
    """Convert canonical annual USD into target currency and display period."""
    amount = _to_decimal(amount_annual_usd)
    if amount is None or amount < _ZERO:
        return None
    code = normalize_currency_code(target_currency)
    rate = _lookup_positive_rate(code, usd_rates)
    multiplier = resolve_annualization_multiplier(period)
    if rate is None or multiplier is None:
        return None
    return _quantize_money((amount * rate) / multiplier)


def convert_salary_bound_to_annual_usd(
    amount: Decimal | int | float | str | None,
    currency: str | None,
    period: SalaryPeriod | str | None,
    usd_rates: Mapping[str, Decimal | int | float | str],
) -> Decimal | None:
    """Convert a user filter salary bound (>= 0) into canonical annual USD without job plausibility rejection."""
    dec_amount = _to_decimal(amount)
    if dec_amount is None or dec_amount < _ZERO:
        return None
    code = normalize_currency_code(currency)
    rate = _lookup_positive_rate(code, usd_rates)
    multiplier = resolve_annualization_multiplier(period)
    if rate is None or multiplier is None:
        return None
    return _quantize_money((dec_amount * multiplier) / rate)
