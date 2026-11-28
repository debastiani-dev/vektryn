from functools import lru_cache
import importlib
import re
from typing import Any, Final

from vektryn_contracts.enums import ISO_639_1_CODES, UNKNOWN_LANGUAGE

MIN_DETECTION_TEXT_CHARS: Final[int] = 80
MIN_DETECTION_CONFIDENCE: Final[float] = 0.65
MAX_DETECTION_SAMPLE_CHARS: Final[int] = 8000

_LEGACY_ISO_ALIASES: Final[dict[str, str]] = {
    "iw": "he",
    "in": "id",
    "ji": "yi",
    "jw": "jv",
    "mo": "ro",
}
_URL_RE = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)
_WHITESPACE_RE = re.compile(r"\s+")
_LOCALE_SPLIT_RE = re.compile(r"[-_]")
_BCP47_TAG_RE = re.compile(r"^[a-z]{2,3}(?:[-_][a-z0-9]{2,8})*$")


def normalize_language_code(value: str | None, *, strict: bool = False) -> str:
    """Normalize a BCP-47/ISO language tag to lowercase ISO 639-1 or 'unknown'.

    In permissive mode (strict=False), unknown/undetermined/non-ISO values return
    'unknown'. In strict mode (strict=True), only empty/None/'unknown' or valid
    ISO 639-1 / BCP-47 tags are accepted; all other values raise ValueError.
    """
    if value is None:
        return UNKNOWN_LANGUAGE

    raw = str(value).strip().lower()
    if not raw or raw == UNKNOWN_LANGUAGE:
        return UNKNOWN_LANGUAGE

    if raw in {"und", "zxx"}:
        if strict:
            raise ValueError(f"Invalid ISO 639-1 language code: {value!r}")
        return UNKNOWN_LANGUAGE

    if not _BCP47_TAG_RE.match(raw):
        if strict:
            raise ValueError(f"Invalid ISO 639-1 language code: {value!r}")
        return UNKNOWN_LANGUAGE

    primary = _LOCALE_SPLIT_RE.split(raw, maxsplit=1)[0]
    primary = _LEGACY_ISO_ALIASES.get(primary, primary)

    if primary in ISO_639_1_CODES:
        return primary

    if strict:
        raise ValueError(f"Invalid ISO 639-1 language code: {value!r}")
    return UNKNOWN_LANGUAGE


def is_valid_language_code(value: str | None, *, allow_unknown: bool = True) -> bool:
    """Return True iff value normalizes cleanly to ISO 639-1 (or 'unknown')."""
    if value is None:
        return allow_unknown
    try:
        normalized = normalize_language_code(value, strict=True)
    except ValueError:
        return False
    if normalized == UNKNOWN_LANGUAGE:
        return allow_unknown
    return True


@lru_cache(maxsize=1)
def _get_language_identifier() -> Any:
    """Lazily load py3langid so workers that never detect text pay 0 MB RAM."""
    langid_mod = importlib.import_module("py3langid.langid")
    return langid_mod.LanguageIdentifier.from_model_file(
        langid_mod.MODEL_FILE,
        norm_probs=True,
        min_confidence=MIN_DETECTION_CONFIDENCE,
    )


def _clean_text_for_detection(text: str) -> str:
    without_urls = _URL_RE.sub(" ", text)
    return _WHITESPACE_RE.sub(" ", without_urls).strip()


def detect_content_language(text: str | None) -> str:
    """Detect ISO 639-1 language offline via py3langid with length/confidence guards."""
    if not text:
        return UNKNOWN_LANGUAGE

    cleaned = _clean_text_for_detection(text)
    if len(cleaned) < MIN_DETECTION_TEXT_CHARS:
        return UNKNOWN_LANGUAGE

    sample = cleaned[:MAX_DETECTION_SAMPLE_CHARS]
    identifier = _get_language_identifier()
    detected_code, confidence = identifier.classify(sample)
    if confidence < MIN_DETECTION_CONFIDENCE:
        return UNKNOWN_LANGUAGE
    return normalize_language_code(detected_code, strict=False)
