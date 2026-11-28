import { describe, expect, it } from "vitest";
import {
    buildActiveFilterChips,
    countActivePanelFilters,
    EMPTY_METADATA_FILTERS,
    resolveRadarOrdering,
} from "./radarFilters";

describe("radarFilters", () => {
    it("omits ordering param for default best_match so backend RRF relevance applies", () => {
        expect(resolveRadarOrdering("best_match")).toBeNull();
        expect(resolveRadarOrdering("newest")).toBe("-created_at");
        expect(resolveRadarOrdering("posted_at")).toBe("-job_posting__posted_at,-created_at");
        expect(resolveRadarOrdering("vector")).toBe("-cosine_similarity,-fit_score,-created_at");
    });

    it("counts all active panel filters across resume, min fit, and metadata", () => {
        expect(
            countActivePanelFilters({
                resumeFilter: "",
                minScore: 0,
                metadataFilters: EMPTY_METADATA_FILTERS,
            }),
        ).toBe(0);

        expect(
            countActivePanelFilters({
                resumeFilter: "resume-1",
                minScore: 70,
                metadataFilters: {
                    ...EMPTY_METADATA_FILTERS,
                    seniority: "senior",
                    contractType: "pj",
                    workMode: "remote",
                    region: "",
                    atsSource: "manual",
                    language: "pt",
                    hideReposts: true,
                },
            }),
        ).toBe(8);
    });

    it("builds removable active chips with readable labels", () => {
        const chips = buildActiveFilterChips({
            resumeFilter: "resume-1",
            resumeLabel: "Senior Python Backend",
            minScore: 80,
            metadataFilters: {
                ...EMPTY_METADATA_FILTERS,
                seniority: "senior",
                contractType: "pj",
                workMode: "onsite",
                region: "brazil",
                atsSource: "manual",
                language: "pt",
                hideReposts: true,
            },
        });

        expect(chips).toEqual([
            { key: "resume", prefix: "Resume", label: "Senior Python Backend" },
            { key: "minScore", prefix: "Min Fit", label: "80%+" },
            { key: "seniority", prefix: "Seniority", label: "Senior" },
            { key: "contractType", prefix: "Contract", label: "PJ" },
            { key: "workMode", prefix: "Work Mode", label: "On-site" },
            { key: "language", prefix: "Language", label: "Portuguese (PT)" },
            { key: "region", prefix: "Region", label: "Brazil" },
            { key: "atsSource", prefix: "Source", label: "Manual Import" },
            { key: "hideReposts", prefix: "Reposts", label: "Hidden" },
        ]);
    });
});
