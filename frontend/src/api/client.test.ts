import { afterEach, describe, expect, it, vi } from "vitest";
import type { PaginatedResponse } from "../types/models";
import {
    ApiError,
    fetchAllPages,
    fetchAllPagesWithCount,
    formatApiError,
    registerSessionExpiredHandler,
    vektrynApi,
} from "./client";

describe("fetchAllPages", () => {
    it("follows DRF pagination until next is null while preserving query params", async () => {
        const queries: string[] = [];
        const fetchPage = async (query: string): Promise<PaginatedResponse<number>> => {
            queries.push(query);
            const page = Number(new URLSearchParams(query.replace(/^\?/, "")).get("page"));
            if (page === 1) {
                return { count: 3, next: "/api/v1/leads/?page=2", previous: null, results: [1, 2] };
            }
            return { count: 3, next: null, previous: "/api/v1/leads/?page=1", results: [3] };
        };

        const items = await fetchAllPages(fetchPage, "?status=applied");
        expect(items).toEqual([1, 2, 3]);
        expect(queries).toEqual(["?status=applied&page=1", "?status=applied&page=2"]);
    });

    const fetchInfinitePage = async (): Promise<PaginatedResponse<string>> => ({
        count: 99,
        next: "/api/next",
        previous: null,
        results: ["row"],
    });

    it("stops at maxPages even when next remains non-null", async () => {
        const items = await fetchAllPages(fetchInfinitePage, "", 3);
        expect(items).toEqual(["row", "row", "row"]);
    });

    it("preserves server total count in fetchAllPagesWithCount even when capped by maxPages", async () => {
        const result = await fetchAllPagesWithCount(fetchInfinitePage, "", 2);
        expect(result).toEqual({ items: ["row", "row"], totalCount: 99 });
    });
});

