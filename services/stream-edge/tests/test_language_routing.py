"""Tests for Spec #21 multilingual classification & single-winner routing in stream-edge."""

from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
import uuid

from cryptography.fernet import Fernet

from stream_edge.clients.gemini import (
    ExtractedJobMetadata,
    build_resume_fit_prompt,
    normalize_salary_currency,
)
from stream_edge.collectors.prefilter import load_resume_criteria
from stream_edge.workers.enrichment import process_raw_message
from stream_edge.workers.matcher import (
    _ActiveProfile,
    _JobCandidate,
    _rescore_resume_sync,
    _upsert_job_and_score_sync,
    select_winning_profile,
)
from vektryn_contracts import (
    EMBEDDING_DIMENSIONS,
    UNKNOWN_LANGUAGE,
    ATSSource,
    ContractType,
    JobEnrichedEvent,
    JobRawEvent,
    JobRescoreEvent,
    RegionEligibility,
    SeniorityLevel,
    WorkMode,
    encrypt_api_key,
)


def _make_profile(
    *,
    profile_uuid: uuid.UUID | None = None,
    user_id: int = 1,
    label: str = "Backend",
    language: str = "en",
    strict_language_match: bool = False,
    cosine_similarity: float = 0.80,
    modified_at: datetime | None = None,
    target_work_modes: list[str] | None = None,
    target_regions: list[str] | None = None,
) -> _ActiveProfile:
    return _ActiveProfile(
        uuid=profile_uuid or uuid.uuid4(),
        user_id=user_id,
        label=label,
        raw_text="Senior Python engineer",
        content_hash="h" * 64,
        extracted_skills=["python"],
        target_seniority=[],
        target_contract_types=[],
        target_regions=target_regions or [],
        min_alert_score=70,
        cosine_similarity=cosine_similarity,
        target_work_modes=target_work_modes,
        language=language,
        strict_language_match=strict_language_match,
        modified_at=modified_at or datetime(2026, 11, 20, 12, 0, tzinfo=UTC),
    )


def _make_job(
    *,
    language: str = "en",
    work_mode: str = "remote",
    region_eligibility: list[str] | None = None,
    ats_source: str = "greenhouse",
    submitted_by_user_id: int | None = None,
) -> _JobCandidate:
    return _JobCandidate(
        uuid=uuid.uuid4(),
        title="Senior Python Backend Engineer",
        company_name="Acme",
        apply_url="https://acme.example/jobs/1",
        description_clean="Build distributed Python services.",
        seniority="senior",
        contract_type="pj",
        region_eligibility=region_eligibility or ["worldwide"],
        tech_stack=["python"],
        work_mode=work_mode,
        language=language,
        ats_source=ats_source,
        submitted_by_user_id=submitted_by_user_id,
    )


