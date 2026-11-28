from collections.abc import Sequence
import hashlib
import html
import re
from typing import Final
import unicodedata

from vektryn_contracts.enums import ATSSource, RegionEligibility

MIN_DEDUP_DESC_CHARS: Final[int] = 150

DIRECT_ATS_TIER: Final[int] = 10
AGGREGATOR_TIER: Final[int] = 20
MANUAL_TIER: Final[int] = 30

SOURCE_PRIORITY_RANK: Final[dict[ATSSource, int]] = {
    # Tier 1: Direct ATS boards
    ATSSource.GREENHOUSE: DIRECT_ATS_TIER,
    ATSSource.ASHBY: DIRECT_ATS_TIER,
    ATSSource.LEVER: DIRECT_ATS_TIER,
    ATSSource.WORKABLE: DIRECT_ATS_TIER,
    ATSSource.SMARTRECRUITERS: DIRECT_ATS_TIER,
    ATSSource.RECRUITEE: DIRECT_ATS_TIER,
    ATSSource.BREEZY: DIRECT_ATS_TIER,
    ATSSource.INHIRE: DIRECT_ATS_TIER,
    ATSSource.GUPY: DIRECT_ATS_TIER,
    ATSSource.SOLIDES: DIRECT_ATS_TIER,
    # Tier 2: Multi-company aggregator feeds
    ATSSource.REMOTIVE: AGGREGATOR_TIER,
    ATSSource.HIMALAYAS: AGGREGATOR_TIER,
    ATSSource.JOBICY: AGGREGATOR_TIER,
    ATSSource.TRAMPOS: AGGREGATOR_TIER,
    ATSSource.GITHUB_VAGAS: AGGREGATOR_TIER,
    # Tier 3: Manual user imports
    ATSSource.MANUAL: MANUAL_TIER,
}

_LEGAL_SUFFIX_TOKENS: Final[frozenset[str]] = frozenset(
    {
        "inc",
        "llc",
        "ltd",
        "ltda",
        "sa",
        "gmbh",
        "corp",
        "co",
        "plc",
        "bv",
        "ag",
        "sas",
        "srl",
    }
)

_GENERIC_COMPANY_NAMES: Final[frozenset[str]] = frozenset(
    {
        "confidential",
        "confidencial",
        "empresa confidencial",
        "stealth",
        "stealth startup",
        "undisclosed",
        "anonymous",
        "anonimo",
        "unknown",
        "n/a",
        "na",
    }
)

# Downward containment expansion: broad regions include their narrower sub-regions
# so siblings (e.g. brazil vs north_america) stay disjoint while parent/child
# pairs (e.g. brazil vs latam/americas, europe vs emea) intersect cleanly.
_REGION_DOWNWARD_EXPANSION: Final[dict[str, frozenset[str]]] = {
    RegionEligibility.BRAZIL.value: frozenset({RegionEligibility.BRAZIL.value}),
    RegionEligibility.LATAM.value: frozenset(
        {RegionEligibility.BRAZIL.value, RegionEligibility.LATAM.value}
    ),
    RegionEligibility.NORTH_AMERICA.value: frozenset(
        {RegionEligibility.NORTH_AMERICA.value}
    ),
    RegionEligibility.AMERICAS.value: frozenset(
        {
            RegionEligibility.BRAZIL.value,
            RegionEligibility.LATAM.value,
            RegionEligibility.NORTH_AMERICA.value,
            RegionEligibility.AMERICAS.value,
        }
    ),
    RegionEligibility.EUROPE.value: frozenset({RegionEligibility.EUROPE.value}),
    RegionEligibility.EMEA.value: frozenset(
        {RegionEligibility.EUROPE.value, RegionEligibility.EMEA.value}
    ),
    RegionEligibility.APAC.value: frozenset({RegionEligibility.APAC.value}),
    RegionEligibility.RESTRICTED.value: frozenset({RegionEligibility.RESTRICTED.value}),
}

_WILDCARD_REGIONS: Final[frozenset[str]] = frozenset(
    {RegionEligibility.UNKNOWN.value, RegionEligibility.WORLDWIDE.value}
)

_SA_DOTTED_OR_SLASH_RE = re.compile(r"\bs\s*[./]\s*a\.?(?=\s|$)", re.IGNORECASE)
_BV_DOTTED_RE = re.compile(r"\bb\s*[./]\s*v\.?(?=\s|$)", re.IGNORECASE)
_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")
_WHITESPACE_RE = re.compile(r"\s+")
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_URL_RE = re.compile(r"(?:https?://|www\.|mailto:)\S+", re.IGNORECASE)

