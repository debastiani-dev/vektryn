import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { GapAnalysisDrawer } from "../components/radar/GapAnalysisDrawer";
import { JobPostingDrawer } from "../components/radar/JobPostingDrawer";
import { ObservedSourcesSection } from "../components/radar/ObservedSourcesSection";
import { MetadataFiltersPanel } from "../components/radar/RadarMetadataFilters";
import { RadarSearchToolbar } from "../components/radar/RadarSearchToolbar";
import type { JobPostingSource, MatchScore } from "../types/models";
import {
    EMPTY_METADATA_FILTERS,
    formatAdditionalSourcesTooltip,
    formatRepostLabel,
    formatRepostTooltip,
    isDirectAtsSource,
} from "./radarFilters";
import { hydrateRadarStateFromPreset, isPresetActive } from "./savedFilters";

const SAMPLE_SOURCES: JobPostingSource[] = [
    {
        uuid: "src-gh",
        ats_source: "greenhouse",
        apply_url: "https://boards.greenhouse.io/acme/jobs/1",
        is_primary: true,
        is_active: true,
        first_seen_at: "2026-11-10T10:00:00Z",
        last_seen_at: "2026-11-28T10:00:00Z",
    },
    {
        uuid: "src-rem",
        ats_source: "remotive",
        apply_url: "https://remotive.com/jobs/acme-1",
        is_primary: false,
        is_active: false,
        first_seen_at: "2026-11-12T10:00:00Z",
        last_seen_at: "2026-11-20T10:00:00Z",
    },
];

function makeMatch(): MatchScore {
    return {
        uuid: "match-dedup-1",
        job_posting: {
            uuid: "job-dedup-1",
            ats_source: "remotive",
            primary_source: "greenhouse",
            sources_count: 3,
            observed_sources: ["greenhouse", "remotive", "himalayas"],
            repost_count: 2,
            last_reposted_at: "2026-11-25T10:00:00Z",
            title: "Senior Backend Python Engineer",
            company_name: "Acme Corp",
            apply_url: "https://boards.greenhouse.io/acme/jobs/1",
            location_raw: "Remote - LATAM",
            seniority: "senior",
            contract_type: "b2b_contractor",
            work_mode: "remote",
            language: "en",
            region_eligibility: ["latam"],
            salary_min: "150000",
            salary_max: "180000",
            salary_currency: "USD",
            salary_period: "annual",
            tech_stack: ["python", "kafka"],
            is_active: true,
            posted_at: "2026-11-10T10:00:00Z",
            created_at: "2026-11-10T10:00:00Z",
        },
        resume_profile_uuid: "resume-1",
        resume_profile_label: "Backend EN",
        is_routed_winner: true,
        cosine_similarity: 0.94,
        fit_score: 90,
        matched_skills: ["python", "kafka"],
        missing_keywords: [],
        talking_points: ["Event-driven architecture"],
        gap_summary: "Strong backend alignment.",
        scoring_model: "gemini-3.5-flash-lite",
        created_at: "2026-11-10T10:00:00Z",
    };
}

