import { afterEach, describe, expect, it, vi } from "vitest";
import type { PaginatedResponse } from "../types/models";
import { fetchAllPages, fetchAllPagesWithCount, vektrynApi } from "./client";

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
                        collect_trigger: { can_trigger: true, cooldown_remaining_seconds: 0 },
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
});
