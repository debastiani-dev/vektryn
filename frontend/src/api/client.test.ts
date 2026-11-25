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

    it("stops at maxPages even when next remains non-null", async () => {
        const fetchPage = async (): Promise<PaginatedResponse<string>> => ({
            count: 99,
            next: "/api/next",
            previous: null,
            results: ["row"],
        });

        const items = await fetchAllPages(fetchPage, "", 3);
        expect(items).toEqual(["row", "row", "row"]);
    });

    it("preserves server total count in fetchAllPagesWithCount even when capped by maxPages", async () => {
        const fetchPage = async (): Promise<PaginatedResponse<string>> => ({
            count: 99,
            next: "/api/next",
            previous: null,
            results: ["row"],
        });

        const result = await fetchAllPagesWithCount(fetchPage, "", 2);
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
});
