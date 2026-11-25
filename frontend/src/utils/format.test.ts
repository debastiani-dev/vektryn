import { describe, expect, it } from "vitest";
import {
    extractMailtoAddress,
    formatApplyLinkLabel,
    formatApplyLinkTooltip,
    formatAtsSource,
    formatCategoryLabel,
    formatContractType,
    formatRegionEligibility,
    formatSalaryRange,
    formatScoreLabel,
    formatSeniority,
    formatUsdAnnual,
    formatVectorSimilarity,
    isAlertMatch,
    isMailtoUrl,
    scoreBadgeStyle,
    scoreVisualTheme,
} from "./format";

describe("format utilities", () => {
    it("formats salary ranges across currencies and periods", () => {
        expect(formatSalaryRange("140000", "180000", "USD", "annual")).toBe("$140k–$180k/yr");
        expect(formatSalaryRange("15000", "15000", "BRL", "monthly")).toBe("R$15k/mo");
        expect(formatSalaryRange("85", "110", "EUR", "hourly")).toBe("€85–€110/hr");
        expect(formatSalaryRange(null, null, "USD", "annual")).toBeNull();
    });

    it("formats annual USD median compensation", () => {
        expect(formatUsdAnnual("165000")).toBe("$165k/yr");
        expect(formatUsdAnnual("0")).toBe("—");
        expect(formatUsdAnnual(null)).toBe("—");
    });

    it("formats domain labels cleanly", () => {
        expect(formatContractType("b2b_contractor")).toBe("B2B Contractor");
        expect(formatContractType("clt")).toBe("CLT");
        expect(formatSeniority("staff")).toBe("Staff");
        expect(formatSeniority("unknown")).toBe("");
        expect(formatRegionEligibility("north_america")).toBe("North America");
        expect(formatRegionEligibility("latam")).toBe("LATAM");
        expect(formatAtsSource("github_vagas")).toBe("Github Vagas");
        expect(formatCategoryLabel("ai_ml")).toBe("AI / ML");
    });

    it("separates Stage 2 AI fit themes/labels from unscored Stage 1 matches", () => {
        expect(formatScoreLabel(86.4)).toBe("86% AI Fit");
        expect(formatScoreLabel(null)).toBe("Not Scored");
        expect(formatScoreLabel(undefined)).toBe("Not Scored");

        // Alert-threshold AI score (default 70 and custom minAlertScore)
        const alertTheme = scoreVisualTheme(76);
        expect(alertTheme.caption).toBe("AI FIT");
        expect(alertTheme.tile).toContain("violet");
        expect(scoreBadgeStyle(76)).toContain("violet");
        expect(isAlertMatch(76)).toBe(true);
        expect(isAlertMatch(76, 80)).toBe(false);

        // Non-alert mid/good AI score
        const midTheme = scoreVisualTheme(64);
        expect(midTheme.caption).toBe("AI FIT");
        expect(midTheme.tile).toContain("emerald");
        expect(scoreBadgeStyle(64)).toContain("emerald");
        expect(isAlertMatch(64)).toBe(false);

        // Non-alert lower AI score
        const lowTheme = scoreVisualTheme(42);
        expect(lowTheme.caption).toBe("AI FIT");
        expect(lowTheme.tile).toContain("amber");
        expect(scoreBadgeStyle(42)).toContain("amber");

        // Unscored (null / undefined)
        const unscoredTheme = scoreVisualTheme(null);
        expect(unscoredTheme.caption).toBe("UNSCORED");
        expect(unscoredTheme.tile).toContain("zinc");
        expect(scoreBadgeStyle(null)).toContain("zinc");
        expect(isAlertMatch(null)).toBe(false);
        expect(isAlertMatch(undefined)).toBe(false);
    });

    it("formats Stage 1 vector similarity percentages cleanly", () => {
        expect(formatVectorSimilarity(0.796)).toBe("80% vector");
        expect(formatVectorSimilarity(0.624)).toBe("62% vector");
        expect(formatVectorSimilarity(0)).toBe("0% vector");
        expect(formatVectorSimilarity(1.1)).toBe("100% vector");
    });

    it("detects and formats mailto vs HTTP apply links cleanly", () => {
        expect(isMailtoUrl("mailto:hiring@acme.com")).toBe(true);
        expect(isMailtoUrl("MAILTO:jobs@acme.com")).toBe(true);
        expect(isMailtoUrl("https://acme.com/apply")).toBe(false);
        expect(extractMailtoAddress("mailto:hiring@acme.com")).toBe("hiring@acme.com");
        expect(formatApplyLinkLabel("mailto:hiring@acme.com", "Apply")).toBe("Apply via Email");
        expect(formatApplyLinkLabel("https://acme.com/apply", "Apply")).toBe("Apply");
        expect(formatApplyLinkTooltip("mailto:hiring@acme.com")).toBe(
            "Send application email to hiring@acme.com",
        );
        expect(formatApplyLinkTooltip("https://acme.com/apply", "Open link")).toBe("Open link");
        expect(formatAtsSource("manual")).toBe("Manual");
    });
});