async def test_enrichment_normalizes_language_and_runs_offline_fallback() -> None:
    pt_raw = JobRawEvent(
        ats_source=ATSSource.GUPY,
        external_id="gupy-pt-fallback",
        content_hash="a" * 64,
        title="Engenheiro Backend Python Senior",
        company_name="Acme Brasil",
        apply_url="https://acme.gupy.io/jobs/pt-fallback",
        raw_html_gcs_uri="gs://bucket/pt.html",
        description_clean=(
            "Estamos contratando uma pessoa Engenheira de Software Backend Senior "
            "para desenvolver microsservicos escalaveis com Python, Django, PostgreSQL e Kafka."
        ),
    )
    mock_gemini = MagicMock()
    # Gemini returns "unknown" -> deterministic py3langid fallback resolves "pt"
    mock_gemini.extract_job_metadata = AsyncMock(
        return_value=ExtractedJobMetadata(
            work_mode=WorkMode.REMOTE,
            language=UNKNOWN_LANGUAGE,
            tech_stack=["python", "django"],
        )
    )
    mock_gemini.embed_job_text = AsyncMock(return_value=[0.05] * EMBEDDING_DIMENSIONS)
    mock_redis = MagicMock()
    mock_redis.acquire_content_hash = AsyncMock(return_value=True)
    mock_redis.try_consume_enrichment_daily_quota = AsyncMock(return_value=(True, 1))
    mock_producer = MagicMock()
    mock_producer.publish = AsyncMock()

    await process_raw_message(
        raw_bytes=pt_raw.model_dump_json().encode("utf-8"),
        gemini=mock_gemini,
        redis_client=mock_redis,
        producer=mock_producer,
    )
    published = mock_producer.publish.call_args.kwargs["event"]
    assert isinstance(published, JobEnrichedEvent)
    assert published.language == "pt"

    # When Gemini returns BCP-47 like "de-DE", normalize directly without fallback
    mock_producer.reset_mock()
    mock_gemini.extract_job_metadata = AsyncMock(
        return_value=ExtractedJobMetadata(
            work_mode=WorkMode.REMOTE,
            language="de-DE",
            tech_stack=["python"],
        )
    )
    await process_raw_message(
        raw_bytes=pt_raw.model_dump_json().encode("utf-8"),
        gemini=mock_gemini,
        redis_client=mock_redis,
        producer=mock_producer,
    )
    published_de = mock_producer.publish.call_args.kwargs["event"]
    assert published_de.language == "de"


def test_select_winning_profile_language_routing_strict_no_collisions_and_tiebreaker() -> (
    None
):
    en_profile = _make_profile(
        label="Backend EN", language="en", cosine_similarity=0.92
    )
    pt_profile = _make_profile(
        label="Backend PT", language="pt", cosine_similarity=0.78
    )
    de_strict = _make_profile(
        label="Backend DE Strict",
        language="de",
        strict_language_match=True,
        cosine_similarity=0.95,
    )

    # 1. PT job narrows exclusively to PT profile even when EN has higher cosine
    winner_pt = select_winning_profile(
        [en_profile, pt_profile, de_strict], _make_job(language="pt")
    )
    assert winner_pt is pt_profile

    # 2. EN job routes to EN profile
    winner_en = select_winning_profile(
        [en_profile, pt_profile, de_strict], _make_job(language="en")
    )
    assert winner_en is en_profile

    # 3. FR job has zero collision with DE (no "other" bucket); de_strict is excluded; falls back to highest cosine non-strict (EN)
    winner_fr = select_winning_profile(
        [en_profile, pt_profile, de_strict], _make_job(language="fr")
    )
    assert winner_fr is en_profile

    # 4. Strict profile blocks mismatched known language when it is the only profile
    assert select_winning_profile([de_strict], _make_job(language="en")) is None

    # 5. Strict profile STILL allows job.language == "unknown"
    assert (
        select_winning_profile([de_strict], _make_job(language=UNKNOWN_LANGUAGE))
        is de_strict
    )

    # 6. Deterministic tie-breaker: cosine DESC, modified_at DESC, uuid ASC
    t1 = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)
    t2 = t1 + timedelta(hours=1)
    low_uuid = uuid.UUID("00000000-0000-0000-0000-000000000001")
    high_uuid = uuid.UUID("00000000-0000-0000-0000-000000000009")

    older = _make_profile(
        profile_uuid=low_uuid, language="en", cosine_similarity=0.85, modified_at=t1
    )
    newer_high = _make_profile(
        profile_uuid=high_uuid, language="en", cosine_similarity=0.85, modified_at=t2
    )
    newer_low = _make_profile(
        profile_uuid=low_uuid, language="en", cosine_similarity=0.85, modified_at=t2
    )

    assert (
        select_winning_profile([older, newer_high], _make_job(language="en"))
        is newer_high
    )
    assert (
        select_winning_profile([newer_high, newer_low], _make_job(language="en"))
        is newer_low
    )


