from uuid import uuid4

import pytest
from pydantic import ValidationError

from vektryn_contracts import (
    EMBEDDING_DIMENSIONS,
    ISO_639_1_CODES,
    UNKNOWN_LANGUAGE,
    VALID_LANGUAGE_CODES,
    ATSSource,
    JobEnrichedEvent,
    JobMatchAlertEvent,
    detect_content_language,
    is_valid_language_code,
    normalize_language_code,
)


def test_iso_639_1_registry_has_no_other_bucket_and_covers_standard_codes() -> None:
    assert len(ISO_639_1_CODES) == 184
    assert "other" not in ISO_639_1_CODES
    assert UNKNOWN_LANGUAGE == "unknown"
    assert VALID_LANGUAGE_CODES == ISO_639_1_CODES | {UNKNOWN_LANGUAGE}
    for code in (
        "en",
        "pt",
        "es",
        "de",
        "fr",
        "it",
        "ja",
        "zh",
        "ko",
        "nl",
        "pl",
        "uk",
    ):
        assert code in ISO_639_1_CODES


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("en", "en"),
        ("EN", "en"),
        ("en-US", "en"),
        ("en_GB", "en"),
        ("pt-BR", "pt"),
        ("pt_PT", "pt"),
        ("zh-Hans", "zh"),
        ("zh-Hans-CN", "zh"),
        ("es-419", "es"),
        ("iw", "he"),
        ("in", "id"),
        ("ji", "yi"),
        ("unknown", "unknown"),
        ("", "unknown"),
        ("   ", "unknown"),
        (None, "unknown"),
    ],
)
def test_normalize_language_code_valid_inputs(raw: str | None, expected: str) -> None:
    assert normalize_language_code(raw, strict=False) == expected
    assert normalize_language_code(raw, strict=True) == expected
    assert is_valid_language_code(raw) is True


@pytest.mark.parametrize(
    "invalid",
    ["other", "english", "portuguese", "xx", "zz", "123", "und", "zxx", "en-US-bad!"],
)
def test_normalize_language_code_invalid_inputs(invalid: str) -> None:
    assert normalize_language_code(invalid, strict=False) == UNKNOWN_LANGUAGE
    assert is_valid_language_code(invalid) is False
    with pytest.raises(ValueError, match="Invalid ISO 639-1"):
        normalize_language_code(invalid, strict=True)


def test_is_valid_language_code_allow_unknown_flag() -> None:
    assert is_valid_language_code("unknown", allow_unknown=True) is True
    assert is_valid_language_code("unknown", allow_unknown=False) is False
    assert is_valid_language_code(None, allow_unknown=False) is False
    assert is_valid_language_code("pt-BR", allow_unknown=False) is True


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "We are looking for a Senior Backend Engineer to build scalable distributed "
            "services with Python, Django, PostgreSQL, and Apache Kafka for our remote team.",
            "en",
        ),
        (
            "Estamos buscando uma pessoa Engenheira de Software Backend Senior para atuar "
            "com Python, Django, PostgreSQL e mensageria em arquitetura distribuida 100% remota.",
            "pt",
        ),
        (
            "Buscamos un Ingeniero de Software Backend Senior con experiencia comprobada "
            "en Python, arquitecturas de microservicios, bases de datos y sistemas distribuidos.",
            "es",
        ),
        (
            "Wir suchen einen erfahrenen Backend-Entwickler fuer unsere verteilten Systeme "
            "mit Python, PostgreSQL, Docker und moderner Cloud-Infrastruktur im Remote-Team.",
            "de",
        ),
        (
            "Nous recherchons un ingenieur logiciel backend experimente pour concevoir et "
            "maintenir nos services distribues en Python avec PostgreSQL et Kafka en teletravail.",
            "fr",
        ),
        (
            "Cerchiamo uno sviluppatore software backend esperto nella progettazione di "
            "microservizi scalabili in Python, database relazionali e architetture cloud remote.",
            "it",
        ),
    ],
)
def test_detect_content_language_multilingual_samples(text: str, expected: str) -> None:
    detected = detect_content_language(text)
    assert detected == expected


