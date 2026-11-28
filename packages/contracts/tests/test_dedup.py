import pytest

from vektryn_contracts import (
    AGGREGATOR_TIER,
    DIRECT_ATS_TIER,
    MANUAL_TIER,
    MIN_DEDUP_DESC_CHARS,
    SOURCE_PRIORITY_RANK,
    ATSSource,
    RegionEligibility,
    are_regions_compatible,
    compute_description_fingerprint,
    get_source_priority_rank,
    is_direct_ats_source,
    is_generic_company_name,
    normalize_company_for_dedup,
    normalize_title_for_dedup,
    token_jaccard_similarity,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Acme Corp.", "acme"),
        ("Acme, Inc.", "acme"),
        ("Acme LLC", "acme"),
        ("Acme Tecnologia Ltda.", "acme tecnologia"),
        ("Banco Itaú S/A", "banco itau"),
        ("Banco Itaú S.A.", "banco itau"),
        ("Siemens AG", "siemens"),
        ("Example Holding B.V.", "example holding"),
        ("Example Holding BV", "example holding"),
        ("Acme Corp., Ltd.", "acme"),
        ("Ltd", "ltd"),
        ("   ", ""),
        (None, ""),
    ],
)
def test_normalize_company_for_dedup(raw: str | None, expected: str) -> None:
    assert normalize_company_for_dedup(raw) == expected


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("", True),
        ("   ", True),
        ("confidential", True),
        ("Confidencial", True),
        ("Empresa Confidencial", True),
        ("Stealth Startup", True),
        ("stealth", True),
        ("undisclosed", True),
        ("Anonymous", True),
        ("Anônimo", True),
        ("unknown", True),
        ("N/A", True),
        ("Stripe", False),
        ("Nubank", False),
    ],
)
def test_is_generic_company_name(name: str, expected: bool) -> None:
    assert is_generic_company_name(name) is expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Senior Backend Engineer (Remote - LATAM)", "senior backend engineer"),
        ("Senior Backend Engineer - 100% Remoto", "senior backend engineer"),
        ("Staff Backend Engineer (Remote)", "staff backend engineer"),
        (
            "Engenheiro de Software Pleno - Home Office (Brasil)",
            "engenheiro de software pleno",
        ),
        ("Software Engineer II - Hybrid", "software engineer ii"),
        ("Software Engineer III - Hybrid", "software engineer iii"),
        ("Junior Frontend Developer [Brazil]", "junior frontend developer"),
        ("Principal Platform Engineer - Remote / EMEA", "principal platform engineer"),
    ],
)
def test_normalize_title_for_dedup(raw: str, expected: str) -> None:
    assert normalize_title_for_dedup(raw) == expected


def test_normalize_title_preserves_seniority_distinctions() -> None:
    senior = normalize_title_for_dedup("Senior Backend Engineer (Remote)")
    staff = normalize_title_for_dedup("Staff Backend Engineer (Remote)")
    mid = normalize_title_for_dedup("Mid Backend Engineer (Remote)")
    lead = normalize_title_for_dedup("Lead Backend Engineer (Remote)")
    assert len({senior, staff, mid, lead}) == 4


def test_compute_description_fingerprint_guards_short_stubs() -> None:
    fp, char_len = compute_description_fingerprint(
        "Apply via link: https://example.com/jobs/1"
    )
    assert fp == ""
    assert char_len < MIN_DEDUP_DESC_CHARS


def test_compute_description_fingerprint_ignores_html_urls_and_boilerplate() -> None:
    core = (
        "We are looking for a Senior Python Engineer to design and operate "
        "high-throughput event-driven microservices on PostgreSQL, Kafka, and Redis. "
        "You will mentor engineers, drive architectural RFCs, and own production reliability."
    )
    desc_a = f"<p>{core}</p><p>Apply at https://boards.greenhouse.io/acme/jobs/123</p>"
    desc_b = (
        f"Originally posted on Remotive\n"
        f"{core}\n"
        f"Please mention Remotive when applying.\n"
        f"Apply at https://remotive.com/remote-jobs/acme-999"
    )
    fp_a, len_a = compute_description_fingerprint(desc_a)
    fp_b, len_b = compute_description_fingerprint(desc_b)
    assert len_a >= MIN_DEDUP_DESC_CHARS
    assert len_b >= MIN_DEDUP_DESC_CHARS
    assert fp_a != ""
    assert fp_a == fp_b


def test_token_jaccard_similarity() -> None:
    assert token_jaccard_similarity(
        "senior python engineer", "senior python engineer"
    ) == pytest.approx(1.0)
    assert token_jaccard_similarity(
        "senior python engineer", "staff python engineer"
    ) == pytest.approx(0.5)
    assert token_jaccard_similarity("", "senior python") == pytest.approx(0.0)


@pytest.mark.parametrize(
    ("regions_a", "regions_b", "expected"),
    [
        ([RegionEligibility.BRAZIL], [RegionEligibility.LATAM], True),
        ([RegionEligibility.BRAZIL], [RegionEligibility.AMERICAS], True),
        ([RegionEligibility.LATAM], [RegionEligibility.AMERICAS], True),
        ([RegionEligibility.NORTH_AMERICA], [RegionEligibility.AMERICAS], True),
        ([RegionEligibility.EUROPE], [RegionEligibility.EMEA], True),
        ([RegionEligibility.BRAZIL], [RegionEligibility.EUROPE], False),
        ([RegionEligibility.BRAZIL], [RegionEligibility.NORTH_AMERICA], False),
        ([RegionEligibility.LATAM], [RegionEligibility.NORTH_AMERICA], False),
        ([RegionEligibility.APAC], [RegionEligibility.EMEA], False),
        ([RegionEligibility.RESTRICTED], [RegionEligibility.BRAZIL], False),
        ([RegionEligibility.RESTRICTED], [RegionEligibility.RESTRICTED], True),
        ([RegionEligibility.BRAZIL], [RegionEligibility.WORLDWIDE], True),
        ([RegionEligibility.BRAZIL], [RegionEligibility.UNKNOWN], True),
        ([], [RegionEligibility.EUROPE], True),
    ],
)
def test_are_regions_compatible(
    regions_a: list[RegionEligibility],
    regions_b: list[RegionEligibility],
    expected: bool,
) -> None:
    assert are_regions_compatible(regions_a, regions_b) is expected


def test_source_priority_rank_covers_all_ats_sources() -> None:
    assert set(SOURCE_PRIORITY_RANK.keys()) == set(ATSSource)
    assert get_source_priority_rank(ATSSource.GREENHOUSE) == DIRECT_ATS_TIER
    assert get_source_priority_rank(ATSSource.ASHBY) == DIRECT_ATS_TIER
    assert get_source_priority_rank(ATSSource.GUPY) == DIRECT_ATS_TIER
    assert get_source_priority_rank(ATSSource.REMOTIVE) == AGGREGATOR_TIER
    assert get_source_priority_rank(ATSSource.HIMALAYAS) == AGGREGATOR_TIER
    assert get_source_priority_rank(ATSSource.MANUAL) == MANUAL_TIER
    assert is_direct_ats_source(ATSSource.GREENHOUSE) is True
    assert is_direct_ats_source(ATSSource.REMOTIVE) is False
    assert is_direct_ats_source(ATSSource.MANUAL) is False