def test_matcher_single_byok_call_per_user_advisory_lock_and_manual_fallback() -> None:
    fernet_key = Fernet.generate_key().decode("utf-8")
    encrypted_key = encrypt_api_key("AIzaSyMultiResumeKey1234567890", fernet_key)
    job_uuid = uuid.uuid4()
    en_uuid = uuid.uuid4()
    pt_uuid = uuid.uuid4()
    match_uuid = uuid.uuid4()
    now = datetime(2026, 11, 27, 12, 0, tzinfo=UTC)

    # 1. Two active resumes (EN + PT) for user 7 -> PT job executes STRICTLY 1 Stage 2 BYOK call (PT)
    pt_event = JobEnrichedEvent(
        ats_source=ATSSource.GUPY,
        external_id="gupy-pt-1",
        content_hash="c" * 64,
        title="Desenvolvedor Python Senior",
        company_name="Acme BR",
        apply_url="https://acme.gupy.io/jobs/1",
        raw_html_gcs_uri="gs://bucket/1.html",
        description_clean="Vaga remota Python Django",
        seniority=SeniorityLevel.SENIOR,
        contract_type=ContractType.CLT,
        work_mode=WorkMode.REMOTE,
        language="pt",
        region_eligibility=[RegionEligibility.BRAZIL],
        tech_stack=["python", "django"],
        embedding=[0.1] * EMBEDDING_DIMENSIONS,
    )

    executed_sql: list[tuple[str, tuple | None]] = []
    cur = MagicMock()
    cur.execute.side_effect = lambda sql, params=None: executed_sql.append(
        (sql, params)
    )
    cur.fetchone.side_effect = [
        None,
        None,
        (job_uuid,),
        (match_uuid, None),
        (match_uuid,),
    ]
    cur.fetchall.return_value = [
        (
            en_uuid,
            7,
            "Backend EN",
            "Senior Python EN",
            "h1" + "0" * 62,
            ["python"],
            ["senior"],
            [],
            ["brazil"],
            70,
            0.93,
            encrypted_key,
            "auto",
            True,
            ["remote"],
            "en",
            False,
            now,
        ),
        (
            pt_uuid,
            7,
            "Backend PT-BR",
            "Engenheiro Python PT",
            "h2" + "0" * 62,
            ["python"],
            ["senior"],
            [],
            ["brazil"],
            70,
            0.84,
            encrypted_key,
            "auto",
            True,
            ["remote"],
            "pt",
            False,
            now,
        ),
    ]

    @contextmanager
    def _fake_connect(*_args, **_kwargs):
        conn = MagicMock()
        conn.cursor.return_value.__enter__.return_value = cur
        yield conn

    scoring_manager = MagicMock()
    scoring_manager.evaluate_resume_fit_sync.return_value = (
        SimpleNamespace(
            fit_score=90,
            matched_skills=["python"],
            missing_keywords=[],
            talking_points=["Experiencia com Django"],
            gap_summary="Otimo fit.",
            fit_highlights=["Python forte"],
            watchout_note="",
        ),
        "gemini-4-hydrogen",
    )
    producer = MagicMock()

    with (
        patch("stream_edge.workers.matcher.psycopg.connect", side_effect=_fake_connect),
        patch("stream_edge.workers.matcher.register_vector"),
    ):
        _upsert_job_and_score_sync(
            enriched=pt_event,
            scoring_manager=scoring_manager,
            producer=producer,
            byok_encryption_key=fernet_key,
        )

    assert scoring_manager.evaluate_resume_fit_sync.call_count == 1
    eval_kwargs = scoring_manager.evaluate_resume_fit_sync.call_args.kwargs
    assert eval_kwargs["resume_text"] == "Engenheiro Python PT"
    assert eval_kwargs["job_language"] == "pt"
    assert eval_kwargs["resume_language"] == "pt"

    # Verify standardized 64-bit advisory lock & user-level alert_sent_at dedup SQL
    sql_joined = "\n".join(sql for sql, _ in executed_sql)
    assert (
        "pg_advisory_xact_lock(hashtextextended('vektryn:winner:' || %s || ':' || %s, 0))"
        in sql_joined
    )
    assert "other.alert_sent_at IS NOT NULL" in sql_joined

    # Alert carries resume_profile_label and resume_language
    producer._publish_sync.assert_called_once()
    alert_event = producer._publish_sync.call_args.kwargs["event"]
    assert alert_event.resume_profile_uuid == pt_uuid
    assert alert_event.resume_profile_label == "Backend PT-BR"
    assert alert_event.resume_language == "pt"

    # 2. Manual import fallback for submitted_by_user_id when strict_language_match excludes all profiles
    scoring_manager.reset_mock()
    producer.reset_mock()
    manual_event = JobEnrichedEvent(
        ats_source=ATSSource.MANUAL,
        external_id="manual-de-1",
        content_hash="d" * 64,
        title="Backend Engineer DE",
        company_name="BerlinTech",
        apply_url="https://berlintech.example/jobs/1",
        raw_html_gcs_uri="gs://bucket/manual-de.html",
        description_clean="Wir suchen Python Backend Entwickler.",
        seniority=SeniorityLevel.SENIOR,
        contract_type=ContractType.B2B_CONTRACTOR,
        work_mode=WorkMode.ONSITE,
        language="de",
        region_eligibility=[RegionEligibility.EUROPE],
        tech_stack=["python"],
        embedding=[0.1] * EMBEDDING_DIMENSIONS,
        submitted_by_user_id=7,
    )

    cur_manual = MagicMock()
    cur_manual.fetchone.side_effect = [
        None,
        None,
        (job_uuid,),
        (match_uuid, None),
        (match_uuid,),
    ]
    cur_manual.fetchall.return_value = [
        # Submitter user 7: strict EN + remote only -> gates exclude, fallback still scores!
        (
            en_uuid,
            7,
            "Strict EN",
            "English CV",
            "h1" + "0" * 62,
            ["python"],
            ["senior"],
            [],
            ["brazil"],
            70,
            0.40,
            encrypted_key,
            "auto",
            True,
            ["remote"],
            "en",
            True,
            now,
        ),
        # Non-submitter user 8: strict EN + remote only -> normal gates apply -> skipped ($0 BYOK)
        (
            uuid.uuid4(),
            8,
            "Other User Strict EN",
            "Other CV",
            "h9" + "0" * 62,
            ["python"],
            ["senior"],
            [],
            ["brazil"],
            70,
            0.95,
            encrypted_key,
            "auto",
            True,
            ["remote"],
            "en",
            True,
            now,
        ),
    ]

    @contextmanager
    def _fake_manual_connect(*_args, **_kwargs):
        conn = MagicMock()
        conn.cursor.return_value.__enter__.return_value = cur_manual
        yield conn

    with (
        patch(
            "stream_edge.workers.matcher.psycopg.connect",
            side_effect=_fake_manual_connect,
        ),
        patch("stream_edge.workers.matcher.register_vector"),
    ):
        _upsert_job_and_score_sync(
            enriched=manual_event,
            scoring_manager=scoring_manager,
            producer=producer,
            byok_encryption_key=fernet_key,
        )

    assert scoring_manager.evaluate_resume_fit_sync.call_count == 1
    assert scoring_manager.evaluate_resume_fit_sync.call_args.kwargs["user_id"] == 7


