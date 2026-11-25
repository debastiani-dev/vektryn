import { describe, expect, it } from "vitest";
import {
    hydrateRadarStateFromPreset,
    isPresetActive,
    serializeRadarStateToPreset,
} from "./savedFilters";

describe("savedFilters helpers", () => {
    const resumes = [{ uuid: "resume-a" }, { uuid: "resume-b" }];

    it("serializes only active non-default radar filter fields", () => {
        const serialized = serializeRadarStateToPreset({
            searchTerm: "  python kafka  ",
            resumeFilter: "resume-a",
            minScore: 80,
            evaluatedOnly: true,
            metadataFilters: {
                seniority: "senior",
                contractType: "pj",
                region: "brazil",
                atsSource: "",
            },
            sortBy: "posted_at",
        });

        expect(serialized).toEqual({
            search: "python kafka",
            resume_profile: "resume-a",
            min_score: 80,
            evaluated_only: true,
            seniority: "senior",
            contract_type: "pj",
            region: "brazil",
            sort_by: "posted_at",
        });
    });

    it("falls back to All Resumes when a preset references a deleted resume_profile", () => {
        const hydrated = hydrateRadarStateFromPreset(
            {
                resume_profile: "deleted-resume-uuid",
                seniority: "staff",
                min_score: 70,
                sort_by: "newest",
            },
            resumes,
        );

        expect(hydrated.resumeFilter).toBe("");
        expect(hydrated.metadataFilters.seniority).toBe("staff");
        expect(hydrated.minScore).toBe(70);
        expect(hydrated.sortBy).toBe("newest");
    });

    it("matches active preset state accurately", () => {
        const state = hydrateRadarStateFromPreset(
            { search: "django", region: "latam", evaluated_only: true },
            resumes,
        );
        expect(
            isPresetActive(state, { search: "django", region: "latam", evaluated_only: true }, resumes),
        ).toBe(true);
        expect(isPresetActive(state, { search: "rust", region: "latam" }, resumes)).toBe(false);
    });
});