def test_detect_content_language_short_and_non_linguistic_guards() -> None:
    assert detect_content_language(None) == UNKNOWN_LANGUAGE
    assert detect_content_language("") == UNKNOWN_LANGUAGE
    assert detect_content_language("Senior Python Engineer Remote") == UNKNOWN_LANGUAGE
    assert (
        detect_content_language(
            "010101 1234567890 {{{}}} [][][] === 999999999 0xdeadbeef "
            "https://example.com/a/b/c https://example.org/d/e/f 42 100 200 300 400"
        )
        == UNKNOWN_LANGUAGE
    )


def test_no_cross_language_collision_between_unrelated_languages() -> None:
    fr_text = (
        "Nous recrutons un developpeur backend senior pour construire des APIs fiables "
        "et performantes en Python avec notre equipe internationale entierement a distance."
    )
    de_text = (
        "Wir stellen einen erfahrenen Softwareentwickler fuer den Aufbau skalierbarer "
        "Backend-Dienste mit Python, PostgreSQL und Cloud-Infrastruktur in unserem Team ein."
    )
    fr_code = detect_content_language(fr_text)
    de_code = detect_content_language(de_text)
    assert fr_code == "fr"
    assert de_code == "de"
    assert fr_code != de_code


def test_enriched_and_alert_events_language_backward_compatibility() -> None:
    enriched = JobEnrichedEvent(
        ats_source=ATSSource.GREENHOUSE,
        external_id="gh-lang-1",
        content_hash="b" * 64,
        title="Engenheiro Backend Senior",
        company_name="Acme Brasil",
        apply_url="https://boards.greenhouse.io/acme/jobs/1",
        raw_html_gcs_uri="gs://bucket/gh-lang-1.html",
        description_clean="Vaga remota para desenvolvedor backend Python.",
        language="pt-BR",
        embedding=[0.01] * EMBEDDING_DIMENSIONS,
    )
    assert enriched.language == "pt"

    legacy_enriched_dict = enriched.model_dump(mode="json")
    legacy_enriched_dict.pop("language")
    restored_legacy = JobEnrichedEvent.model_validate(legacy_enriched_dict)
    assert restored_legacy.language == UNKNOWN_LANGUAGE

    with pytest.raises(ValidationError):
        JobEnrichedEvent(
            ats_source=ATSSource.GREENHOUSE,
            external_id="gh-lang-bad",
            content_hash="c" * 64,
            title="Role",
            company_name="Acme",
            apply_url="https://boards.greenhouse.io/acme/jobs/2",
            raw_html_gcs_uri="gs://bucket/gh-lang-2.html",
            description_clean="Description",
            language="other",
            embedding=[0.01] * EMBEDDING_DIMENSIONS,
        )

    alert = JobMatchAlertEvent(
        user_id=7,
        job_posting_uuid=uuid4(),
        resume_profile_uuid=uuid4(),
        resume_profile_label="Backend PT-BR",
        resume_language="pt_BR",
        match_score_uuid=uuid4(),
        title="Engenheiro Backend",
        company_name="Acme",
        fit_score=91,
        cosine_similarity=0.88,
        apply_url="https://boards.greenhouse.io/acme/jobs/1",
    )
    assert alert.resume_profile_label == "Backend PT-BR"
    assert alert.resume_language == "pt"

    legacy_alert_dict = alert.model_dump(mode="json")
    legacy_alert_dict.pop("resume_profile_label")
    legacy_alert_dict.pop("resume_language")
    restored_alert = JobMatchAlertEvent.model_validate(legacy_alert_dict)
    assert restored_alert.resume_profile_label == ""
    assert restored_alert.resume_language == UNKNOWN_LANGUAGE