def test_rescore_case_a_mandatory_demotion_and_case_b_fresh_reuse() -> None:
    fernet_key = Fernet.generate_key().decode("utf-8")
    encrypted_key = encrypt_api_key("AIzaSyRescoreMultiKey1234567890", fernet_key)
    target_uuid = uuid.uuid4()
    sibling_uuid = uuid.uuid4()
    en_job_uuid = uuid.uuid4()
    de_job_uuid = uuid.uuid4()
    now = datetime(2026, 11, 27, 12, 0, tzinfo=UTC)

    unit_vec = [1.0] + [0.0] * (EMBEDDING_DIMENSIONS - 1)

    executed_sql: list[tuple[str, tuple | None]] = []
    cur = MagicMock()
    cur.execute.side_effect = lambda sql, params=None: executed_sql.append(
        (sql, params)
    )
    # For Case A promotion check (RETURNING uuid -> sibling promoted)
    cur.fetchone.side_effect = [(uuid.uuid4(),)]
    cur.fetchall.side_effect = [
        # Active profiles for user 7: target (DE) and sibling (EN)
        [
            (
                target_uuid,
                7,
                "German CV",
                "hash-de" + "0" * 57,
                ["python"],
                [],
                [],
                [],
                70,
                unit_vec,
                "Backend DE",
                encrypted_key,
                "auto",
                True,
                ["remote"],
                "de",
                False,
                now,
            ),
            (
                sibling_uuid,
                7,
                "English CV",
                "hash-en" + "0" * 57,
                ["python"],
                [],
                [],
                [],
                70,
                unit_vec,
                "Backend EN",
                encrypted_key,
                "auto",
                True,
                ["remote"],
                "en",
                False,
                now,
            ),
        ],
        # Query 1 (stale): EN job where target previously won -> Case A: EN sibling wins, target demoted ($0 BYOK)
        [
            (
                en_job_uuid,
                "Senior Python Engineer",
                "US Co",
                "https://usco.example/1",
                "English job description",
                "senior",
                "b2b_contractor",
                ["worldwide"],
                ["python"],
                0.91,
                "greenhouse",
                "remote",
                "en",
                unit_vec,
                "old-hash" + "0" * 56,
                80,
                True,
            ),
            # Case B1: DE job where target wins AND already has fresh matching hash -> flip only ($0 BYOK)
            (
                de_job_uuid,
                "Backend Entwickler",
                "DE Co",
                "https://deco.example/2",
                "Deutsche Stellenbeschreibung",
                "senior",
                "b2b_contractor",
                ["europe"],
                ["python"],
                0.92,
                "greenhouse",
                "remote",
                "de",
                unit_vec,
                "hash-de" + "0" * 57,
                85,
                False,
            ),
        ],
        # Query 2 (unscored): empty
        [],
    ]

    @contextmanager
    def _fake_connect(*_args, **_kwargs):
        conn = MagicMock()
        conn.cursor.return_value.__enter__.return_value = cur
        yield conn

    scoring_manager = MagicMock()
    scoring_manager.get_pause_state.return_value = None
    producer = MagicMock()

    with (
        patch("stream_edge.workers.matcher.psycopg.connect", side_effect=_fake_connect),
        patch("stream_edge.workers.matcher.register_vector"),
    ):
        processed = _rescore_resume_sync(
            event=JobRescoreEvent(
                resume_profile_uuid=target_uuid,
                user_id=7,
                max_jobs=10,
                force=False,
            ),
            scoring_manager=scoring_manager,
            producer=producer,
            byok_encryption_key=fernet_key,
        )

    assert processed == 2
    # Strictly $0 BYOK spend across both Case A demotion and Case B1 fresh reuse
    scoring_manager.evaluate_resume_fit_sync.assert_not_called()
    producer._publish_sync.assert_not_called()

    # Verify mandatory Case A demotion of target + promotion of sibling + 64-bit lock
    assert any(
        "SET is_routed_winner = FALSE" in sql
        and params is not None
        and target_uuid in params
        for sql, params in executed_sql
    )
    assert any(
        "SET is_routed_winner = TRUE" in sql
        and params is not None
        and sibling_uuid in params
        for sql, params in executed_sql
    )
    assert any(
        "pg_advisory_xact_lock(hashtextextended('vektryn:winner:' || %s || ':' || %s, 0))"
        in sql
        for sql, _ in executed_sql
    )


