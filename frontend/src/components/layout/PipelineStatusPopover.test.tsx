import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { PersonalAnalyticsPanel } from "../analytics/PersonalAnalyticsPanel";
import { computePopoverCoords } from "../../utils/popoverPosition";

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

    it("renders PersonalAnalyticsPanel resume selector with mobile-safe flex truncation classes", () => {
        const html = renderToStaticMarkup(<PersonalAnalyticsPanel />);
        expect(html).toContain('id="personal-analytics-resume"');
        expect(html).toContain("min-w-0 max-w-full flex-1 truncate");
    });
});
