import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { LoginView } from "../auth/LoginView";
import { LandingPage } from "./LandingPage";
import {
    AnalyticsPreviewPanel,
    CopilotPreviewPanel,
    RadarPreviewPanel,
    TrackerPreviewPanel,
} from "./LandingPreviewShowcase";
import {
    INGESTED_SOURCES_STRIP,
    RADAR_PREVIEW_ROLES,
    cyclePreviewPriority,
    filterRadarPreviewRoles,
    getCopilotPreviewDraft,
    getNextPreviewTabId,
} from "./landingPreviewData";

describe("LandingPage and interactive coded preview helpers", () => {
    it("supports keyboard roving tab navigation with wrap-around", () => {
        expect(getNextPreviewTabId("radar", "ArrowRight")).toBe("copilot");
        expect(getNextPreviewTabId("analytics", "ArrowRight")).toBe("radar");
        expect(getNextPreviewTabId("radar", "ArrowLeft")).toBe("analytics");
        expect(getNextPreviewTabId("tracker", "Home")).toBe("radar");
        expect(getNextPreviewTabId("radar", "End")).toBe("analytics");
        expect(getNextPreviewTabId("radar", "Enter")).toBeNull();
    });

    it("filters static Job Radar preview roles by chip and hidden state", () => {
        const noneHidden = new Set<string>();
        expect(filterRadarPreviewRoles(RADAR_PREVIEW_ROLES, "all", noneHidden)).toHaveLength(3);
        expect(
            filterRadarPreviewRoles(RADAR_PREVIEW_ROLES, "high_fit", noneHidden).map((r) => r.id),
        ).toEqual(["role-1", "role-2"]);
        expect(
            filterRadarPreviewRoles(RADAR_PREVIEW_ROLES, "global", noneHidden).map((r) => r.id),
        ).toEqual(["role-1", "role-3"]);
        expect(
            filterRadarPreviewRoles(RADAR_PREVIEW_ROLES, "unapplied", noneHidden).map((r) => r.id),
        ).toEqual(["role-1", "role-3"]);
        expect(
            filterRadarPreviewRoles(RADAR_PREVIEW_ROLES, "all", new Set(["role-1", "role-2"])).map(
                (r) => r.id,
            ),
        ).toEqual(["role-3"]);
    });

    it("switches AI Copilot preview drafts and cycles Kanban priorities", () => {
        expect(getCopilotPreviewDraft("tailored_bullets").heading).toContain("Tailored Resume");
        expect(getCopilotPreviewDraft("cover_letter").heading).toContain("Cover Letter");
        expect(getCopilotPreviewDraft("recruiter_outreach").heading).toContain("Recruiter");

        expect(cyclePreviewPriority("low")).toBe("medium");
        expect(cyclePreviewPriority("medium")).toBe("high");
        expect(cyclePreviewPriority("high")).toBe("low");
    });

    it("renders LandingPage with sticky-safe wrapper, product-first preview, and zero <img> tags", () => {
        const html = renderToStaticMarkup(
            <LandingPage isAuthenticated={false} onSignIn={vi.fn()} onOpenWorkspace={vi.fn()} />,
        );

        expect(html).toContain("overflow-x-clip");
        expect(html).not.toContain("overflow-x-hidden");
        expect(html).toContain("Sign In");
        expect(html).toContain("Vekt-");
        expect(html).toContain("-ryn");
        expect(INGESTED_SOURCES_STRIP).toHaveLength(14);
        expect(html).toContain("Greenhouse");
        expect(html).toContain("Ashby");
        expect(html).toContain("Himalayas");
        expect(html).toContain("GitHub Vagas");
        expect(html).toContain('role="tablist"');
        expect(html).toContain('role="tab"');
        expect(html).toContain('role="tabpanel"');
        expect(html).toContain("Live Stream");
        expect(html).toContain("alex");
        expect(html).not.toContain(">rafa<");
        expect(html).toContain("debastiani.dev");
        expect(html).not.toContain("<img");
        expect(html.indexOf('id="preview"')).toBeLessThan(html.indexOf('id="capabilities"'));
    });

    it("renders Open Workspace CTA on LandingPage when already authenticated", () => {
        const html = renderToStaticMarkup(
            <LandingPage isAuthenticated onSignIn={vi.fn()} onOpenWorkspace={vi.fn()} />,
        );
        expect(html).toContain("Open Workspace");
    });

    it("renders all 4 real-app preview panels cleanly with zero <img> tags", () => {
        const panels = [
            renderToStaticMarkup(<RadarPreviewPanel />),
            renderToStaticMarkup(<CopilotPreviewPanel />),
            renderToStaticMarkup(<TrackerPreviewPanel />),
            renderToStaticMarkup(<AnalyticsPreviewPanel />),
        ];

        expect(panels[0]).toContain("Hybrid RRF");
        expect(panels[0]).toContain("92%");
        expect(panels[0]).toContain("Gap Details");
        expect(panels[1]).toContain("Fit Summary");
        expect(panels[1]).toContain("Matched Skills");
        expect(panels[1]).toContain("AI Copilot");
        expect(panels[2]).toContain("Follow-up overdue");
        expect(panels[3]).toContain("Application Funnel");
        expect(panels[3]).toContain("enrichment-worker");
        expect(panels[3]).toContain("matcher-worker");

        for (const panelHtml of panels) {
            expect(panelHtml).not.toContain("<img");
        }
    });

    it("renders Back to Vektryn link on LoginView when onBackToHome is provided", () => {
        const html = renderToStaticMarkup(
            <LoginView onAuthenticated={vi.fn()} onBackToHome={vi.fn()} />,
        );
        expect(html).toContain('href="/"');
        expect(html).toContain("Back to Vektryn");
    });
});