def test_prefilter_unrestricted_region_widens_multi_resume_union() -> None:
    cur = MagicMock()
    cur.fetchall.return_value = [
        (
            uuid.uuid4(),
            "Backend BR",
            "Senior Python",
            ["python"],
            ["senior"],
            ["pj"],
            ["brazil"],
            ["remote"],
        ),
        (
            uuid.uuid4(),
            "Backend Global",
            "Senior Python",
            ["python", "go"],
            [],
            [],
            [],  # Unrestricted regions/seniority/contracts
            ["remote"],
        ),
    ]
    cur.__enter__.return_value = cur
    conn = MagicMock()
    conn.cursor.return_value = cur
    conn.__enter__.return_value = conn

    with patch("stream_edge.collectors.prefilter.psycopg.connect", return_value=conn):
        criteria = load_resume_criteria()

    assert criteria is not None
    assert "go" in criteria.skills
    assert criteria.target_contract_types == frozenset()
    # Empty db_regions falls back to default broad set rather than narrowing strictly to {"brazil"}
    assert "worldwide" in criteria.target_regions


def test_build_resume_fit_prompt_aligns_output_language() -> None:
    prompt_de = build_resume_fit_prompt(
        resume_text="Python Entwickler",
        resume_skills=["python"],
        job_title="Backend Entwickler",
        company_name="Acme DE",
        job_description="Wir suchen...",
        job_stack=["python"],
        job_language="de",
        resume_language="en",
    )
    assert "ISO 639-1 language 'de'" in prompt_de
    assert "TARGET ROLE LANGUAGE: de" in prompt_de
    assert "CANDIDATE RESUME LANGUAGE: en" in prompt_de

    prompt_fallback = build_resume_fit_prompt(
        resume_text="Engenheiro Python",
        resume_skills=["python"],
        job_title="Backend",
        company_name="Acme",
        job_description="Short",
        job_stack=["python"],
        job_language=UNKNOWN_LANGUAGE,
        resume_language="pt",
    )
    assert "ISO 639-1 language 'pt'" in prompt_fallback


