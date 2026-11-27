import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import type { MatchScore } from "../../types/models";
import { computePopoverCoords } from "../../utils/popoverPosition";
import { PersonalAnalyticsPanel } from "../analytics/PersonalAnalyticsPanel";
import { GapAnalysisDrawer } from "../radar/GapAnalysisDrawer";
import { JobPostingDrawer } from "../radar/JobPostingDrawer";

describe("Mobile layout hardening: PipelineStatusPopover & PersonalAnalyticsPanel", () => {
    it("clamps PipelineStatusPopover inside narrow mobile viewports when trigger is on the left", () => {
        const mobile = computePopoverCoords({ right: 170, bottom: 112 }, 360, 740);
        expect(mobile.left).toBe(12);
        expect(mobile.width).toBe(336);
        expect(mobile.left + mobile.width).toBeLessThanOrEqual(360 - 12);
        expect(mobile.top).toBe(122);
        expect(mobile.maxHeight).toBe(740 - 122 - 12);
    });

    it("clamps PipelineStatusPopover inside tablet viewports when header wraps", () => {
        const tablet = computePopoverCoords({ right: 190, bottom: 120 }, 768, 900);
        expect(tablet.left).toBe(12);
        expect(tablet.width).toBe(400);
        expect(tablet.left + tablet.width).toBeLessThanOrEqual(768 - 12);
    });

    it("right-aligns PipelineStatusPopover under the trigger on wide desktop viewports", () => {
        const desktop = computePopoverCoords({ right: 1100, bottom: 64 }, 1440, 900);
        expect(desktop.width).toBe(400);
        expect(desktop.left).toBe(700);
        expect(desktop.top).toBe(74);
    });

    it("clamps profile menu popover inside mobile viewports when header wraps to the left", () => {
        const mobileProfile = computePopoverCoords({ right: 130, bottom: 136 }, 360, 740, {
            desktopWidth: 240,
            mobileWidth: 240,
            minWidth: 220,
            offsetY: 8,
        });
        expect(mobileProfile.left).toBe(12);
        expect(mobileProfile.width).toBe(240);
        expect(mobileProfile.top).toBe(144);
        expect(mobileProfile.left + mobileProfile.width).toBeLessThanOrEqual(360 - 12);
    });

    it("renders PersonalAnalyticsPanel resume selector with mobile-safe flex truncation classes", () => {
        const html = renderToStaticMarkup(<PersonalAnalyticsPanel />);
        expect(html).toContain('id="personal-analytics-resume"');
        expect(html).toContain("min-w-0 max-w-full flex-1 truncate");
    });

    it("clamps GapAnalysisDrawer and JobPostingDrawer strictly to mobile viewport width", () => {
        const sampleMatch: MatchScore = {
            uuid: "match-mobile-1",
            job_posting: {
                uuid: "job-mobile-1",
                ats_source: "greenhouse",
                title: "Principal Distributed Systems Engineer",
                company_name: "Acme Cloud",
                apply_url: "https://example.com/jobs/1",
                location_raw: "Remote",
                seniority: "staff",
                contract_type: "pj",
                work_mode: "remote",
                region_eligibility: ["global"],
                salary_min: null,
                salary_max: null,
                salary_currency: null,
                salary_period: null,
                tech_stack: ["python"],
                is_active: true,
                posted_at: null,
            },
            resume_profile_uuid: "resume-1",
            cosine_similarity: 0.91,
            fit_score: 90,
            matched_skills: ["python"],
            missing_keywords: [],
            talking_points: ["Built resilient Kafka pipelines"],
            gap_summary: "Strong fit.",
            scoring_model: "gemini-3.5-flash-lite",
            created_at: "2026-11-27T12:00:00Z",
        };

        const gapHtml = renderToStaticMarkup(
            <GapAnalysisDrawer
                match={sampleMatch}
                saving={false}
                saved
                onClose={vi.fn()}
                onSaveLead={vi.fn()}
            />,
        );
        expect(gapHtml).toContain("max-w-[min(48rem,100vw)]");
        expect(gapHtml).toContain("min-w-0");
        expect(gapHtml).toContain("overflow-x-hidden");
        expect(gapHtml).toContain("h-dvh");

        const jobHtml = renderToStaticMarkup(
            <JobPostingDrawer jobPreview={sampleMatch.job_posting} onClose={vi.fn()} />,
        );
        expect(jobHtml).toContain("max-w-[min(48rem,100vw)]");
        expect(jobHtml).toContain("overflow-x-hidden");
        expect(jobHtml).toContain("h-dvh");
    });
});
