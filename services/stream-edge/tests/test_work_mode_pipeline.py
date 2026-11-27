"""Tests for Spec #20 Work Mode prefiltering, Gemini enrichment, and matcher gating."""

import asyncio
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
import uuid

from cryptography.fernet import Fernet
import httpx
import pytest

from stream_edge.clients.gemini import ExtractedJobMetadata, GeminiStreamClient
from stream_edge.collectors.ats_boards import (
    BreezyCollector,
    RecruiteeCollector,
    SmartRecruitersCollector,
    WorkableCollector,
)
from stream_edge.collectors.base import CollectedJob
from stream_edge.collectors.prefilter import (
    ResumeFilterCriteria,
    _cached_word_patterns,
    detect_deterministic_work_mode,
    filter_and_rank_jobs,
    load_resume_criteria,
)
from stream_edge.collectors.remote_feeds import MultiCompanyFeedCollector
from stream_edge.workers.enrichment import process_raw_message
from stream_edge.workers.matcher import (
    _matches_profile_constraints,
    _rescore_resume_sync,
    _upsert_job_and_score_sync,
)
from vektryn_contracts import (
    EMBEDDING_DIMENSIONS,
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


def _collected_job(
    *,
    external_id: str,
    title: str = "Senior Python Backend Engineer",
    location_raw: str = "Brazil",
    description_clean: str = "Build Python, Django, PostgreSQL, and Kafka APIs.",
    ats_source: ATSSource = ATSSource.GREENHOUSE,
    work_mode_hint: str = "",
) -> CollectedJob:
    return CollectedJob(
        ats_source=ats_source,
        external_id=external_id,
        title=title,
        company_name="Acme Cloud",
        apply_url=f"https://example.com/jobs/{external_id}",
        location_raw=location_raw,
        raw_html=f"<p>{description_clean}</p>",
        description_clean=description_clean,
        work_mode_hint=work_mode_hint,
    )


def _criteria(target_work_modes: set[str] | frozenset[str]) -> ResumeFilterCriteria:
    return ResumeFilterCriteria(
        resume_ids=("r1",),
        skills=frozenset({"python", "django", "postgresql"}),
        target_seniority=frozenset({"senior"}),
        target_contract_types=frozenset(),
        target_regions=frozenset({"brazil", "latam", "worldwide"}),
        active_disciplines=frozenset({"backend"}),
        target_work_modes=frozenset(target_work_modes),
    )


def test_prefilter_work_mode_detection_and_strict_drop_rules():
    # Deterministic EN + PT + ATS metadata detection
    assert (
        detect_deterministic_work_mode(
            _collected_job(external_id="1", location_raw="São Paulo, SP - Presencial")
        )
        == WorkMode.ONSITE
    )
    assert (
        detect_deterministic_work_mode(
            _collected_job(external_id="2", location_raw="São Paulo, SP (Híbrido)")
        )
        == WorkMode.HYBRID
    )
    assert (
        detect_deterministic_work_mode(
            _collected_job(external_id="3", work_mode_hint="OnSite")
        )
        == WorkMode.ONSITE
    )
    assert (
        detect_deterministic_work_mode(
            _collected_job(external_id="4", location_raw="Brazil, Home Office")
        )
        == WorkMode.REMOTE
    )
    assert (
        detect_deterministic_work_mode(
            _collected_job(external_id="5", location_raw="São Paulo, SP")
        )
        == WorkMode.UNKNOWN
    )

    jobs = [
        _collected_job(external_id="remote", location_raw="Remote - Brazil"),
        _collected_job(
            external_id="unlabeled",
            location_raw="São Paulo, SP",
            description_clean="Python Django engineer. Modelo híbrido 3x/semana.",
        ),
        _collected_job(external_id="hybrid_pt", location_raw="São Paulo - Híbrido"),
        _collected_job(external_id="onsite_en", location_raw="Brazil - In-Office"),
        _collected_job(
            external_id="ats_onsite",
            location_raw="Brazil",
            work_mode_hint="OnSite",
        ),
        _collected_job(
            external_id="manual_onsite",
            ats_source=ATSSource.MANUAL,
            location_raw="São Paulo - Presencial",
            work_mode_hint="OnSite",
        ),
    ]

    # Remote-only users drop deterministic hybrid/onsite, keep remote + unlabeled + manual
    remote_only = filter_and_rank_jobs(jobs, _criteria({"remote"}))
    assert {j.external_id for j in remote_only} == {
        "remote",
        "unlabeled",
        "manual_onsite",
    }

    # Opting into hybrid keeps hybrid_pt while still dropping onsite
    remote_and_hybrid = filter_and_rank_jobs(jobs, _criteria({"remote", "hybrid"}))
    assert {j.external_id for j in remote_and_hybrid} == {
        "remote",
        "unlabeled",
        "hybrid_pt",
        "manual_onsite",
    }

    # Empty target_work_modes ([]) is unrestricted and keeps everything
    unrestricted = filter_and_rank_jobs(jobs, _criteria(set()))
    assert len(unrestricted) == len(jobs)


def test_load_resume_criteria_unions_work_modes_and_respects_empty_unrestricted():
    def _mock_connect_with_rows(rows):
        cur = MagicMock()
        cur.fetchall.return_value = rows
        cur.__enter__.return_value = cur
        conn = MagicMock()
        conn.cursor.return_value = cur
        conn.__enter__.return_value = conn
        return conn

    # Two restricted profiles -> union {"remote", "hybrid"}
    rows_restricted = [
        (
            uuid.uuid4(),
            "Backend",
            "Python Django",
            ["python", "django"],
            ["senior"],
            [],
            ["brazil"],
            ["remote"],
        ),
        (
            uuid.uuid4(),
            "Backend 2",
            "Python FastAPI",
            ["python"],
            ["senior"],
            [],
            ["brazil"],
            ["hybrid"],
        ),
    ]
    with patch(
        "stream_edge.collectors.prefilter.psycopg.connect",
        return_value=_mock_connect_with_rows(rows_restricted),
    ):
        criteria = load_resume_criteria()
    assert criteria is not None
    assert criteria.target_work_modes == frozenset({"remote", "hybrid"})

    # One restricted + one empty [] -> unrestricted (empty frozenset)
    rows_unrestricted = [
        rows_restricted[0],
        (
            uuid.uuid4(),
            "Open",
            "Python",
            ["python"],
            ["senior"],
            [],
            ["brazil"],
            [],
        ),
    ]
    with patch(
        "stream_edge.collectors.prefilter.psycopg.connect",
        return_value=_mock_connect_with_rows(rows_unrestricted),
    ):
        criteria_open = load_resume_criteria()
    assert criteria_open is not None
    assert criteria_open.target_work_modes == frozenset()


def test_enrichment_extracts_work_mode_across_en_and_pt_and_publishes_event():
    captured_prompts: list[str] = []

    def _make_fake_client(work_mode_value: str) -> GeminiStreamClient:
        fake_sdk = MagicMock()

        def _fake_generate(*, model, contents, config):
            assert not model.startswith("gemini-2.5")
            assert config.thinking_config is not None
            captured_prompts.append(contents)
            return SimpleNamespace(
                text=ExtractedJobMetadata(
                    seniority=SeniorityLevel.SENIOR,
                    contract_type=ContractType.PJ,
                    work_mode=WorkMode(work_mode_value),
                    region_eligibility=[RegionEligibility.BRAZIL],
                    tech_stack=["python", "django"],
                ).model_dump_json()
            )

        fake_sdk.models.generate_content.side_effect = _fake_generate
        with patch("stream_edge.clients.gemini.genai.Client", return_value=fake_sdk):
            return GeminiStreamClient(api_key="AIzaSyFakeEnrichKey1234567890")

    cases = [
        ("São Paulo, SP", "Vaga 100% presencial em Pinheiros.", WorkMode.ONSITE),
        ("Brazil", "Atuação em modelo híbrido 3x/semana.", WorkMode.HYBRID),
        ("Brazil", "Posição 100% remoto / home office.", WorkMode.REMOTE),
        ("São Paulo, SP", "Buscamos dev Python sênior para APIs.", WorkMode.UNKNOWN),
    ]

    for loc, desc, expected in cases:
        client = _make_fake_client(expected.value)
        meta = asyncio.run(
            client.extract_job_metadata(
                title="Senior Python Engineer",
                company_name="Acme BR",
                location_raw=loc,
                description_clean=desc,
            )
        )
        assert meta.work_mode == expected

    assert any("modelo híbrido" in p and "unknown" in p for p in captured_prompts)

    # End-to-end process_raw_message forwards work_mode onto JobEnrichedEvent
    raw = JobRawEvent(
        ats_source=ATSSource.GUPY,
        external_id="gupy-42",
        content_hash="f" * 64,
        title="Engenheiro Python",
        company_name="Acme BR",
        apply_url="https://acme.gupy.io/jobs/42",
        raw_html_gcs_uri="gs://bucket/gupy-42.html",
        location_raw="São Paulo, SP",
        description_clean="Trabalho 100% remoto.",
    )
    mock_gemini = MagicMock()
    mock_gemini.extract_job_metadata = AsyncMock(
        return_value=ExtractedJobMetadata(
            seniority=SeniorityLevel.SENIOR,
            contract_type=ContractType.CLT,
            work_mode=WorkMode.REMOTE,
            region_eligibility=[RegionEligibility.BRAZIL],
            tech_stack=["python"],
        )
    )
    mock_gemini.embed_job_text = AsyncMock(return_value=[0.05] * EMBEDDING_DIMENSIONS)
    mock_redis = MagicMock()
    mock_redis.acquire_content_hash = AsyncMock(return_value=True)
    mock_redis.try_consume_enrichment_daily_quota = AsyncMock(return_value=(True, 1))
    mock_producer = MagicMock()
    mock_producer.publish = AsyncMock()

    asyncio.run(
        process_raw_message(
            raw_bytes=raw.model_dump_json().encode("utf-8"),
            gemini=mock_gemini,
            redis_client=mock_redis,
            producer=mock_producer,
        )
    )
    published = mock_producer.publish.call_args.kwargs["event"]
    assert isinstance(published, JobEnrichedEvent)
    assert published.work_mode == WorkMode.REMOTE


def test_matcher_profile_constraints_strictly_gates_work_modes():
    common = {
        "seniority": "senior",
        "contract_type": "pj",
        "region_eligibility": ["brazil"],
        "target_seniority": ["senior"],
        "target_contract_types": ["pj"],
        "target_regions": ["brazil"],
    }
    assert (
        _matches_profile_constraints(
            **common, work_mode="remote", target_work_modes=["remote"]
        )
        is True
    )
    assert (
        _matches_profile_constraints(
            **common, work_mode="hybrid", target_work_modes=["remote"]
        )
        is False
    )
    assert (
        _matches_profile_constraints(
            **common, work_mode="onsite", target_work_modes=["remote"]
        )
        is False
    )
    # Critical Spec #20 invariant: unknown is skipped when unchecked, scored when checked
    assert (
        _matches_profile_constraints(
            **common, work_mode="unknown", target_work_modes=["remote"]
        )
        is False
    )
    assert (
        _matches_profile_constraints(
            **common, work_mode="unknown", target_work_modes=["remote", "unknown"]
        )
        is True
    )
    # Empty list [] is unrestricted
    assert (
        _matches_profile_constraints(**common, work_mode="onsite", target_work_modes=[])
        is True
    )


@pytest.mark.parametrize(
    ("job_mode", "target_modes", "expect_scored"),
    [
        (WorkMode.REMOTE, ["remote"], True),
        (WorkMode.HYBRID, ["remote"], False),
        (WorkMode.UNKNOWN, ["remote"], False),
        (WorkMode.UNKNOWN, ["remote", "unknown"], True),
        (WorkMode.ONSITE, [], True),
    ],
)
def test_matcher_live_and_rescore_enforce_target_work_modes(
    job_mode: WorkMode,
    target_modes: list[str],
    expect_scored: bool,
):
    fernet_key = Fernet.generate_key().decode("utf-8")
    encrypted_key = encrypt_api_key("AIzaSyMatcherWorkModeKey1234567890", fernet_key)
    job_uuid = uuid.uuid4()
    resume_uuid = uuid.uuid4()
    match_uuid = uuid.uuid4()

    enriched = JobEnrichedEvent(
        ats_source=ATSSource.GREENHOUSE,
        external_id=f"wm-{job_mode.value}",
        content_hash="e" * 64,
        title="Senior Python Backend Engineer",
        company_name="Acme Cloud",
        apply_url="https://example.com/jobs/wm",
        raw_html_gcs_uri="gs://bucket/wm.html",
        location_raw="Brazil",
        description_clean="Build Python Django APIs.",
        seniority=SeniorityLevel.SENIOR,
        contract_type=ContractType.PJ,
        work_mode=job_mode,
        region_eligibility=[RegionEligibility.BRAZIL],
        tech_stack=["python", "django"],
        embedding=[0.1] * EMBEDDING_DIMENSIONS,
    )

    # 1. Live jobs.enriched path
    executed_sql: list[tuple[str, tuple]] = []
    cur = MagicMock()

    def _live_execute(sql, params=None):
        executed_sql.append((sql, params))

    cur.execute.side_effect = _live_execute
    cur.fetchone.side_effect = [
        (job_uuid,),
        (match_uuid, None),
        (match_uuid,),
    ]
    cur.fetchall.return_value = [
        (
            resume_uuid,
            7,
            "Backend CV",
            "Senior Python engineer",
            "h" * 64,
            ["python", "django"],
            ["senior"],
            ["pj"],
            ["brazil"],
            70,
            0.91,
            encrypted_key,
            "auto",
            True,
            target_modes,
        )
    ]

    @contextmanager
    def _fake_connect(*_args, **_kwargs):
        conn = MagicMock()
        conn.cursor.return_value.__enter__.return_value = cur
        yield conn

    scoring_manager = MagicMock()
    scoring_manager.evaluate_resume_fit_sync.return_value = (
        SimpleNamespace(
            fit_score=88,
            matched_skills=["python"],
            missing_keywords=[],
            talking_points=["Built APIs"],
            gap_summary="Strong fit.",
            fit_highlights=["Python match"],
            watchout_note="",
        ),
        "gemini-3.5-flash-lite",
    )
    scoring_manager.get_pause_state.return_value = None
    producer = MagicMock()

    with (
        patch("stream_edge.workers.matcher.psycopg.connect", side_effect=_fake_connect),
        patch("stream_edge.workers.matcher.register_vector"),
    ):
        _upsert_job_and_score_sync(
            enriched=enriched,
            scoring_manager=scoring_manager,
            producer=producer,
            byok_encryption_key=fernet_key,
        )

    # Confirm work_mode was persisted in JobPosting UPSERT
    upsert_sql, upsert_params = executed_sql[0]
    assert "work_mode" in upsert_sql
    assert job_mode.value in upsert_params

    if expect_scored:
        scoring_manager.evaluate_resume_fit_sync.assert_called_once()
        producer._publish_sync.assert_called_once()
    else:
        scoring_manager.evaluate_resume_fit_sync.assert_not_called()
        producer._publish_sync.assert_not_called()

    # 2. Retroactive jobs.rescore path
    scoring_manager.reset_mock()
    producer.reset_mock()
    rescore_cur = MagicMock()
    rescore_cur.fetchone.side_effect = [
        (
            resume_uuid,
            7,
            "Senior Python engineer",
            "h" * 64,
            ["python", "django"],
            ["senior"],
            ["pj"],
            ["brazil"],
            70,
            [0.1] * EMBEDDING_DIMENSIONS,
            "Backend CV",
            encrypted_key,
            "auto",
            True,
            target_modes,
        ),
        (match_uuid, None),
        (match_uuid,),
    ]
    rescore_cur.fetchall.return_value = [
        (
            job_uuid,
            enriched.title,
            enriched.company_name,
            str(enriched.apply_url),
            enriched.description_clean,
            enriched.seniority.value,
            enriched.contract_type.value,
            ["brazil"],
            ["python", "django"],
            0.91,
            enriched.ats_source.value,
            job_mode.value,
        )
    ]

    @contextmanager
    def _fake_rescore_connect(*_args, **_kwargs):
        conn = MagicMock()
        conn.cursor.return_value.__enter__.return_value = rescore_cur
        yield conn

    event = JobRescoreEvent(
        resume_profile_uuid=resume_uuid, user_id=7, max_jobs=10, force=True
    )
    with (
        patch(
            "stream_edge.workers.matcher.psycopg.connect",
            side_effect=_fake_rescore_connect,
        ),
        patch("stream_edge.workers.matcher.register_vector"),
    ):
        _rescore_resume_sync(
            event=event,
            scoring_manager=scoring_manager,
            producer=producer,
            byok_encryption_key=fernet_key,
        )

    if expect_scored:
        scoring_manager.evaluate_resume_fit_sync.assert_called_once()
        producer._publish_sync.assert_called_once()
    else:
        scoring_manager.evaluate_resume_fit_sync.assert_not_called()
        producer._publish_sync.assert_not_called()


def test_prefilter_supports_ui_ux_qa_disciplines_and_non_alnum_word_boundaries():
    # Non-alphanumeric terms like c++ and ui/ux compile cleanly and match properly
    cpp_pat, uiux_pat = _cached_word_patterns(("c++", "ui/ux"))
    assert cpp_pat.search("Strong C++ systems programming experience") is not None
    assert cpp_pat.search("Ac++b") is None
    assert uiux_pat.search("Senior UI/UX Product Designer") is not None

    # UI/UX discipline filtering
    uiux_criteria = ResumeFilterCriteria(
        resume_ids=("r-ux",),
        skills=frozenset({"figma", "storybook", "design systems", "accessibility"}),
        target_seniority=frozenset({"senior"}),
        target_contract_types=frozenset(),
        target_regions=frozenset({"brazil", "worldwide"}),
        active_disciplines=frozenset({"ui_ux"}),
        target_work_modes=frozenset({"remote"}),
    )
    ux_jobs = [
        _collected_job(
            external_id="ux-1",
            title="Senior Product Designer (UI/UX)",
            location_raw="Remote - Brazil",
            description_clean="Own Figma design systems, Storybook components, and WCAG accessibility.",
        ),
        _collected_job(
            external_id="be-1",
            title="Senior Backend Engineer",
            location_raw="Remote - Brazil",
            description_clean="Build Python and PostgreSQL microservices.",
        ),
    ]
    ux_filtered = filter_and_rank_jobs(ux_jobs, uiux_criteria)
    assert [j.external_id for j in ux_filtered] == ["ux-1"]

    # QA / SDET discipline filtering (EN + PT)
    qa_criteria = ResumeFilterCriteria(
        resume_ids=("r-qa",),
        skills=frozenset({"playwright", "cypress", "k6", "pytest"}),
        target_seniority=frozenset({"senior"}),
        target_contract_types=frozenset(),
        target_regions=frozenset({"brazil", "worldwide"}),
        active_disciplines=frozenset({"qa"}),
        target_work_modes=frozenset({"remote"}),
    )
    qa_jobs = [
        _collected_job(
            external_id="qa-1",
            title="Analista de Testes Sênior (QA / SDET)",
            location_raw="Remoto - Brasil",
            description_clean="Automação de testes com Playwright, Cypress e testes de carga com k6.",
        ),
        _collected_job(
            external_id="ux-2",
            title="Senior Product Designer",
            location_raw="Remote",
            description_clean="Figma prototyping and design systems.",
        ),
    ]
    qa_filtered = filter_and_rank_jobs(qa_jobs, qa_criteria)
    assert [j.external_id for j in qa_filtered] == ["qa-1"]


def _mock_ats_board_response(request: httpx.Request) -> httpx.Response:
    url = str(request.url)
    if "apply.workable.com" in url:
        return httpx.Response(
            200,
            json={
                "name": "Acme",
                "jobs": [
                    {
                        "shortcode": "w1",
                        "title": "QA Engineer",
                        "country": "Brazil",
                        "telecommuting": True,
                        "description": "<p>Playwright</p>",
                        "url": "https://apply.workable.com/acme/j/w1",
                    },
                    {
                        "shortcode": "w2",
                        "title": "QA Engineer Onsite",
                        "city": "SP",
                        "telecommuting": False,
                        "description": "<p>Playwright</p>",
                        "url": "https://apply.workable.com/acme/j/w2",
                    },
                ],
            },
        )
    if "api.smartrecruiters.com" in url and "/postings/sr1" not in url:
        return httpx.Response(
            200,
            json={
                "content": [
                    {
                        "id": "sr1",
                        "name": "Product Designer",
                        "company": {"name": "Acme"},
                        "location": {"fullLocation": "Brazil", "remote": True},
                    }
                ]
            },
        )
    if "api.smartrecruiters.com" in url:
        return httpx.Response(
            200,
            json={"jobAd": {"sections": {"job": {"text": "<p>Figma</p>"}}}},
        )
    if "recruitee.com" in url:
        return httpx.Response(
            200,
            json={
                "offers": [
                    {
                        "id": 10,
                        "title": "SDET",
                        "company_name": "Acme",
                        "careers_url": "https://acme.recruitee.com/o/sdet",
                        "location": "Brazil",
                        "remote": True,
                        "description": "<p>Cypress</p>",
                    }
                ]
            },
        )
    if "breezy.hr/json" in url:
        return httpx.Response(
            200,
            json=[
                {
                    "id": "b1",
                    "name": "Design Engineer",
                    "url": "https://acme.breezy.hr/p/b1",
                    "company": {"name": "Acme"},
                    "location": {"name": "Brazil", "is_remote": True},
                }
            ],
        )
    return httpx.Response(200, text="<main>Storybook and Figma</main>")


def test_ats_board_collectors_populate_remote_work_mode_hint():
    async def _run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(_mock_ats_board_response)
        ) as http_client:
            w_jobs = await WorkableCollector(http_client).fetch_board("acme", "Acme")
            sr_jobs = await SmartRecruitersCollector(http_client).fetch_board(
                "acme", "Acme"
            )
            r_jobs = await RecruiteeCollector(http_client).fetch_board("acme", "Acme")
            b_jobs = await BreezyCollector(http_client).fetch_board("acme", "Acme")

        assert [j.work_mode_hint for j in w_jobs] == ["Remote", ""]
        assert sr_jobs[0].work_mode_hint == "Remote"
        assert r_jobs[0].work_mode_hint == "Remote"
        assert b_jobs[0].work_mode_hint == "Remote"

    asyncio.run(_run())


def test_remote_feeds_fetch_design_and_qa_categories():
    called_urls: list[str] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        called_urls.append(str(request.url))
        if "github.com" in str(request.url) or "trampos.co" in str(request.url):
            return httpx.Response(200, json=[])
        return httpx.Response(200, json={"jobs": [], "data": []})

    async def _run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(_handler)
        ) as http_client:
            collector = MultiCompanyFeedCollector(http_client)
            await collector.fetch_all_with_stats()

    asyncio.run(_run())

    joined = "\n".join(called_urls)
    assert "remotive.com/api/remote-jobs?category=design" in joined
    assert "remotive.com/api/remote-jobs?category=qa" in joined
    assert "jobicy.com/api/v2/remote-jobs?count=50&tag=design" in joined
    assert "jobicy.com/api/v2/remote-jobs?count=50&tag=qa" in joined
    assert "portal.gupy.io/api/job-search/jobs?jobName=ux" in joined
    assert "portal.gupy.io/api/job-search/jobs?jobName=designer" in joined
    assert "portal.gupy.io/api/job-search/jobs?jobName=qa" in joined
