import { describe, expect, it } from "vitest";
import { EMPTY_METADATA_FILTERS } from "./radarFilters";
import {
    hydrateRadarStateFromPreset,
    isPresetActive,
    normalizeCompanyName,
    serializeRadarStateToPreset,
} from "./savedFilters";

describe("savedFilters helpers", () => {
    const resumes = [{ uuid: "resume-a" }, { uuid: "resume-b" }];

    it("serializes only active non-default radar filter fields including triage flags", () => {
        const serialized = serializeRadarStateToPreset({
            searchTerm: "  python kafka  ",
            resumeFilter: "resume-a",
            minScore: 80,
            evaluatedOnly: true,
            untrackedOnly: true,
            hideDismissed: false,
            hideMuted: true,
            metadataFilters: {
                ...EMPTY_METADATA_FILTERS,
                seniority: "senior",
                contractType: "pj",
                workMode: "remote",
                region: "brazil",
                atsSource: "",
                language: "pt",
                hideReposts: true,
            },
            sortBy: "posted_at",
        });

        expect(serialized).toEqual({
            search: "python kafka",
            resume_profile: "resume-a",
            min_score: 80,
            evaluated_only: true,
            untracked_only: true,
            hide_dismissed: false,
            seniority: "senior",
            contract_type: "pj",
            work_mode: "remote",
            region: "brazil",
            language: "pt",
            hide_reposts: true,
            sort_by: "posted_at",
        });
    });

    it("falls back to All Resumes when a preset references a deleted resume_profile", () => {
        const hydrated = hydrateRadarStateFromPreset(
            {
                resume_profile: "deleted-resume-uuid",
                seniority: "staff",
                work_mode: "hybrid",
                min_score: 70,
                sort_by: "newest",
            },
            resumes,
        );

        expect(hydrated.resumeFilter).toBe("");
        expect(hydrated.metadataFilters.seniority).toBe("staff");
        expect(hydrated.metadataFilters.workMode).toBe("hybrid");
        expect(hydrated.minScore).toBe(70);
        expect(hydrated.sortBy).toBe("newest");
        expect(hydrated.untrackedOnly).toBe(false);
        expect(hydrated.hideDismissed).toBe(true);
        expect(hydrated.hideMuted).toBe(true);
    });

    it("matches legacy presets without triage keys against default triage state", () => {
        const state = hydrateRadarStateFromPreset(
            { search: "django", region: "latam", evaluated_only: true },
            resumes,
        );
        expect(
            isPresetActive(state, { search: "django", region: "latam", evaluated_only: true }, resumes),
        ).toBe(true);
        expect(
            isPresetActive(
                { ...state, untrackedOnly: true },
                { search: "django", region: "latam", evaluated_only: true },
                resumes,
            ),
        ).toBe(false);
        expect(isPresetActive(state, { search: "rust", region: "latam" }, resumes)).toBe(false);
    });

    it("normalizes company names identically to backend whitespace collapsing", () => {
        expect(normalizeCompanyName("\t  Acme   Staffing \n")).toBe("acme staffing");
    });
});
