import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, it, vi } from "vitest";
import { vektrynApi } from "../api/client";
import { LiveAlertBanner } from "../components/layout/LiveAlertBanner";
import { NotificationCard } from "../components/layout/NotificationCenter";
import { CopilotPanel } from "../components/radar/CopilotPanel";
import { GapAnalysisDrawer } from "../components/radar/GapAnalysisDrawer";
import { JobPostingDrawer } from "../components/radar/JobPostingDrawer";
import { MetadataFiltersPanel } from "../components/radar/RadarMetadataFilters";
import { RadarSearchToolbar } from "../components/radar/RadarSearchToolbar";
import type { LiveMatchAlert, MatchScore, NotificationItem, ResumeProfile } from "../types/models";
import { alertToNotification } from "./notifications";
import { EMPTY_METADATA_FILTERS } from "./radarFilters";

function makeResume(overrides: Partial<ResumeProfile> = {}): ResumeProfile {
    return {
        uuid: "resume-en",
        label: "Backend EN",
        source_file_gcs_uri: "",
        raw_text: "Senior Python Engineer",
        content_hash: "0".repeat(64),
        extracted_skills: ["python"],
        language: "en",
        strict_language_match: false,
        target_seniority: ["senior"],
        target_contract_types: ["b2b_contractor"],
        target_regions: ["worldwide"],
        target_work_modes: ["remote"],
        min_alert_score: 75,
        is_active: true,
        has_embedding: true,
        created_at: "2026-11-27T10:00:00Z",
        modified_at: "2026-11-27T10:00:00Z",
        ...overrides,
    };
}

function makeMatch(overrides: Partial<MatchScore> = {}): MatchScore {
    return {
        uuid: "match-1",
        job_posting: {
            uuid: "job-1",
            ats_source: "greenhouse",
            title: "Engenheiro Backend Python Senior",
            company_name: "Nubank",
            apply_url: "https://example.com/jobs/1",
            location_raw: "Sao Paulo - Remote",
            seniority: "senior",
            contract_type: "clt",
            work_mode: "remote",
            language: "pt",
            region_eligibility: ["brazil"],
            salary_min: null,
            salary_max: null,
            salary_currency: null,
            salary_period: null,
            tech_stack: ["python", "django"],
            is_active: true,
            posted_at: null,
        },
        resume_profile_uuid: "resume-pt",
        resume_profile_label: "Backend PT-BR",
        resume_profile_summary: {
            uuid: "resume-pt",
            label: "Backend PT-BR",
            language: "pt",
        },
        is_routed_winner: true,
        cosine_similarity: 0.91,
        fit_score: 88,
        matched_skills: ["python", "django"],
        missing_keywords: [],
        talking_points: ["Experiencia com Django em escala"],
        gap_summary: "Excelente alinhamento.",
        scoring_model: "gemini-3.5-flash-lite",
        created_at: "2026-11-27T12:00:00Z",
        ...overrides,
    };
}