describe("vektrynApi", () => {
    afterEach(() => {
        vi.restoreAllMocks();
        vi.unstubAllGlobals();
    });

    it("attaches X-CSRFToken on POST and omits Content-Type for FormData uploads", async () => {
        vi.stubGlobal("document", { cookie: "csrftoken=test-csrf-token" });
        const fetchMock = vi.fn().mockResolvedValue(
            new Response(
                JSON.stringify({
                    uuid: "resume-1",
                    label: "Backend",
                    raw_text: "Python",
                    source_file_gcs_uri: "",
                    extracted_skills: ["python"],
                    target_seniority: ["senior"],
                    target_contract_types: ["pj"],
                    target_regions: ["brazil"],
                    min_alert_score: 75,
                    is_active: true,
                    has_embedding: true,
                    created_at: "2026-03-01T00:00:00Z",
                    modified_at: "2026-03-01T00:00:00Z",
                }),
                { status: 201, headers: { "Content-Type": "application/json" } },
            ),
        );
        vi.stubGlobal("fetch", fetchMock);

        const file = new File(["Senior Python Engineer"], "resume.txt", { type: "text/plain" });
        const created = await vektrynApi.createResume({
            label: "Backend",
            file,
            target_seniority: ["senior"],
            min_alert_score: 75,
        });

        expect(created.uuid).toBe("resume-1");
        expect(fetchMock).toHaveBeenCalledTimes(1);
        const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
        const headers = init.headers as Headers;
        expect(headers.get("X-CSRFToken")).toBe("test-csrf-token");
        expect(headers.has("Content-Type")).toBe(false);
        expect(init.body).toBeInstanceOf(FormData);
    });

    it("handles 204 No Content on logout cleanly", async () => {
        const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 204 }));
        vi.stubGlobal("fetch", fetchMock);

        await expect(vektrynApi.logout()).resolves.toBeUndefined();
    });

    it("posts rescore request with CSRF token and options", async () => {
        vi.stubGlobal("document", { cookie: "csrftoken=rescore-csrf" });
        const fetchMock = vi.fn().mockResolvedValue(
            new Response(
                JSON.stringify({
                    status: "queued",
                    event_id: "evt-1",
                    resume_profile_uuid: "resume-1",
                    max_jobs: 25,
                    force: true,
                }),
                { status: 202, headers: { "Content-Type": "application/json" } },
            ),
        );
        vi.stubGlobal("fetch", fetchMock);

        const res = await vektrynApi.rescoreResume("resume-1", { max_jobs: 25, force: true });
        expect(res).toEqual({
            status: "queued",
            event_id: "evt-1",
            resume_profile_uuid: "resume-1",
            max_jobs: 25,
            force: true,
        });
        const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
        expect(url).toBe("/api/v1/resumes/resume-1/rescore/");
        expect(init.method).toBe("POST");
        expect((init.headers as Headers).get("X-CSRFToken")).toBe("rescore-csrf");
        expect(init.body).toBe(JSON.stringify({ max_jobs: 25, force: true }));
    });

    it("posts manual job import with CSRF token and supports listJobs external_id lookup", async () => {
        vi.stubGlobal("document", { cookie: "csrftoken=import-csrf" });
        const fetchMock = vi
            .fn()
            .mockResolvedValueOnce(
                new Response(
                    JSON.stringify({
                        status: "queued",
                        ats_source: "manual",
                        external_id: "manual-abc123",
                        content_hash: "a".repeat(64),
                        title: "Staff Python Engineer",
                        company_name: "Acme",
                        apply_url: "mailto:hiring@acme.com",
                        event_id: "evt-9",
                        job_posting_uuid: null,
                    }),
                    { status: 202, headers: { "Content-Type": "application/json" } },
                ),
            )
            .mockResolvedValueOnce(
                new Response(
                    JSON.stringify({
                        count: 1,
                        next: null,
                        previous: null,
                        results: [{ uuid: "job-1", external_id: "manual-abc123" }],
                    }),
                    { status: 200, headers: { "Content-Type": "application/json" } },
                ),
            );
        vi.stubGlobal("fetch", fetchMock);

        const imported = await vektrynApi.importJob({
            title: "Staff Python Engineer",
            company_name: "Acme",
            apply_url: "hiring@acme.com",
            description: "Build Python and Kafka services at scale.",
        });
        expect(imported.status).toBe("queued");
        expect(imported.apply_url).toBe("mailto:hiring@acme.com");

        const [importUrl, importInit] = fetchMock.mock.calls[0] as [string, RequestInit];
        expect(importUrl).toBe("/api/v1/jobs/import/");
        expect(importInit.method).toBe("POST");
        expect((importInit.headers as Headers).get("X-CSRFToken")).toBe("import-csrf");

        const listed = await vektrynApi.listJobs("?ats_source=manual&external_id=manual-abc123");
        expect(listed.count).toBe(1);
        expect((fetchMock.mock.calls[1] as [string])[0]).toBe(
            "/api/v1/jobs/?ats_source=manual&external_id=manual-abc123",
        );
    });

    it("fetches pipeline system status and triggers staff collector sync with CSRF token", async () => {
        vi.stubGlobal("document", { cookie: "csrftoken=sys-csrf" });
        const fetchMock = vi
            .fn()
            .mockResolvedValueOnce(
                new Response(
                    JSON.stringify({
                        overall_status: "healthy",
                        last_collect_at: "2026-11-25T05:00:00Z",
                        latest_run_totals: {
                            fetched_count: 50,
                            ingested_count: 10,
                            deduped_count: 40,
                            error_count: 0,
                            duration_ms: 1200,
                        },
                        sources: [],
                        jobs: {
                            active_count: 75,
                            ai_scored_count: 25,
                            unscored_active_count: 50,
                            pending_match_count: 0,
                            recent_unmatched_count: 0,
                            unembedded_active_count: 0,
                        },
                        rollup: {
                            latest_bucket_date: "2026-11-25",
                            latest_updated_at: "2026-11-25T01:00:00Z",
                        },
                        dlq: { status: "healthy", recent_24h_count: 0, total_count: 0 },
                        collect_trigger: {
                            can_trigger: true,
                            is_running: false,
                            running_started_at: null,
                            cooldown_remaining_seconds: 0,
                        },
                    }),
                    { status: 200, headers: { "Content-Type": "application/json" } },
                ),
            )
            .mockResolvedValueOnce(
                new Response(
                    JSON.stringify({
                        status: "queued",
                        mode: "cloud_run_job",
                        job_name: "vektryn-collect",
                        execution_id: "exec-1",
                        cooldown_seconds: 300,
                    }),
                    { status: 202, headers: { "Content-Type": "application/json" } },
                ),
            );
        vi.stubGlobal("fetch", fetchMock);

        const statusRes = await vektrynApi.getSystemStatus();
        expect(statusRes.overall_status).toBe("healthy");
        expect((fetchMock.mock.calls[0] as [string])[0]).toBe("/api/v1/system/status/");

        const triggerRes = await vektrynApi.triggerCollectorSync();
        expect(triggerRes.status).toBe("queued");
        const [triggerUrl, triggerInit] = fetchMock.mock.calls[1] as [string, RequestInit];
        expect(triggerUrl).toBe("/api/v1/system/collect/");
        expect(triggerInit.method).toBe("POST");
        expect((triggerInit.headers as Headers).get("X-CSRFToken")).toBe("sys-csrf");
    });

    it("calls notification center endpoints and match detail lookup with CSRF tokens", async () => {
        vi.stubGlobal("document", { cookie: "csrftoken=notif-csrf" });
        const sampleNotification = {
            uuid: "notif-1",
            kind: "match_alert",
            title: "90% Fit: Staff Python",
            body: "Acme matched",
            payload: { match_score_uuid: "match-1", job_posting_uuid: "job-1" },
            read_at: null,
            dismissed_at: null,
            is_read: false,
            created_at: "2026-11-25T10:00:00Z",
            modified_at: "2026-11-25T10:00:00Z",
        };
        const fetchMock = vi
            .fn()
            .mockResolvedValueOnce(
                new Response(
                    JSON.stringify({
                        count: 1,
                        next: null,
                        previous: null,
                        results: [sampleNotification],
                        unread_count: 1,
                    }),
                    { status: 200, headers: { "Content-Type": "application/json" } },
                ),
            )
            .mockResolvedValueOnce(
                new Response(
                    JSON.stringify({
                        notification: { ...sampleNotification, is_read: true, read_at: "2026-11-25T10:05:00Z" },
                        unread_count: 0,
                    }),
                    { status: 200, headers: { "Content-Type": "application/json" } },
                ),
            )
            .mockResolvedValueOnce(
                new Response(
                    JSON.stringify({
                        notification: { ...sampleNotification, dismissed_at: "2026-11-25T10:06:00Z" },
                        unread_count: 0,
                    }),
                    { status: 200, headers: { "Content-Type": "application/json" } },
                ),
            )
            .mockResolvedValueOnce(
                new Response(
                    JSON.stringify({ updated_count: 2, unread_count: 0 }),
                    { status: 200, headers: { "Content-Type": "application/json" } },
                ),
            )
            .mockResolvedValueOnce(
                new Response(
                    JSON.stringify({ uuid: "match-1", fit_score: 90 }),
                    { status: 200, headers: { "Content-Type": "application/json" } },
                ),
            );
        vi.stubGlobal("fetch", fetchMock);

        const listRes = await vektrynApi.listNotifications("?unread=true");
        expect(listRes.unread_count).toBe(1);
        expect((fetchMock.mock.calls[0] as [string])[0]).toBe("/api/v1/notifications/?unread=true");

        const readRes = await vektrynApi.markNotificationRead("notif-1");
        expect(readRes.unread_count).toBe(0);
        expect((fetchMock.mock.calls[1] as [string, RequestInit])[0]).toBe(
            "/api/v1/notifications/notif-1/read/",
        );
        expect((fetchMock.mock.calls[1] as [string, RequestInit])[1].method).toBe("PATCH");

        const dismissRes = await vektrynApi.dismissNotification("notif-1");
        expect(dismissRes.unread_count).toBe(0);
        expect((fetchMock.mock.calls[2] as [string, RequestInit])[0]).toBe(
            "/api/v1/notifications/notif-1/dismiss/",
        );

        const readAllRes = await vektrynApi.markAllNotificationsRead();
        expect(readAllRes.updated_count).toBe(2);
        expect((fetchMock.mock.calls[3] as [string, RequestInit])[0]).toBe(
            "/api/v1/notifications/read-all/",
        );
        expect((fetchMock.mock.calls[3] as [string, RequestInit])[1].method).toBe("POST");

        const matchRes = await vektrynApi.getMatch("match-1");
        expect(matchRes.uuid).toBe("match-1");
        expect((fetchMock.mock.calls[4] as [string])[0]).toBe("/api/v1/matches/match-1/");
    });

    it("supports saved filter CRUD and lead CSV export", async () => {
        vi.stubGlobal("document", { cookie: "csrftoken=preset-csrf" });
        const samplePreset = {
            uuid: "preset-1",
            name: "BR Senior Python",
            query_params: { seniority: "senior", region: "brazil" },
            created_at: "2026-11-25T10:00:00Z",
            modified_at: "2026-11-25T10:00:00Z",
        };
        const fetchMock = vi
            .fn()
            .mockResolvedValueOnce(
                new Response(
                    JSON.stringify({
                        count: 1,
                        next: null,
                        previous: null,
                        results: [samplePreset],
                    }),
                    { status: 200, headers: { "Content-Type": "application/json" } },
                ),
            )
            .mockResolvedValueOnce(
                new Response(JSON.stringify(samplePreset), {
                    status: 201,
                    headers: { "Content-Type": "application/json" },
                }),
            )
            .mockResolvedValueOnce(new Response(null, { status: 204 }))
            .mockResolvedValueOnce(
                new Response("uuid,job_title\nlead-1,Engineer\n", {
                    status: 200,
                    headers: {
                        "Content-Type": "text/csv",
                        "Content-Disposition": 'attachment; filename="vektryn-leads-2026-11-25.csv"',
                    },
                }),
            );
        vi.stubGlobal("fetch", fetchMock);

        const listed = await vektrynApi.listSavedFilters();
        expect(listed.results).toHaveLength(1);
        expect((fetchMock.mock.calls[0] as [string])[0]).toBe("/api/v1/jobs/filters/");

        const created = await vektrynApi.createSavedFilter({
            name: "BR Senior Python",
            query_params: { seniority: "senior", region: "brazil" },
        });
        expect(created.uuid).toBe("preset-1");
        expect((fetchMock.mock.calls[1] as [string, RequestInit])[1].method).toBe("POST");

        await vektrynApi.deleteSavedFilter("preset-1");
        expect((fetchMock.mock.calls[2] as [string])[0]).toBe("/api/v1/jobs/filters/preset-1/");

        const exported = await vektrynApi.exportLeads("csv");
        expect(exported.filename).toBe("vektryn-leads-2026-11-25.csv");
        expect(await exported.blob.text()).toContain("lead-1,Engineer");
        expect((fetchMock.mock.calls[3] as [string])[0]).toBe("/api/v1/leads/export/?format=csv");
    });

    it("supports dismissed jobs and muted companies triage endpoints", async () => {
        vi.stubGlobal("document", { cookie: "csrftoken=triage-csrf" });
        const sampleDismissed = {
            uuid: "dis-1",
            job_posting: "job-1",
            job_title: "Staff Python Engineer",
            company_name: "Acme",
            ats_source: "greenhouse",
            created_at: "2026-11-25T12:00:00Z",
        };
        const sampleMuted = {
            uuid: "mut-1",
            company_name_display: "Spam Agency",
            company_name_normalized: "spam agency",
            created_at: "2026-11-25T12:00:00Z",
        };
        const fetchMock = vi
            .fn()
            .mockResolvedValueOnce(
                new Response(
                    JSON.stringify({
                        count: 1,
                        next: null,
                        previous: null,
                        results: [sampleDismissed],
                    }),
                    { status: 200, headers: { "Content-Type": "application/json" } },
                ),
            )
            .mockResolvedValueOnce(
                new Response(JSON.stringify(sampleDismissed), {
                    status: 201,
                    headers: { "Content-Type": "application/json" },
                }),
            )
            .mockResolvedValueOnce(new Response(null, { status: 204 }))
            .mockResolvedValueOnce(
                new Response(
                    JSON.stringify({
                        count: 1,
                        next: null,
                        previous: null,
                        results: [sampleMuted],
                    }),
                    { status: 200, headers: { "Content-Type": "application/json" } },
                ),
            )
            .mockResolvedValueOnce(
                new Response(JSON.stringify(sampleMuted), {
                    status: 201,
                    headers: { "Content-Type": "application/json" },
                }),
            )
            .mockResolvedValueOnce(new Response(null, { status: 204 }));
        vi.stubGlobal("fetch", fetchMock);

        const dismissedList = await vektrynApi.listDismissedJobs(2);
        expect(dismissedList.count).toBe(1);
        expect((fetchMock.mock.calls[0] as [string])[0]).toBe("/api/v1/jobs/dismissed/?page=2");

        const dismissed = await vektrynApi.dismissJob("job-1");
        expect(dismissed.uuid).toBe("dis-1");
        expect((fetchMock.mock.calls[1] as [string, RequestInit])[1].method).toBe("POST");

        await vektrynApi.restoreDismissedJob("dis-1");
        expect((fetchMock.mock.calls[2] as [string])[0]).toBe("/api/v1/jobs/dismissed/dis-1/");

        const mutedList = await vektrynApi.listMutedCompanies(1);
        expect(mutedList.count).toBe(1);
        expect((fetchMock.mock.calls[3] as [string])[0]).toBe(
            "/api/v1/jobs/muted-companies/?page=1",
        );

        const muted = await vektrynApi.muteCompany("Spam Agency");
        expect(muted.uuid).toBe("mut-1");
        expect((fetchMock.mock.calls[4] as [string, RequestInit])[1].method).toBe("POST");

        await vektrynApi.unmuteCompany("mut-1");
        expect((fetchMock.mock.calls[5] as [string])[0]).toBe(
            "/api/v1/jobs/muted-companies/mut-1/",
        );
    });

    it("lists and generates match artifacts and parses 429/503 ApiError metadata", async () => {
        vi.stubGlobal("document", { cookie: "csrftoken=copilot-csrf" });
        const sampleArtifact = {
            uuid: "art-1",
            match_score: "match-1",
            kind: "tailored_bullets",
            resume_content_hash: "hash-v1",
            content_markdown: "## Tailored Resume Bullets\n- Shipped Kafka pipelines.",
            model_name: "gemini-4-hydrogen",
            is_stale: false,
            created_at: "2026-11-25T12:00:00Z",
            modified_at: "2026-11-25T12:00:00Z",
        };
        const fetchMock = vi
            .fn()
            .mockResolvedValueOnce(
                new Response(JSON.stringify({ results: [sampleArtifact] }), {
                    status: 200,
                    headers: { "Content-Type": "application/json" },
                }),
            )
            .mockResolvedValueOnce(
                new Response(JSON.stringify({ ...sampleArtifact, cached: false }), {
                    status: 201,
                    headers: { "Content-Type": "application/json" },
                }),
            )
            .mockResolvedValueOnce(
                new Response(
                    JSON.stringify({
                        detail: "AI Copilot rate limit exceeded. Try again in 42s.",
                        retry_after_seconds: 42,
                    }),
                    {
                        status: 429,
                        headers: {
                            "Content-Type": "application/json",
                            "Retry-After": "42",
                        },
                    },
                ),
            )
            .mockResolvedValueOnce(
                new Response(
                    JSON.stringify({ detail: "AI Copilot is temporarily unavailable." }),
                    {
                        status: 503,
                        headers: { "Content-Type": "application/json" },
                    },
                ),
            );
        vi.stubGlobal("fetch", fetchMock);

        const listed = await vektrynApi.listMatchArtifacts("match-1");
        expect(listed.results).toHaveLength(1);
        expect((fetchMock.mock.calls[0] as [string])[0]).toBe(
            "/api/v1/matches/match-1/artifacts/",
        );

        const generated = await vektrynApi.generateMatchArtifact("match-1", {
            kind: "tailored_bullets",
            regenerate: true,
            tone: "technical",
            guidance: "Focus on throughput",
        });
        expect(generated.cached).toBe(false);
        const [postUrl, postInit] = fetchMock.mock.calls[1] as [string, RequestInit];
        expect(postUrl).toBe("/api/v1/matches/match-1/artifacts/");
        expect(postInit.method).toBe("POST");
        expect(JSON.parse(postInit.body as string)).toEqual({
            kind: "tailored_bullets",
            regenerate: true,
            tone: "technical",
            guidance: "Focus on throughput",
        });

        try {
            await vektrynApi.generateMatchArtifact("match-1", { kind: "cover_letter" });
            expect.unreachable("Expected 429 ApiError");
        } catch (err) {
            expect(err).toBeInstanceOf(ApiError);
            const apiErr = err as ApiError;
            expect(apiErr.status).toBe(429);
            expect(apiErr.retryAfterSeconds).toBe(42);
            expect(apiErr.detail).toContain("42s");
        }

        try {
            await vektrynApi.generateMatchArtifact("match-1", { kind: "cover_letter" });
            expect.unreachable("Expected 503 ApiError");
        } catch (err) {
            expect(err).toBeInstanceOf(ApiError);
            const apiErr = err as ApiError;
            expect(apiErr.status).toBe(503);
            expect(apiErr.detail).toBe("AI Copilot is temporarily unavailable.");
        }
    });

    it("inspects and replays DLQ messages and handles 429 cooldown errors", async () => {
        vi.stubGlobal("document", { cookie: "csrftoken=dlq-csrf" });
        const fetchMock = vi
            .fn()
            .mockResolvedValueOnce(
                new Response(
                    JSON.stringify({
                        total_count: 1,
                        returned_count: 1,
                        limit: 25,
                        replay_cooldown_remaining_seconds: 0,
                        items: [
                            {
                                event_id: "evt-1",
                                original_topic: "jobs.raw",
                                partition: 0,
                                offset: 4,
                                dlq_partition: 0,
                                dlq_offset: 10,
                                error_type: "RuntimeError",
                                error_message: "boom",
                                retry_count: 1,
                                produced_at: "2026-11-25T12:00:00Z",
                                payload_preview: "{}",
                                payload_truncated: false,
                                replayable: true,
                                replayed_at: null,
                                dismissed_at: null,
                            },
                        ],
                    }),
                    { status: 200, headers: { "Content-Type": "application/json" } },
                ),
            )
            .mockResolvedValueOnce(
                new Response(
                    JSON.stringify({
                        dry_run: true,
                        matched_count: 1,
                        replayed_count: 0,
                        skipped_count: 0,
                        failed_count: 0,
                        cooldown_seconds: 30,
                        items: [],
                    }),
                    { status: 200, headers: { "Content-Type": "application/json" } },
                ),
            )
            .mockResolvedValueOnce(
                new Response(
                    JSON.stringify({
                        detail: "DLQ replay is on cooldown. Try again in 22s.",
                        retry_after_seconds: 22,
                    }),
                    {
                        status: 429,
                        headers: {
                            "Content-Type": "application/json",
                            "Retry-After": "22",
                        },
                    },
                ),
            )
            .mockResolvedValueOnce(
                new Response(
                    JSON.stringify({
                        dismissed_count: 1,
                        dismissed_at: "2026-11-25T15:00:00Z",
                        event_ids: ["evt-1"],
                    }),
                    { status: 200, headers: { "Content-Type": "application/json" } },
                ),
            );
        vi.stubGlobal("fetch", fetchMock);

        const listRes = await vektrynApi.listDlqMessages({
            limit: 25,
            original_topic: "jobs.raw",
        });
        expect(listRes.returned_count).toBe(1);
        expect((fetchMock.mock.calls[0] as [string])[0]).toBe(
            "/api/v1/system/dlq/?limit=25&original_topic=jobs.raw",
        );

        const dryRes = await vektrynApi.replayDlqMessages({
            dry_run: true,
            event_ids: ["evt-1"],
        });
        expect(dryRes.matched_count).toBe(1);
        const [replayUrl, replayInit] = fetchMock.mock.calls[1] as [string, RequestInit];
        expect(replayUrl).toBe("/api/v1/system/dlq/replay/");
        expect(replayInit.method).toBe("POST");

        try {
            await vektrynApi.replayDlqMessages({ dry_run: false, event_ids: ["evt-1"] });
            expect.unreachable("Expected 429 ApiError");
        } catch (err) {
            expect(err).toBeInstanceOf(ApiError);
            expect((err as ApiError).status).toBe(429);
            expect((err as ApiError).retryAfterSeconds).toBe(22);
        }

        const dismissRes = await vektrynApi.dismissDlqMessages(["evt-1"]);
        expect(dismissRes.dismissed_count).toBe(1);
        const [dismissUrl, dismissInit] = fetchMock.mock.calls[3] as [string, RequestInit];
        expect(dismissUrl).toBe("/api/v1/system/dlq/dismiss/");
        expect(dismissInit.method).toBe("POST");
    });

    it("fetches personal analytics with days and resume_profile query params", async () => {
        const fetchMock = vi.fn().mockResolvedValueOnce(
            new Response(
                JSON.stringify({
                    window: { days: 90, label: "90d", resume_profile_uuid: "res-1" },
                    funnel: {
                        total_leads: 0,
                        status_counts: {
                            discovered: 0,
                            saved: 0,
                            applied: 0,
                            screening: 0,
                            interviewing: 0,
                            offer: 0,
                            rejected: 0,
                            withdrawn: 0,
                        },
                        stages: [],
                        applied_to_offer_pct: null,
                        median_days_since_applied: null,
                    },
                    channels: { by_ats_source: [], by_contract_type: [] },
                    skill_gaps: {
                        high_fit_match_count: 0,
                        missing_keywords: [],
                        matched_skills: [],
                    },
                }),
                { status: 200, headers: { "Content-Type": "application/json" } },
            ),
        );
        vi.stubGlobal("fetch", fetchMock);

        const res = await vektrynApi.getPersonalAnalytics({
            days: "90",
            resumeProfileUuid: "res-1",
        });
        expect(res.window.days).toBe(90);
        expect((fetchMock.mock.calls[0] as [string])[0]).toBe(
            "/api/v1/analytics/personal/?days=90&resume_profile=res-1",
        );
    });

    it("rotates password with CSRF token and parses 400 fieldErrors and 429 login lockout", async () => {
        vi.stubGlobal("document", { cookie: "csrftoken=auth-csrf" });
        const fetchMock = vi
            .fn()
            .mockResolvedValueOnce(
                new Response(JSON.stringify({ detail: "Password updated successfully." }), {
                    status: 200,
                    headers: { "Content-Type": "application/json" },
                }),
            )
            .mockResolvedValueOnce(
                new Response(
                    JSON.stringify({
                        current_password: ["Current password is incorrect."],
                        new_password: ["This password is too common."],
                    }),
                    { status: 400, headers: { "Content-Type": "application/json" } },
                ),
            )
            .mockResolvedValueOnce(
                new Response(
                    JSON.stringify({
                        detail: "Too many failed login attempts. Try again in 900s.",
                        retry_after_seconds: 900,
                    }),
                    {
                        status: 429,
                        headers: {
                            "Content-Type": "application/json",
                            "Retry-After": "900",
                        },
                    },
                ),
            );
        vi.stubGlobal("fetch", fetchMock);

        const okRes = await vektrynApi.changePassword({
            current_password: "OldPassword!1",
            new_password: "NewPassword!2",
            confirm_password: "NewPassword!2",
        });
        expect(okRes.detail).toBe("Password updated successfully.");
        const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
        expect(url).toBe("/api/v1/auth/change-password/");
        expect(init.method).toBe("POST");
        expect((init.headers as Headers).get("X-CSRFToken")).toBe("auth-csrf");

        try {
            await vektrynApi.changePassword({
                current_password: "wrong",
                new_password: "password",
            });
            expect.unreachable("Expected 400 ApiError");
        } catch (err) {
            expect(err).toBeInstanceOf(ApiError);
            const apiErr = err as ApiError;
            expect(apiErr.status).toBe(400);
            expect(apiErr.fieldErrors.current_password).toEqual([
                "Current password is incorrect.",
            ]);
            expect(apiErr.fieldErrors.new_password).toEqual(["This password is too common."]);
        }

        try {
            await vektrynApi.login("alice", "wrong");
            expect.unreachable("Expected 429 ApiError");
        } catch (err) {
            expect(err).toBeInstanceOf(ApiError);
            const apiErr = err as ApiError;
            expect(apiErr.status).toBe(429);
            expect(apiErr.retryAfterSeconds).toBe(900);
        }
    });

    it("triggers session-expired handler on unauthenticated 403 but not staff-permission 403 or auth/me", async () => {
        const onExpired = vi.fn();
        const unregister = registerSessionExpiredHandler(onExpired);
        const fetchMock = vi
            .fn()
            .mockResolvedValueOnce(
                new Response(
                    JSON.stringify({ detail: "You do not have permission to perform this action." }),
                    { status: 403, headers: { "Content-Type": "application/json" } },
                ),
            )
            .mockResolvedValueOnce(
                new Response(
                    JSON.stringify({ detail: "Authentication credentials were not provided." }),
                    { status: 403, headers: { "Content-Type": "application/json" } },
                ),
            )
            .mockResolvedValueOnce(
                new Response(
                    JSON.stringify({ detail: "Authentication credentials were not provided." }),
                    { status: 403, headers: { "Content-Type": "application/json" } },
                ),
            );
        vi.stubGlobal("fetch", fetchMock);

        try {
            await expect(vektrynApi.listDlqMessages()).rejects.toBeInstanceOf(ApiError);
            expect(onExpired).not.toHaveBeenCalled();

            await expect(vektrynApi.getCurrentUser()).rejects.toBeInstanceOf(ApiError);
            expect(onExpired).not.toHaveBeenCalled();

            await expect(vektrynApi.listNotifications()).rejects.toBeInstanceOf(ApiError);
            expect(onExpired).toHaveBeenCalledTimes(1);
        } finally {
            unregister();
        }
    });

    it("manages self-service profile, deactivation, and staff user CRUD endpoints", async () => {
        vi.stubGlobal("document", { cookie: "csrftoken=profile-csrf" });
        const sampleProfile = {
            id: "1",
            username: "rafa",
            email: "rafa@example.com",
            is_staff: true,
            is_superuser: true,
            display_name: "Rafa",
            timezone: "America/Sao_Paulo",
            preferred_currency: "BRL",
            default_copilot_tone: "technical",
            linkedin_url: "https://linkedin.com/in/rafa",
            github_url: "https://github.com/debastiani-dev",
            portfolio_url: "",
            created_at: "2026-11-25T00:00:00Z",
            modified_at: "2026-11-25T00:00:00Z",
        };
        const sampleManaged = {
            id: 2,
            username: "alice",
            email: "alice@example.com",
            is_active: true,
            is_staff: false,
            is_superuser: false,
            date_joined: "2026-11-25T00:00:00Z",
            last_login: null,
            profile: {
                display_name: "Alice",
                timezone: "UTC",
                preferred_currency: "USD",
                default_copilot_tone: "balanced",
                linkedin_url: "",
                github_url: "",
                portfolio_url: "",
            },
        };
        const fetchMock = vi
            .fn()
            .mockResolvedValueOnce(
                new Response(JSON.stringify(sampleProfile), {
                    status: 200,
                    headers: { "Content-Type": "application/json" },
                }),
            )
            .mockResolvedValueOnce(
                new Response(JSON.stringify({ ...sampleProfile, display_name: "Rafa D." }), {
                    status: 200,
                    headers: { "Content-Type": "application/json" },
                }),
            )
            .mockResolvedValueOnce(
                new Response(JSON.stringify({ detail: "Account deactivated successfully." }), {
                    status: 200,
                    headers: { "Content-Type": "application/json" },
                }),
            )
            .mockResolvedValueOnce(
                new Response(
                    JSON.stringify({
                        count: 1,
                        next: null,
                        previous: null,
                        results: [sampleManaged],
                    }),
                    { status: 200, headers: { "Content-Type": "application/json" } },
                ),
            )
            .mockResolvedValueOnce(
                new Response(JSON.stringify(sampleManaged), {
                    status: 201,
                    headers: { "Content-Type": "application/json" },
                }),
            )
            .mockResolvedValueOnce(
                new Response(JSON.stringify({ ...sampleManaged, is_staff: true }), {
                    status: 200,
                    headers: { "Content-Type": "application/json" },
                }),
            )
            .mockResolvedValueOnce(
                new Response(JSON.stringify({ ...sampleManaged, is_active: false }), {
                    status: 200,
                    headers: { "Content-Type": "application/json" },
                }),
            );
        vi.stubGlobal("fetch", fetchMock);

        const prof = await vektrynApi.getUserProfile();
        expect(prof.timezone).toBe("America/Sao_Paulo");
        expect((fetchMock.mock.calls[0] as [string])[0]).toBe("/api/v1/auth/profile/");

        const patched = await vektrynApi.updateUserProfile({ display_name: "Rafa D." });
        expect(patched.display_name).toBe("Rafa D.");
        expect((fetchMock.mock.calls[1] as [string, RequestInit])[1].method).toBe("PATCH");

        const deact = await vektrynApi.deactivateAccount("Secret!2026");
        expect(deact.detail).toContain("deactivated");
        expect((fetchMock.mock.calls[2] as [string])[0]).toBe("/api/v1/auth/deactivate/");

        const listed = await vektrynApi.listUsers({
            search: "alice",
            is_active: "true",
            is_staff: "false",
            page: 2,
        });
        expect(listed.results).toHaveLength(1);
        expect((fetchMock.mock.calls[3] as [string])[0]).toBe(
            "/api/v1/users/?search=alice&is_active=true&is_staff=false&page=2",
        );

        const created = await vektrynApi.createUser({
            username: "alice",
            password: "SafePassword!2026",
        });
        expect(created.id).toBe(2);
        expect((fetchMock.mock.calls[4] as [string, RequestInit])[1].method).toBe("POST");

        const updated = await vektrynApi.updateUser(2, { is_staff: true });
        expect(updated.is_staff).toBe(true);
        expect((fetchMock.mock.calls[5] as [string])[0]).toBe("/api/v1/users/2/");

        const deactivated = await vektrynApi.deactivateUser(2);
        expect(deactivated.is_active).toBe(false);
        expect((fetchMock.mock.calls[6] as [string, RequestInit])[1].method).toBe("DELETE");
    });

    it("parses DRF JSON array bodies and formats clean user-facing error messages", async () => {
        vi.stubGlobal("document", { cookie: "csrftoken=resume-csrf" });
        const fetchMock = vi
            .fn()
            .mockResolvedValueOnce(
                new Response(JSON.stringify(["Gemini request failed on gemini-4-carbon (400)."]), {
                    status: 400,
                    headers: { "Content-Type": "application/json" },
                }),
            )
            .mockResolvedValueOnce(
                new Response(
                    JSON.stringify({
                        file: ["Could not extract any readable text from the uploaded file."],
                    }),
                    {
                        status: 400,
                        headers: { "Content-Type": "application/json" },
                    },
                ),
            );
        vi.stubGlobal("fetch", fetchMock);

        try {
            await vektrynApi.createResume({ label: "CV", raw_text: "Python" });
            expect.unreachable("Expected 400 ApiError");
        } catch (err) {
            expect(err).toBeInstanceOf(ApiError);
            const apiErr = err as ApiError;
            expect(apiErr.detail).toBe("Gemini request failed on gemini-4-carbon (400).");
            expect(apiErr.fieldErrors).toEqual({});
            expect(formatApiError(apiErr, "Fallback")).toBe(
                "Gemini request failed on gemini-4-carbon (400).",
            );
        }

        try {
            await vektrynApi.createResume({ label: "CV", raw_text: "Python" });
            expect.unreachable("Expected 400 field ApiError");
        } catch (err) {
            expect(err).toBeInstanceOf(ApiError);
            expect(formatApiError(err, "Fallback")).toBe(
                "Could not extract any readable text from the uploaded file.",
            );
        }

        expect(formatApiError(new ApiError(500, "<html>500</html>", null, null), "Fallback")).toBe(
            "Fallback",
        );
    });
});
