import { describe, expect, it } from "vitest";
import {
    formatAtsSource,
    formatCategoryLabel,
    formatContractType,
    formatRegionEligibility,
    formatSalaryRange,
    formatScoreLabel,
    formatSeniority,
    formatUsdAnnual,
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

    it("maps AI fit scores to semantic visual themes and labels", () => {
        expect(formatScoreLabel(86)).toBe("86% AI Fit");
        expect(formatScoreLabel(null)).toBe("No AI Score");
        expect(scoreVisualTheme(88).caption).toBe("Strong Fit");
        expect(scoreVisualTheme(74).caption).toBe("Alert Fit");
        expect(scoreVisualTheme(55).caption).toBe("AI Fit");
        expect(scoreVisualTheme(null).caption).toBe("Cosine Sim");
    });
});