_TITLE_NOISE_PHRASE = (
    r"(?:"
    r"100%\s*(?:remote|remoto)"
    r"|full(?:y)?\s*remote"
    r"|home\s*office"
    r"|work\s*from\s*home"
    r"|remote(?:\s*[-/,]?\s*(?:first|only|us|usa|uk|eu|europe|emea|latam|brazil|brasil|worldwide|global|americas))?"
    r"|remoto(?:\s*[-/,]?\s*(?:brasil|brazil|latam))?"
    r"|hybrid|hibrido"
    r"|on[-\s]*site|presencial"
    r"|latam|brazil|brasil|worldwide|global|americas|emea|europe|eu|usa|us|uk"
    r"|sao\s*paulo|rio\s*de\s*janeiro|belo\s*horizonte|curitiba|florianopolis|sp|rj|mg"
    r")"
)
_TITLE_NOISE_UNIT_RE = re.compile(
    rf"^(?:\s*[-/,|&]\s*)?{_TITLE_NOISE_PHRASE}(?:\s*[-/,|&]\s*{_TITLE_NOISE_PHRASE})*\s*$",
    re.IGNORECASE,
)
_TITLE_BRACKETED_RE = re.compile(r"[\(\[\{]([^\)\]\}]*)[\)\]\}]")
_TITLE_TRAILING_SEP_RE = re.compile(
    r"\s*[-\u2013\u2014|/\u2022]\s*([^-\u2013\u2014|\u2022]+)$"
)
_TITLE_TRAILING_NOISE_RE = re.compile(
    rf"(?:\s+|,\s*){_TITLE_NOISE_PHRASE}\s*$",
    re.IGNORECASE,
)

_BOILERPLATE_LINE_RE = re.compile(
    r"(?:^|\n)\s*(?:"
    r"originally\s+posted\s+on\b[^\n]*"
    r"|this\s+job\s+(?:was\s+)?(?:sourced|syndicated|imported)\s+from\b[^\n]*"
    r"|apply\s+(?:now\s+)?(?:at|via|on)\s+(?:remotive|himalayas|jobicy|trampos|gupy|greenhouse|lever|ashby)\b[^\n]*"
    r"|please\s+mention\s+(?:remotive|himalayas|jobicy|trampos)\b[^\n]*"
    r")",
    re.IGNORECASE,
)


