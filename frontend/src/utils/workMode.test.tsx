import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, it, vi } from "vitest";
import { vektrynApi } from "../api/client";
import { GapAnalysisDrawer } from "../components/radar/GapAnalysisDrawer";
import { JobPostingDrawer } from "../components/radar/JobPostingDrawer";
import { MetadataFiltersPanel } from "../components/radar/RadarMetadataFilters";
import { TargetWorkModesField } from "../components/resumes/ResumesView";
import type { MatchScore, WorkMode } from "../types/models";
import { formatWorkMode, workModeBadgeStyle } from "./format";
import { EMPTY_METADATA_FILTERS } from "./radarFilters";

describe("Spec #20 Work Mode UI & API helpers", () => {
    afterEach(() => {
        vi.restoreAllMocks();
        vi.unstubAllGlobals();
    });

    it("formats work modes and resolves distinct badge styles", () => {
        const modes: Array<[WorkMode, string, string]> = [
            ["remote", "Remote", "emerald"],
            ["hybrid", "Hybrid", "amber"],
            ["onsite", "On-site", "rose"],
            ["unknown", "Unknown", "zinc"],
        ];
        for (const [mode, label, tone] of modes) {
            expect(formatWorkMode(mode)).toBe(label);
            expect(workModeBadgeStyle(mode)).toContain(tone);
        }
        expect(formatWorkMode(undefined)).toBe("Unknown");
    });

    it("renders TargetWorkModesField with Remote pre-selected and Unknown helper copy", () => {
        const html = renderToStaticMarkup(
            <TargetWorkModesField selected={["remote"]} onToggle={vi.fn()} />,
        );
        expect(html).toContain("Target Work Modes");
        expect(html).toContain('aria-pressed="true"');
        expect(html).toContain("Remote");
        expect(html).toContain("Hybrid");
        expect(html).toContain("On-site");
        expect(html).toContain("Unknown");
        expect(html).toContain("couldn&#x27;t be extracted by AI");
    });

    it("renders Work Mode filter in MetadataFiltersPanel with all options", () => {
        const html = renderToStaticMarkup(
            <MetadataFiltersPanel
                resumes={[]}
                resumeFilter=""
                minScore={0}
                filters={{ ...EMPTY_METADATA_FILTERS, workMode: "hybrid" }}
                onResumeChange={vi.fn()}
                onMinScoreChange={vi.fn()}
                onUpdateMetadata={vi.fn()}
            />,
        );
        expect(html).toContain('id="radar-filter-work-mode"');
        expect(html).toContain("All work modes");
        expect(html).toContain("Remote");
        expect(html).toContain("Hybrid");
        expect(html).toContain("On-site");
        expect(html).toContain("Unknown");
    });

    it("renders work mode badges in JobPostingDrawer and GapAnalysisDrawer", () => {
        const jobHtml = renderToStaticMarkup(
            <JobPostingDrawer
                jobPreview={{
                    uuid: "job-1",
                    title: "Senior Python Engineer",
                    company_name: "Acme Cloud",
                    apply_url: "https://example.com/jobs/1",
                    seniority: "senior",
                    contract_type: "pj",
                    work_mode: "hybrid",
                    is_active: true,
                }}
                onClose={vi.fn()}
            />,
        );
        expect(jobHtml).toContain("Hybrid");

        const sampleMatch: MatchScore = {
            uuid: "match-1",
            job_posting: {
                uuid: "job-1",
                ats_source: "greenhouse",
                title: "Staff Python Engineer",
                company_name: "Acme Cloud",
                apply_url: "https://example.com/jobs/1",
                location_raw: "Remote - LATAM",
                seniority: "staff",
                contract_type: "pj",
                work_mode: "remote",
                region_eligibility: ["brazil"],
                salary_min: null,
                salary_max: null,
                salary_currency: null,
                salary_period: null,
                tech_stack: ["python", "django"],
                is_active: true,
                posted_at: null,
            },
            resume_profile_uuid: "resume-1",
            cosine_similarity: 0.88,
            fit_score: 86,
            matched_skills: ["python"],
            missing_keywords: [],
            talking_points: ["Built APIs"],
            gap_summary: "Strong fit.",
            scoring_model: "gemini-3.5-flash-lite",
            created_at: "2026-11-27T12:00:00Z",
        };
        const gapHtml = renderToStaticMarkup(
            <GapAnalysisDrawer
                match={sampleMatch}
                saving={false}
                saved={false}
                onClose={vi.fn()}
                onSaveLead={vi.fn()}
            />,
        );
        expect(gapHtml).toContain("Remote");
    });

    it("serializes target_work_modes on JSON and multipart resume creation", async () => {
        vi.stubGlobal("document", { cookie: "csrftoken=wm-csrf" });
        const fetchMock = vi
            .fn()
            .mockResolvedValueOnce(
                new Response(JSON.stringify({ uuid: "r1", target_work_modes: ["remote"] }), {
                    status: 201,
                    headers: { "Content-Type": "application/json" },
                }),
            )
            .mockResolvedValueOnce(
                new Response(JSON.stringify({ uuid: "r2", target_work_modes: [] }), {
                    status: 201,
                    headers: { "Content-Type": "application/json" },
                }),
            );
        vi.stubGlobal("fetch", fetchMock);

        await vektrynApi.createResume({
            label: "Remote CV",
            raw_text: "Senior Python engineer",
            target_work_modes: ["remote", "unknown"],
        });
        const [, jsonInit] = fetchMock.mock.calls[0] as [string, RequestInit];
        expect(JSON.parse(String(jsonInit.body))).toMatchObject({
            target_work_modes: ["remote", "unknown"],
        });

        const file = new File(["Senior Python"], "cv.txt", { type: "text/plain" });
        await vektrynApi.createResume({
            label: "Any CV",
            file,
            target_work_modes: [],
        });
        const [, formInit] = fetchMock.mock.calls[1] as [string, RequestInit];
        expect(formInit.body).toBeInstanceOf(FormData);
        expect((formInit.body as FormData).getAll("target_work_modes")).toEqual([""]);
    });
});