async def test_enrichment_sanitizes_non_iso_salary_currency_like_unknown() -> None:
    assert normalize_salary_currency("unknown") == ""
    assert normalize_salary_currency("N/A") == ""
    assert normalize_salary_currency("usd") == "USD"
    assert normalize_salary_currency("R$") == "BRL"
    assert normalize_salary_currency("€") == "EUR"
    assert normalize_salary_currency("£") == "GBP"
    assert normalize_salary_currency("$") == "USD"
    assert normalize_salary_currency(None) == ""

    raw = JobRawEvent(
        ats_source=ATSSource.MANUAL,
        external_id="manual-currency-unknown",
        content_hash="a" * 64,
        title="Senior Python Distributed Systems Engineer",
        company_name="Acme",
        apply_url="https://acme.example/jobs/1",
        raw_html_gcs_uri="local://manual/currency",
        location_raw="Remote",
        description_clean="We build distributed Python and Kafka pipelines at scale.",
        submitted_by_user_id="1",
    )
    gemini = MagicMock()
    gemini.extract_job_metadata = AsyncMock(
        return_value=ExtractedJobMetadata(
            seniority=SeniorityLevel.SENIOR,
            contract_type=ContractType.B2B_CONTRACTOR,
            work_mode=WorkMode.REMOTE,
            language="en",
            salary_currency="unknown",
            tech_stack=["python", "kafka"],
        )
    )
    gemini.embed_job_text = AsyncMock(return_value=[0.1] * EMBEDDING_DIMENSIONS)

    redis_client = MagicMock()
    redis_client.acquire_content_hash = AsyncMock(return_value=True)
    redis_client.acquire_enrichment_daily_quota = AsyncMock(return_value=True)

    producer = MagicMock()
    producer.publish = AsyncMock()

    await process_raw_message(
        raw_bytes=raw.model_dump_json().encode("utf-8"),
        gemini=gemini,
        redis_client=redis_client,
        producer=producer,
    )

    published_event: JobEnrichedEvent = producer.publish.call_args.kwargs["event"]
    assert published_event.salary_currency == ""
    assert published_event.language == "en"