describe("Spec #21 Multi-Resume & Multilingual UI", () => {
    afterEach(() => {
        vi.restoreAllMocks();
        vi.unstubAllGlobals();
    });

    it("promotes All Active Resumes (Auto-Matched) selector to Row 1 when >= 2 active resumes", () => {
        const resumes = [
            makeResume({ uuid: "r-en", label: "Backend EN", language: "en", is_active: true }),
            makeResume({ uuid: "r-pt", label: "Backend PT", language: "pt", is_active: true }),
        ];
        const html = renderToStaticMarkup(
            <RadarSearchToolbar
                searchTerm=""
                debouncedSearch=""
                searchMode={null}
                loading={false}
                shownCount={2}
                totalCount={2}
                resumes={resumes}
                resumeFilter=""
                minScore={0}
                evaluatedOnly={false}
                untrackedOnly={false}
                hideDismissed={true}
                hideMuted={true}
                hiddenMutedCount={0}
                sortBy="best_match"
                metadataFilters={EMPTY_METADATA_FILTERS}
                filtersOpen={false}
                hasActiveFilters={false}
                onSearchChange={vi.fn()}
                onCommitSearch={vi.fn()}
                onClearSearch={vi.fn()}
                onToggleEvaluatedOnly={vi.fn()}
                onToggleUntrackedOnly={vi.fn()}
                onOpenTriageModal={vi.fn()}
                onToggleFiltersOpen={vi.fn()}
                onSortChange={vi.fn()}
                onResumeChange={vi.fn()}
                onMinScoreChange={vi.fn()}
                onUpdateMetadata={vi.fn()}
                onRemoveChip={vi.fn()}
                onResetAll={vi.fn()}
            />,
        );
        expect(html).toContain('id="radar-toolbar-resume"');
        expect(html).toContain("All Active Resumes (Auto-Matched)");
        expect(html).toContain("Backend EN (EN)");
        expect(html).toContain("Backend PT (PT)");
    });

    it("renders searchable Language filter in MetadataFiltersPanel", () => {
        const html = renderToStaticMarkup(
            <MetadataFiltersPanel
                resumes={[makeResume({ language: "pt" })]}
                resumeFilter=""
                minScore={0}
                filters={{ ...EMPTY_METADATA_FILTERS, language: "pt" }}
                onResumeChange={vi.fn()}
                onMinScoreChange={vi.fn()}
                onUpdateMetadata={vi.fn()}
            />,
        );
        expect(html).toContain('id="radar-filter-language"');
        expect(html).toContain("Portuguese");
        expect(html).toContain("PT");
    });

    it("renders matched-resume and ISO language badges in drawers and Copilot panel", () => {
        const match = makeMatch();
        const gapHtml = renderToStaticMarkup(
            <GapAnalysisDrawer
                match={match}
                saving={false}
                saved={false}
                onClose={vi.fn()}
                onSaveLead={vi.fn()}
            />,
        );
        expect(gapHtml).toContain("Scored with Backend PT-BR");
        expect(gapHtml).toContain("PT");

        const copilotHtml = renderToStaticMarkup(<CopilotPanel match={match} />);
        expect(copilotHtml).toContain("Scored &amp; drafted using");
        expect(copilotHtml).toContain("Backend PT-BR");
        expect(copilotHtml).toContain("PT");

        const jobHtml = renderToStaticMarkup(
            <JobPostingDrawer jobPreview={match.job_posting} match={match} onClose={vi.fn()} />,
        );
        expect(jobHtml).toContain("PT");
    });

    it("renders matched-resume and language metadata in LiveAlertBanner and NotificationCenter", () => {
        const alert: LiveMatchAlert = {
            event_id: "evt-1",
            user_id: "user-1",
            match_score_uuid: "match-1",
            job_posting_uuid: "job-1",
            resume_profile_uuid: "resume-pt",
            resume_profile_label: "Backend PT-BR",
            resume_language: "pt",
            title: "Engenheiro Backend Python Senior",
            company_name: "Nubank",
            fit_score: 88,
            cosine_similarity: 0.91,
            matched_skills: ["python"],
            missing_keywords: [],
            apply_url: "https://example.com/jobs/1",
        };

        const bannerHtml = renderToStaticMarkup(
            <LiveAlertBanner alerts={[alert]} onDismiss={vi.fn()} />,
        );
        expect(bannerHtml).toContain("Backend PT-BR");
        expect(bannerHtml).toContain("PT");

        const notif: NotificationItem = alertToNotification(alert);
        expect(notif.payload.resume_profile_label).toBe("Backend PT-BR");
        expect(notif.payload.resume_language).toBe("pt");

        const centerHtml = renderToStaticMarkup(
            <NotificationCard
                item={notif}
                isOpeningGap={false}
                isSavingJob={false}
                isSavedJob={false}
                onOpenGapDetails={vi.fn()}
                onSaveToTracker={vi.fn()}
                onOpenTracker={vi.fn()}
                onOpenRadar={vi.fn()}
                onMarkRead={vi.fn()}
                onDismiss={vi.fn()}
            />,
        );
        expect(centerHtml).toContain("Backend PT-BR");
        expect(centerHtml).toContain("PT");
    });

    it("serializes language, strict_language_match on resumes and resume_profile on lead PATCH", async () => {
        vi.stubGlobal("document", { cookie: "csrftoken=lang-csrf" });
        const fetchMock = vi
            .fn()
            .mockResolvedValueOnce(
                new Response(JSON.stringify({ uuid: "r1", language: "pt" }), {
                    status: 201,
                    headers: { "Content-Type": "application/json" },
                }),
            )
            .mockResolvedValueOnce(
                new Response(JSON.stringify({ uuid: "r2", language: "de" }), {
                    status: 201,
                    headers: { "Content-Type": "application/json" },
                }),
            )
            .mockResolvedValueOnce(
                new Response(JSON.stringify({ uuid: "lead-1", resume_profile: "r2" }), {
                    status: 200,
                    headers: { "Content-Type": "application/json" },
                }),
            );
        vi.stubGlobal("fetch", fetchMock);

        await vektrynApi.createResume({
            label: "PT CV",
            raw_text: "Engenheiro Senior Python",
            language: "pt",
            strict_language_match: true,
        });
        const [, jsonInit] = fetchMock.mock.calls[0] as [string, RequestInit];
        expect(typeof jsonInit.body).toBe("string");
        expect(JSON.parse(jsonInit.body as string)).toMatchObject({
            language: "pt",
            strict_language_match: true,
        });

        const file = new File(["Senior Entwickler"], "cv_de.txt", { type: "text/plain" });
        await vektrynApi.createResume({
            label: "DE CV",
            file,
            language: "de",
            strict_language_match: true,
        });
        const [, formInit] = fetchMock.mock.calls[1] as [string, RequestInit];
        expect(formInit.body).toBeInstanceOf(FormData);
        expect((formInit.body as FormData).get("language")).toBe("de");
        expect((formInit.body as FormData).get("strict_language_match")).toBe("true");

        await vektrynApi.updateLead("lead-1", { resume_profile: "r2" });
        const [, leadInit] = fetchMock.mock.calls[2] as [string, RequestInit];
        expect(typeof leadInit.body).toBe("string");
        expect(JSON.parse(leadInit.body as string)).toEqual({ resume_profile: "r2" });
    });
});
