"""Comprehensive tests for Spec #22 cross-source dedup, reposts, and source-aware lifecycle."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
import uuid

from cryptography.fernet import Fernet
import httpx
import pytest

from stream_edge.clients.gemini import ExtractedJobMetadata
from stream_edge.clients.redis import DedupRedisClient
from stream_edge.collectors.base import CollectedJob
from stream_edge.collectors.run import (
    _pre_dedup_against_postgres_sync,
    deduplicate_scored_batch,
)
from stream_edge.workers import enrichment, lifecycle, matcher
from vektryn_contracts import (
    AGGREGATOR_TIER,
    DIRECT_ATS_TIER,
    EMBEDDING_DIMENSIONS,
    ATSSource,
    ContractType,
    JobEnrichedEvent,
    JobRawEvent,
    RegionEligibility,
    SalaryPeriod,
    SeniorityLevel,
    WorkMode,
    compute_description_fingerprint,
    compute_job_content_hash,
    encrypt_api_key,
    normalize_company_for_dedup,
    normalize_title_for_dedup,
)

LONG_DESC = (
    "We are hiring a Senior Backend Python Engineer to build event-driven "
    "microservices with Django, PostgreSQL, pgvector, Redis, and Kafka. "
    "You will lead technical design reviews and own reliability at scale."
)


def _make_collected(
    *,
    ats_source: ATSSource,
    external_id: str,
    title: str = "Senior Backend Python Engineer (Remote)",
    company_name: str = "Acme, Inc.",
    apply_url: str = "https://boards.greenhouse.io/acme/jobs/1",
    description_clean: str = LONG_DESC,
    location_raw: str = "Remote - Worldwide",
    work_mode_hint: str = "remote",
) -> CollectedJob:
    return CollectedJob(
        ats_source=ats_source,
        external_id=external_id,
        title=title,
        company_name=company_name,
        apply_url=apply_url,
        location_raw=location_raw,
        raw_html=f"<p>{description_clean}</p>",
        description_clean=description_clean,
        work_mode_hint=work_mode_hint,
    )


def _make_enriched(
    *,
    ats_source: ATSSource = ATSSource.GREENHOUSE,
    external_id: str = "gh-1",
    title: str = "Senior Backend Python Engineer (Remote)",
    company_name: str = "Acme, Inc.",
    apply_url: str = "https://boards.greenhouse.io/acme/jobs/1",
    description_clean: str = LONG_DESC,
    seniority: SeniorityLevel = SeniorityLevel.SENIOR,
    contract_type: ContractType = ContractType.B2B_CONTRACTOR,
    work_mode: WorkMode = WorkMode.REMOTE,
    language: str = "en",
    region_eligibility: list[RegionEligibility] | None = None,
    salary_min: int | None = None,
    salary_max: int | None = None,
    salary_currency: str = "",
    salary_period: SalaryPeriod | None = None,
    tech_stack: list[str] | None = None,
    submitted_by_user_id: int | None = None,
) -> JobEnrichedEvent:
    return JobEnrichedEvent(
        ats_source=ats_source,
        external_id=external_id,
        content_hash=compute_job_content_hash(
            ats_source, title, company_name, description_clean
        ),
        title=title,
        company_name=company_name,
        apply_url=apply_url,
        raw_html_gcs_uri=f"gs://bucket/{external_id}.html",
        location_raw="Remote",
        description_clean=description_clean,
        seniority=seniority,
        contract_type=contract_type,
        work_mode=work_mode,
        language=language,
        region_eligibility=region_eligibility or [RegionEligibility.WORLDWIDE],
        salary_min=salary_min,
        salary_max=salary_max,
        salary_currency=salary_currency,
        salary_period=salary_period,
        tech_stack=tech_stack or ["python", "kafka"],
        embedding=[0.1] * EMBEDDING_DIMENSIONS,
        submitted_by_user_id=submitted_by_user_id,
    )


def _canonical_row(
    *,
    job_uuid: uuid.UUID | None = None,
    ats_source: str = "remotive",
    external_id: str = "rem-1",
    title: str = "Senior Backend Python Engineer - Worldwide",
    company_name: str = "Acme Corp.",
    apply_url: str = "https://remotive.com/jobs/rem-1",
    description_clean: str = LONG_DESC,
    seniority: str = "senior",
    contract_type: str = "unknown",
    work_mode: str = "unknown",
    language: str = "en",
    region_eligibility: list[str] | None = None,
    salary_min=None,
    salary_max=None,
    salary_currency: str = "",
    salary_period: str | None = None,
    tech_stack: list[str] | None = None,
    is_active: bool = True,
    repost_count: int = 0,
    last_reposted_at: datetime | None = None,
    created_at: datetime | None = None,
    cosine_sim: float = 0.97,
    primary_ats_source: str | None = None,
) -> tuple:
    uid = job_uuid or uuid.uuid4()
    fp, _ = compute_description_fingerprint(description_clean)
    base = (
        uid,
        ats_source,
        external_id,
        title,
        company_name,
        apply_url,
        description_clean,
        seniority,
        contract_type,
        work_mode,
        language,
        region_eligibility or ["latam"],
        salary_min,
        salary_max,
        salary_currency,
        salary_period,
        tech_stack or ["python"],
        is_active,
        repost_count,
        last_reposted_at,
        created_at or datetime(2026, 11, 1, 12, 0, tzinfo=UTC),
        normalize_company_for_dedup(company_name),
        normalize_title_for_dedup(title),
        fp,
    )
    return (*base, cosine_sim, primary_ats_source or ats_source)


def test_layer1_priority_cluster_dedup_keeps_best_relevance_and_direct_ats_winner() -> (
    None
):
    remotive_dup = _make_collected(
        ats_source=ATSSource.REMOTIVE,
        external_id="rem-1",
        company_name="Acme Corp.",
        apply_url="https://remotive.com/jobs/1",
    )
    greenhouse_dup = _make_collected(
        ats_source=ATSSource.GREENHOUSE,
        external_id="gh-1",
        company_name="Acme, Inc.",
        apply_url="https://boards.greenhouse.io/acme/jobs/1",
    )
    high_rel_aggregator = _make_collected(
        ats_source=ATSSource.HIMALAYAS,
        external_id="him-99",
        title="Staff Distributed Systems Engineer",
        company_name="Stripe",
        apply_url="https://himalayas.app/jobs/99",
        description_clean=(
            "Join Stripe to build global payment processing infrastructure in Go, "
            "Python, Kafka, and PostgreSQL with strict latency budgets and high reliability."
        ),
    )
    low_rel_direct = _make_collected(
        ats_source=ATSSource.ASHBY,
        external_id="ash-2",
        title="Junior Frontend Developer",
        company_name="Linear",
        apply_url="https://jobs.ashbyhq.com/linear/2",
        description_clean=(
            "Build reactive web interfaces in TypeScript, CSS, and React for modern "
            "issue tracking workflows with crisp keyboard-first UX and sub-50ms rendering."
        ),
    )

    surviving, deduped = deduplicate_scored_batch(
        [
            (95, high_rel_aggregator),
            (85, remotive_dup),
            (70, greenhouse_dup),
            (20, low_rel_direct),
        ]
    )

    assert len(deduped) == 1
    assert deduped[0].ats_source == ATSSource.REMOTIVE
    # Surviving order: Stripe (95) -> Acme Greenhouse (inherits cluster max 85) -> Linear Ashby (20)
    assert [job.external_id for _, job in surviving] == ["him-99", "gh-1", "ash-2"]
    assert [score for score, _ in surviving] == [95, 85, 20]


def test_layer1_postgres_prededup_attaches_source_promotes_direct_ats_and_passes_closed(
    monkeypatch,
) -> None:
    canonical_uuid = uuid.uuid4()
    remotive_src_uuid = uuid.uuid4()
    now = datetime(2026, 11, 28, 12, 0, tzinfo=UTC)
    fp, _ = compute_description_fingerprint(LONG_DESC)
    executed_sql: list[str] = []

    class _FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, sql, params=None):
            executed_sql.append(sql)
            self._sql = sql

        def fetchall(self):
            if "FROM jobs_jobpostingsource s" in self._sql:
                # closed-job pair returns is_active=False -> must pass through!
                return [(uuid.uuid4(), "greenhouse", "gh-closed", False)]
            if "SELECT content_hash" in self._sql:
                return []
            if (
                "FROM jobs_jobposting" in self._sql
                and "description_fingerprint" in self._sql
            ):
                return [
                    (
                        canonical_uuid,
                        "acme",
                        "senior backend python engineer",
                        fp,
                        LONG_DESC,
                        "remote",
                        now - timedelta(days=3),
                        None,
                        0,
                    )
                ]
            return []

        def fetchone(self):
            if "WHERE ats_source = %s" in self._sql:
                return None  # incoming greenhouse source not yet linked
            if "AND is_primary = TRUE" in self._sql:
                return (remotive_src_uuid, "remotive", True)
            if "AND external_id <> %s" in self._sql:
                return None
            return None

    class _FakeConn:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def cursor(self):
            return _FakeCursor()

        def commit(self):
            # Intentionally no-op: in-memory connection double for unit tests.
            pass

    monkeypatch.setattr(
        "stream_edge.collectors.run.psycopg.connect", lambda *_a, **_kw: _FakeConn()
    )

    gh_incoming = _make_collected(
        ats_source=ATSSource.GREENHOUSE,
        external_id="gh-new-primary",
        company_name="Acme, Inc.",
        apply_url="https://boards.greenhouse.io/acme/jobs/new",
    )
    closed_reappearing = _make_collected(
        ats_source=ATSSource.GREENHOUSE,
        external_id="gh-closed",
        company_name="OtherCo",
        apply_url="https://boards.greenhouse.io/other/jobs/closed",
        description_clean=f"{LONG_DESC} OtherCo reopened role.",
    )

    deduped_hashes, deduped_pairs = _pre_dedup_against_postgres_sync(
        [gh_incoming, closed_reappearing]
    )

    assert ("greenhouse", "gh-new-primary") in deduped_pairs
    # Closed canonical posting MUST pass through Layer 1 to Stage 0
    assert ("greenhouse", "gh-closed") not in deduped_pairs
    assert not deduped_hashes

    # Verify advisory lock + two-step primary swap SQL order
    joined = "\n".join(executed_sql)
    assert "pg_advisory_xact_lock" in joined
    clear_idx = next(
        i for i, s in enumerate(executed_sql) if "SET is_primary = FALSE" in s
    )
    promote_idx = next(
        i for i, s in enumerate(executed_sql) if "SET is_primary = TRUE" in s
    )
    assert clear_idx < promote_idx


@pytest.mark.asyncio
async def test_enrichment_tier_aware_redis_wave_guard() -> None:
    wave_store: dict[str, int] = {}

    class _FakeRedis(DedupRedisClient):
        def __init__(self) -> None:
            self.hashes: set[str] = set()
            self.quota_calls = 0

        async def acquire_content_hash(
            self, content_hash: str, ttl_seconds: int = 1
        ) -> bool:
            if content_hash in self.hashes:
                return False
            self.hashes.add(content_hash)
            return True

        async def release_content_hash(self, content_hash: str) -> None:
            self.hashes.discard(content_hash)

        async def claim_wave_fingerprint(
            self,
            company_norm: str,
            description_fingerprint: str,
            source_tier: int,
            ttl_seconds: int = 1,
        ) -> tuple[bool, int | None]:
            key = f"{company_norm}:{description_fingerprint}"
            if key not in wave_store:
                wave_store[key] = source_tier
                return True, None
            cached = wave_store[key]
            if source_tier < cached:
                wave_store[key] = source_tier
                return True, cached
            return False, cached

        async def try_consume_enrichment_daily_quota(self, *, daily_cap: int, now=None):
            self.quota_calls += 1
            return True, self.quota_calls

    fake_redis = _FakeRedis()
    mock_gemini = MagicMock()
    mock_gemini.extract_job_metadata = AsyncMock(
        return_value=ExtractedJobMetadata(work_mode=WorkMode.REMOTE, language="en")
    )
    mock_gemini.embed_job_text = AsyncMock(return_value=[0.1] * EMBEDDING_DIMENSIONS)
    mock_producer = MagicMock()
    mock_producer.publish = AsyncMock()

    # 1. Aggregator (Remotive, tier=20) arrives first -> allowed
    rem_raw = JobRawEvent(
        ats_source=ATSSource.REMOTIVE,
        external_id="rem-w1",
        content_hash="1" * 64,
        title="Senior Backend Python Engineer",
        company_name="Acme Corp.",
        apply_url="https://remotive.com/jobs/w1",
        raw_html_gcs_uri="gs://b/1.html",
        description_clean=LONG_DESC,
    )
    await enrichment.process_raw_message(
        raw_bytes=rem_raw.model_dump_json().encode(),
        gemini=mock_gemini,
        redis_client=fake_redis,
        producer=mock_producer,
    )
    assert mock_gemini.extract_job_metadata.call_count == 1

    # 2. Equal-tier Aggregator (Himalayas, tier=20) arrives next -> SUPPRESSED (0 Gemini, 0 quota)
    him_raw = JobRawEvent(
        ats_source=ATSSource.HIMALAYAS,
        external_id="him-w2",
        content_hash="2" * 64,
        title="Senior Backend Python Engineer",
        company_name="Acme, Inc.",
        apply_url="https://himalayas.app/jobs/w2",
        raw_html_gcs_uri="gs://b/2.html",
        description_clean=LONG_DESC,
    )
    await enrichment.process_raw_message(
        raw_bytes=him_raw.model_dump_json().encode(),
        gemini=mock_gemini,
        redis_client=fake_redis,
        producer=mock_producer,
    )
    assert mock_gemini.extract_job_metadata.call_count == 1
    assert fake_redis.quota_calls == 1

    # 3. Higher-tier Direct ATS (Greenhouse, tier=10 < 20) arrives -> ALLOWED through to Stage 0!
    gh_raw = JobRawEvent(
        ats_source=ATSSource.GREENHOUSE,
        external_id="gh-w3",
        content_hash="3" * 64,
        title="Senior Backend Python Engineer",
        company_name="Acme LLC",
        apply_url="https://boards.greenhouse.io/acme/jobs/w3",
        raw_html_gcs_uri="gs://b/3.html",
        description_clean=LONG_DESC,
    )
    await enrichment.process_raw_message(
        raw_bytes=gh_raw.model_dump_json().encode(),
        gemini=mock_gemini,
        redis_client=fake_redis,
        producer=mock_producer,
    )
    assert mock_gemini.extract_job_metadata.call_count == 2
    assert wave_store[next(iter(wave_store))] == DIRECT_ATS_TIER
    assert AGGREGATOR_TIER > DIRECT_ATS_TIER


def test_stage0_semantic_merge_promotes_direct_ats_backfills_and_skips_byok() -> None:
    canonical_uuid = uuid.uuid4()
    rem_source_uuid = uuid.uuid4()
    now = datetime(2026, 11, 28, 12, 0, tzinfo=UTC)
    cand = _canonical_row(
        job_uuid=canonical_uuid,
        ats_source="remotive",
        external_id="rem-1",
        work_mode="unknown",
        contract_type="unknown",
        salary_min=None,
        tech_stack=["python"],
        region_eligibility=["latam"],
        cosine_sim=0.96,
        primary_ats_source="remotive",
    )

    executed: list[tuple[str, tuple | None]] = []

    class _Stage0Cursor:
        def execute(self, sql, params=None):
            executed.append((sql, params))
            self._sql = sql

        def fetchone(self):
            if (
                "FROM jobs_jobpostingsource s" in self._sql
                and "INNER JOIN jobs_jobposting" in self._sql
            ):
                return None  # Fast Path 1 miss
            if "OR j.content_hash = %s" in self._sql:
                return None  # Fast Path 2 miss
            if "SELECT uuid, job_posting_id, is_primary" in self._sql:
                return None  # Incoming greenhouse source is new
            if "SELECT uuid, ats_source, is_active" in self._sql:
                return (rem_source_uuid, "remotive", True)
            if "AND external_id <> %s" in self._sql:
                return None  # Cross-source syndication (not same source)
            return None

        def fetchall(self):
            if "AS cosine_sim" in self._sql:
                return [cand]
            return []

    incoming_gh = _make_enriched(
        ats_source=ATSSource.GREENHOUSE,
        external_id="gh-promoted-1",
        apply_url="https://boards.greenhouse.io/acme/jobs/promoted",
        work_mode=WorkMode.REMOTE,
        contract_type=ContractType.B2B_CONTRACTOR,
        salary_min=150000,
        salary_max=190000,
        salary_currency="USD",
        salary_period=SalaryPeriod.ANNUAL,
        tech_stack=["python", "kafka"],
        region_eligibility=[RegionEligibility.BRAZIL],
    )

    cur = _Stage0Cursor()
    resolved = matcher._upsert_or_merge_canonical_job(cur, incoming_gh, now)

    assert resolved.uuid == canonical_uuid
    assert resolved.merged_into_existing is True
    assert resolved.apply_url == "https://boards.greenhouse.io/acme/jobs/promoted"
    # Non-destructive backfill applied
    assert resolved.work_mode == "remote"
    assert resolved.contract_type == "b2b_contractor"
    assert set(resolved.tech_stack) == {"python", "kafka"}
    assert set(resolved.region_eligibility) == {"latam", "brazil"}

    # Verify advisory lock, two-step primary swap, and repost_count stays 0 on active syndication
    sql_list = [s for s, _ in executed]
    assert any("pg_advisory_xact_lock" in s for s in sql_list)
    clear_idx = next(i for i, s in enumerate(sql_list) if "SET is_primary = FALSE" in s)
    promote_idx = next(
        i for i, s in enumerate(sql_list) if "SET is_primary = TRUE" in s
    )
    assert clear_idx < promote_idx

    update_job_call = next(
        (s, p)
        for s, p in executed
        if "UPDATE jobs_jobposting" in s and "repost_count" in s
    )
    assert update_job_call[1][-3] == 0  # repost_count stays 0

    # Verify BYOK skip when user already has fresh MatchScore on canonical job
    fernet_key = Fernet.generate_key().decode()
    enc_key = encrypt_api_key("AIzaSyFakeByokKey1234567890", fernet_key)
    resume_uuid = uuid.uuid4()
    profile = matcher._ActiveProfile(
        uuid=resume_uuid,
        user_id=42,
        label="Backend EN",
        raw_text="Python",
        content_hash="fresh_hash_" + "a" * 53,
        extracted_skills=["python"],
        target_seniority=["senior"],
        target_contract_types=[],
        target_regions=[],
        min_alert_score=75,
        cosine_similarity=0.91,
        language="en",
        api_key_encrypted=enc_key,
    )
    mock_scoring = MagicMock()
    cur_route = MagicMock()
    cur_route.fetchone.return_value = (
        uuid.uuid4(),
        profile.content_hash,
        89,
        0.91,
        ["python"],
        [],
    )
    alert = matcher._route_job_for_user(
        cur_route,
        now=now,
        trace_id="t" * 32,
        job=resolved,
        user_id=42,
        user_profiles=[profile],
        scoring_manager=mock_scoring,
        encryption_key=fernet_key,
    )
    assert alert is None
    assert mock_scoring.evaluate_resume_fit_sync.call_count == 0


@pytest.mark.parametrize(
    ("case_name", "cand_overrides", "incoming_overrides"),
    [
        (
            "generic_company",
            {"company_name": "Confidential"},
            {"company_name": "Confidencial"},
        ),
        (
            "different_seniority",
            {"seniority": "senior"},
            {"seniority": SeniorityLevel.STAFF},
        ),
        (
            "different_language",
            {"language": "en"},
            {"language": "pt"},
        ),
        (
            "different_work_mode",
            {"work_mode": "remote"},
            {"work_mode": WorkMode.ONSITE},
        ),
        (
            "disjoint_regions",
            {"region_eligibility": ["brazil"]},
            {"region_eligibility": [RegionEligibility.EUROPE]},
        ),
        (
            "cosine_below_threshold",
            {"cosine_sim": 0.91},
            {},
        ),
        (
            "title_jaccard_below_threshold",
            {"title": "Frontend React Engineer"},
            {"title": "Senior Backend Python Engineer"},
        ),
    ],
)
def test_stage0_negative_merge_guardrails_never_falsely_merge(
    case_name: str,
    cand_overrides: dict,
    incoming_overrides: dict,
) -> None:
    now = datetime(2026, 11, 28, 12, 0, tzinfo=UTC)
    cand = _canonical_row(**cand_overrides)
    new_uuid = uuid.uuid4()

    class _GuardrailCursor:
        def execute(self, sql, params=None):
            self._sql = sql

        def fetchone(self):
            if "INSERT INTO jobs_jobposting (" in self._sql:
                return (new_uuid,)
            return None

        def fetchall(self):
            if "AS cosine_sim" in self._sql:
                return [cand]
            return []

    incoming = _make_enriched(
        ats_source=ATSSource.GREENHOUSE,
        external_id=f"gh-{case_name}",
        **incoming_overrides,
    )
    result = matcher._upsert_or_merge_canonical_job(_GuardrailCursor(), incoming, now)
    assert result.merged_into_existing is False, f"Guardrail failed for {case_name}"
    assert result.uuid == new_uuid


def test_stage0_repost_classification_closed_reactivation_and_same_source_age() -> None:
    now = datetime(2026, 11, 28, 12, 0, tzinfo=UTC)
    canonical_uuid = uuid.uuid4()

    # Case A: Closed canonical job reactivated -> repost_count += 1, is_active = TRUE
    closed_row = _canonical_row(
        job_uuid=canonical_uuid,
        is_active=False,
        repost_count=1,
        created_at=now - timedelta(days=5),
    )
    executed_a: list[tuple[str, tuple | None]] = []

    class _ClosedCur:
        def execute(self, sql, params=None):
            executed_a.append((sql, params))
            self._sql = sql

        def fetchone(self):
            if "FROM jobs_jobpostingsource s" in self._sql:
                return closed_row[:24]
            if "SELECT uuid, job_posting_id, is_primary" in self._sql:
                return (uuid.uuid4(), canonical_uuid, True)
            if "SELECT uuid, ats_source, is_active" in self._sql:
                return (uuid.uuid4(), "remotive", False)
            return None

    matcher._upsert_or_merge_canonical_job(
        _ClosedCur(),
        _make_enriched(ats_source=ATSSource.REMOTIVE, external_id="rem-1"),
        now,
    )
    upd_a = next((s, p) for s, p in executed_a if "UPDATE jobs_jobposting\n" in s)
    assert "is_active = TRUE" in upd_a[0]
    assert upd_a[1][-3] == 2  # repost_count incremented 1 -> 2
    assert upd_a[1][-2] == now

    # Case B: Same ats_source with NEW external_id after >= 14 days -> repost_count += 1
    old_row = _canonical_row(
        job_uuid=canonical_uuid,
        is_active=True,
        repost_count=0,
        created_at=now - timedelta(days=20),
    )
    executed_b: list[tuple[str, tuple | None]] = []

    class _SameSourceCur:
        def execute(self, sql, params=None):
            executed_b.append((sql, params))
            self._sql = sql

        def fetchone(self):
            if (
                "INNER JOIN jobs_jobposting" in self._sql
                or "OR j.content_hash" in self._sql
            ):
                return None
            if "SELECT uuid, job_posting_id, is_primary" in self._sql:
                return None  # new external_id
            if "SELECT uuid, ats_source, is_active" in self._sql:
                return (uuid.uuid4(), "remotive", True)
            if "AND external_id <> %s" in self._sql:
                return (1,)  # prior source with same ats_source exists
            return None

        def fetchall(self):
            if "AS cosine_sim" in self._sql:
                return [old_row]
            return []

    matcher._upsert_or_merge_canonical_job(
        _SameSourceCur(),
        _make_enriched(ats_source=ATSSource.REMOTIVE, external_id="rem-2-repost"),
        now,
    )
    upd_b = next((s, p) for s, p in executed_b if "UPDATE jobs_jobposting\n" in s)
    assert upd_b[1][-3] == 1  # repost_count incremented 0 -> 1
    assert upd_b[1][-2] == now

    # Case C: Synchronous manual reactivation already flipped is_active=True & linked manual source -> NO double increment
    already_reactivated = _canonical_row(
        job_uuid=canonical_uuid,
        ats_source="greenhouse",
        is_active=True,
        repost_count=1,
        last_reposted_at=now - timedelta(seconds=5),
    )
    executed_c: list[tuple[str, tuple | None]] = []

    class _ManualSyncCur:
        def execute(self, sql, params=None):
            executed_c.append((sql, params))
            self._sql = sql

        def fetchone(self):
            if "INNER JOIN jobs_jobposting" in self._sql:
                return already_reactivated[:24]
            if "SELECT uuid, job_posting_id, is_primary" in self._sql:
                return (uuid.uuid4(), canonical_uuid, False)
            if "SELECT uuid, ats_source, is_active" in self._sql:
                return (uuid.uuid4(), "greenhouse", True)
            return None

    res_manual = matcher._upsert_or_merge_canonical_job(
        _ManualSyncCur(),
        _make_enriched(
            ats_source=ATSSource.MANUAL,
            external_id="manual-ext-1",
            submitted_by_user_id=77,
        ),
        now,
    )
    upd_c = next((s, p) for s, p in executed_c if "UPDATE jobs_jobposting\n" in s)
    assert upd_c[1][-3] == 1  # unchanged — no double increment!
    assert res_manual.merged_into_existing is True
    assert res_manual.incoming_ats_source == "manual"
    assert matcher._is_manual_bypass_user(res_manual, 77) is True


def test_lifecycle_direct_ats_immediate_close_aggregator_failover_and_zero_active_close(
    monkeypatch,
) -> None:
    now = datetime(2026, 11, 28, 12, 0, tzinfo=UTC)
    job_direct = str(uuid.uuid4())
    job_failover = str(uuid.uuid4())
    job_empty = str(uuid.uuid4())

    gh_src = lifecycle._ProbedSource(
        source_uuid=str(uuid.uuid4()),
        job_uuid=job_direct,
        ats_source="greenhouse",
        apply_url="https://boards.greenhouse.io/acme/jobs/1",
        is_primary=True,
        company_norm="acme",
    )
    rem_src = lifecycle._ProbedSource(
        source_uuid=str(uuid.uuid4()),
        job_uuid=job_failover,
        ats_source="remotive",
        apply_url="https://remotive.com/jobs/2",
        is_primary=True,
        company_norm="beta",
    )
    last_src = lifecycle._ProbedSource(
        source_uuid=str(uuid.uuid4()),
        job_uuid=job_empty,
        ats_source="jobicy",
        apply_url="https://jobicy.com/jobs/3",
        is_primary=True,
        company_norm="gamma",
    )
    ashby_backup_uuid = uuid.uuid4()
    executed: list[tuple[str, tuple | None]] = []

    class _LifecycleCur:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, sql, params=None):
            executed.append((sql, params))
            self._sql = sql
            self._params = params

        def fetchall(self):
            if (
                "FROM jobs_jobpostingsource" in self._sql
                and "is_active = TRUE" in self._sql
            ):
                if self._params == (job_failover,):
                    return [
                        (
                            ashby_backup_uuid,
                            "ashby",
                            "https://jobs.ashbyhq.com/beta/2",
                            False,
                            now - timedelta(days=1),
                        )
                    ]
                return []  # job_empty has 0 remaining active sources
            if "UPDATE jobs_jobposting" in self._sql and "RETURNING" in self._sql:
                closed_ids = self._params[2]
                return [
                    (uid, f"Title {uid[:4]}", "Co", "https://example.com")
                    for uid in closed_ids
                ]
            if "FROM tracker_applicationlead" in self._sql:
                return [(uuid.uuid4(), 10, job_direct, "applied")]
            return []

    class _LifecycleConn:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def cursor(self):
            return _LifecycleCur()

        def commit(self):
            # Intentionally no-op: in-memory connection double for unit tests.
            pass

    monkeypatch.setattr(
        "stream_edge.workers.lifecycle.psycopg.connect",
        lambda *_a, **_kw: _LifecycleConn(),
    )

    closed_jobs, failovers, leads_notified = (
        lifecycle._apply_source_lifecycle_outcomes_sync(
            live_source_uuids=[str(uuid.uuid4())],
            closed_sources=[gh_src, rem_src, last_src],
            now=now,
        )
    )

    assert (
        closed_jobs == 2
    )  # job_direct (Direct ATS primary) + job_empty (0 active left)
    assert failovers == 1  # job_failover stayed open & promoted ashby_backup_uuid
    assert leads_notified == 1

    # Confirm job_failover promoted ashby URL cleanly (FALSE before TRUE)
    failover_url_update = [
        p
        for s, p in executed
        if "UPDATE jobs_jobposting" in s and "SET apply_url = %s" in s
    ]
    assert failover_url_update == [
        ("https://jobs.ashbyhq.com/beta/2", now, job_failover)
    ]

    # Confirm closed list contains job_direct and job_empty, NOT job_failover
    close_call = next(
        p for s, p in executed if "UPDATE jobs_jobposting" in s and "RETURNING" in s
    )
    assert set(close_call[2]) == {job_direct, job_empty}


@pytest.mark.asyncio
async def test_probe_source_skips_mailto_and_detects_404() -> None:
    mailto_src = lifecycle._ProbedSource(
        source_uuid=str(uuid.uuid4()),
        job_uuid=str(uuid.uuid4()),
        ats_source="manual",
        apply_url="mailto:jobs@acme.com",
        is_primary=True,
        company_norm="acme",
    )
    http_src = lifecycle._ProbedSource(
        source_uuid=str(uuid.uuid4()),
        job_uuid=str(uuid.uuid4()),
        ats_source="greenhouse",
        apply_url="https://boards.greenhouse.io/acme/jobs/404",
        is_primary=True,
        company_norm="acme",
    )
    transport = httpx.MockTransport(lambda _req: httpx.Response(404))
    async with httpx.AsyncClient(transport=transport) as client:
        sem = lifecycle.asyncio.Semaphore(2)
        _, mailto_res = await lifecycle._probe_source(client, sem, mailto_src)
        _, http_res = await lifecycle._probe_source(client, sem, http_src)
    assert mailto_res is None
    assert http_res is True