def _fold_ascii_lower(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return stripped.lower()


def get_source_priority_rank(source: ATSSource | str) -> int:
    """Return canonical precedence rank (lower = higher precedence)."""
    if isinstance(source, ATSSource):
        return SOURCE_PRIORITY_RANK.get(source, MANUAL_TIER)
    try:
        enum_source = ATSSource(str(source).strip().lower())
    except ValueError:
        return MANUAL_TIER
    return SOURCE_PRIORITY_RANK.get(enum_source, MANUAL_TIER)


def is_direct_ats_source(source: ATSSource | str) -> bool:
    """Return True iff the source is a Tier 1 Direct ATS board."""
    return get_source_priority_rank(source) == DIRECT_ATS_TIER


def normalize_company_for_dedup(name: str | None) -> str:
    """Normalize company name for cross-source dedup while preserving core stem.

    NFKD accent-folds, lowercases, strips punctuation, collapses whitespace, and
    removes trailing legal entity suffixes (inc, llc, ltd, ltda, sa, s/a, gmbh,
    corp, co, plc, bv, ag, sas, srl). Does NOT alter MutedCompany normalization.
    """
    if not name:
        return ""

    folded = _fold_ascii_lower(str(name).strip())
    if not folded:
        return ""

    folded = _SA_DOTTED_OR_SLASH_RE.sub(" sa ", folded)
    folded = _BV_DOTTED_RE.sub(" bv ", folded)
    cleaned = _NON_ALNUM_RE.sub(" ", folded)
    tokens = [tok for tok in cleaned.split() if tok]
    if not tokens:
        return ""

    while len(tokens) > 1 and tokens[-1] in _LEGAL_SUFFIX_TOKENS:
        tokens.pop()

    return " ".join(tokens)


def is_generic_company_name(normalized_name: str | None) -> bool:
    """Return True for empty or placeholder/confidential company labels."""
    if not normalized_name:
        return True
    raw_folded = _WHITESPACE_RE.sub(
        " ", _fold_ascii_lower(str(normalized_name))
    ).strip()
    if not raw_folded or raw_folded in _GENERIC_COMPANY_NAMES:
        return True
    alnum_only = _WHITESPACE_RE.sub(" ", _NON_ALNUM_RE.sub(" ", raw_folded)).strip()
    return not alnum_only or alnum_only in _GENERIC_COMPANY_NAMES


def normalize_title_for_dedup(title: str | None) -> str:
    """Normalize job title while stripping location/work-mode noise and keeping seniority."""
    if not title:
        return ""

    text = _fold_ascii_lower(str(title).strip())
    if not text:
        return ""

    def _strip_noise_bracket(match: re.Match[str]) -> str:
        inner = match.group(1).strip()
        if inner and _TITLE_NOISE_UNIT_RE.match(inner):
            return " "
        return f" {inner} "

    text = _TITLE_BRACKETED_RE.sub(_strip_noise_bracket, text)

    # Iteratively trim trailing separator-delimited location/work-mode segments
    while True:
        sep_match = _TITLE_TRAILING_SEP_RE.search(text)
        if sep_match and _TITLE_NOISE_UNIT_RE.match(sep_match.group(1).strip()):
            text = text[: sep_match.start()].strip()
            continue
        trailing_match = _TITLE_TRAILING_NOISE_RE.search(text)
        if trailing_match:
            candidate = text[: trailing_match.start()].strip()
            if candidate:
                text = candidate
                continue
        break

    cleaned = _NON_ALNUM_RE.sub(" ", text)
    return _WHITESPACE_RE.sub(" ", cleaned).strip()


def clean_description_for_dedup(description: str | None) -> str:
    """Strip HTML, URLs, aggregator boilerplate, and punctuation for dedup comparison."""
    if not description:
        return ""

    text = html.unescape(str(description))
    text = _HTML_TAG_RE.sub(" ", text)
    text = _BOILERPLATE_LINE_RE.sub(" ", text)
    text = _URL_RE.sub(" ", text)
    text = _fold_ascii_lower(text)
    text = _NON_ALNUM_RE.sub(" ", text)
    return _WHITESPACE_RE.sub(" ", text).strip()


def compute_description_fingerprint(
    description: str | None,
    *,
    min_chars: int = MIN_DEDUP_DESC_CHARS,
) -> tuple[str, int]:
    """Return (sha256_hex, normalized_char_len), with empty hash below min_chars."""
    cleaned = clean_description_for_dedup(description)
    char_len = len(cleaned)
    if char_len < min_chars:
        return "", char_len
    digest = hashlib.sha256(cleaned.encode("utf-8")).hexdigest()
    return digest, char_len


def token_jaccard_similarity(text_a: str | None, text_b: str | None) -> float:
    """Compute normalized word-set Jaccard similarity in [0.0, 1.0]."""
    if not text_a or not text_b:
        return 0.0
    tokens_a = set(_NON_ALNUM_RE.sub(" ", _fold_ascii_lower(str(text_a))).split())
    tokens_b = set(_NON_ALNUM_RE.sub(" ", _fold_ascii_lower(str(text_b))).split())
    if not tokens_a or not tokens_b:
        return 0.0
    union = tokens_a | tokens_b
    if not union:
        return 0.0
    return len(tokens_a & tokens_b) / len(union)


def are_regions_compatible(
    regions_a: Sequence[RegionEligibility | str] | None,
    regions_b: Sequence[RegionEligibility | str] | None,
) -> bool:
    """Return True iff two region_eligibility lists can refer to the same role."""
    norm_a = {
        (r.value if isinstance(r, RegionEligibility) else str(r).strip().lower())
        for r in (regions_a or [])
        if str(r).strip()
    }
    norm_b = {
        (r.value if isinstance(r, RegionEligibility) else str(r).strip().lower())
        for r in (regions_b or [])
        if str(r).strip()
    }

    if not norm_a or not norm_b:
        return True
    if norm_a & _WILDCARD_REGIONS or norm_b & _WILDCARD_REGIONS:
        return True

    expanded_a: set[str] = set()
    for region in norm_a:
        expanded_a.update(_REGION_DOWNWARD_EXPANSION.get(region, frozenset({region})))

    expanded_b: set[str] = set()
    for region in norm_b:
        expanded_b.update(_REGION_DOWNWARD_EXPANSION.get(region, frozenset({region})))

    return bool(expanded_a & expanded_b)