describe("Spec #22 Cross-Source Dedup & Repost UI", () => {
    it("formats +N sources tooltip, repost badges, and Direct ATS detection", () => {
        expect(isDirectAtsSource("greenhouse")).toBe(true);
        expect(isDirectAtsSource("remotive")).toBe(false);
        expect(isDirectAtsSource("manual")).toBe(false);

        expect(
            formatAdditionalSourcesTooltip("greenhouse", [
                "greenhouse",
                "remotive",
                "himalayas",
            ]),
        ).toBe("Also seen on Remotive, Himalayas");

        expect(formatRepostLabel(1)).toBe("Reposted");
        expect(formatRepostLabel(3)).toBe("Reposted ×3");
        const tooltip = formatRepostTooltip("2026-11-01T12:00:00Z", "2026-11-25T12:00:00Z");
        expect(tooltip).toContain("First observed");
        expect(tooltip).toContain("Last reposted");
    });

    it("renders Hide Reposts toggle in MetadataFiltersPanel and active chip in RadarSearchToolbar", () => {
        const filters = { ...EMPTY_METADATA_FILTERS, hideReposts: true };
        const panelHtml = renderToStaticMarkup(
            <MetadataFiltersPanel
                resumes={[]}
                resumeFilter=""
                minScore={0}
                filters={filters}
                onResumeChange={() => {}}
                onMinScoreChange={() => {}}
                onUpdateMetadata={() => {}}
            />,
        );
        expect(panelHtml).toContain("Hide Reposts");
        expect(panelHtml).toContain('id="radar-filter-hide-reposts"');
        expect(panelHtml).toContain("checked");

        const toolbarHtml = renderToStaticMarkup(
            <RadarSearchToolbar
                searchTerm=""
                debouncedSearch=""
                searchMode={null}
                loading={false}
                shownCount={1}
                totalCount={1}
                resumes={[]}
                resumeFilter=""
                minScore={0}
                evaluatedOnly={false}
                untrackedOnly={false}
                hideDismissed={true}
                hideMuted={true}
                hiddenMutedCount={0}
                sortBy="best_match"
                metadataFilters={filters}
                filtersOpen={false}
                hasActiveFilters={true}
                onSearchChange={() => {}}
                onCommitSearch={() => {}}
                onClearSearch={() => {}}
                onToggleEvaluatedOnly={() => {}}
                onToggleUntrackedOnly={() => {}}
                onOpenTriageModal={() => {}}
                onToggleFiltersOpen={() => {}}
                onSortChange={() => {}}
                onResumeChange={() => {}}
                onMinScoreChange={() => {}}
                onUpdateMetadata={() => {}}
                onRemoveChip={() => {}}
                onResetAll={() => {}}
            />,
        );
        expect(toolbarHtml).toContain("Reposts:");
        expect(toolbarHtml).toContain("Hidden");
    });

    it("persists hide_reposts in SavedFilter preset hydration and active matching", () => {
        const hydrated = hydrateRadarStateFromPreset({ hide_reposts: true }, []);
        expect(hydrated.metadataFilters.hideReposts).toBe(true);
        expect(isPresetActive(hydrated, { hide_reposts: true }, [])).toBe(true);
        expect(isPresetActive(hydrated, {}, [])).toBe(false);
    });

    it("renders ObservedSourcesSection with direct links, Primary/Direct ATS pills, status dots, and repost history", () => {
        const html = renderToStaticMarkup(
            <ObservedSourcesSection
                sources={SAMPLE_SOURCES}
                repostCount={2}
                createdAt="2026-11-10T10:00:00Z"
                lastRepostedAt="2026-11-25T10:00:00Z"
            />,
        );
        expect(html).toContain("Observed Sources");
        expect(html).toContain("Greenhouse");
        expect(html).toContain("Primary");
        expect(html).toContain("Direct ATS");
        expect(html).toContain("Remotive");
        expect(html).toContain("https://boards.greenhouse.io/acme/jobs/1");
        expect(html).toContain("https://remotive.com/jobs/acme-1");
        expect(html).toContain("Reposted ×2");
        expect(html).toContain("2 cycles");
    });

    it("renders primary source, Reposted ×N badge, and Observed Sources in JobPostingDrawer and GapAnalysisDrawer", () => {
        const match = makeMatch();
        const jobDrawerHtml = renderToStaticMarkup(
            <JobPostingDrawer
                jobPreview={match.job_posting}
                match={match}
                onClose={() => {}}
            />,
        );
        expect(jobDrawerHtml).toContain("Greenhouse");
        expect(jobDrawerHtml).toContain("Reposted ×2");
        expect(jobDrawerHtml).toContain("Observed Sources");

        const gapDrawerHtml = renderToStaticMarkup(
            <GapAnalysisDrawer
                match={match}
                saving={false}
                saved={false}
                onClose={() => {}}
                onSaveLead={() => {}}
            />,
        );
        expect(gapDrawerHtml).toContain("Greenhouse");
        expect(gapDrawerHtml).toContain("Reposted ×2");
        expect(gapDrawerHtml).toContain("Observed Sources");
    });
});
