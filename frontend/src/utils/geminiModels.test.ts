import { describe, expect, it } from "vitest";
import { ApiError } from "../api/client";
import {
    classifyCopilotError,
    findGeminiModelOption,
    formatGeminiKeyBadge,
    GEMINI_MODEL_OPTIONS,
    GOOGLE_AI_STUDIO_KEY_URL,
} from "./geminiModels";

describe("geminiModels helpers", () => {
    it("exposes auto plus all 6 curated Gemini 3.5/3.8/4 models with tier badges", () => {
        expect(GEMINI_MODEL_OPTIONS.map((opt) => opt.value)).toEqual([
            "auto",
            "gemini-4-carbon",
            "gemini-4-neon",
            "gemini-4-argon",
            "gemini-4-hydrogen",
            "gemini-3.8-flash",
            "gemini-3.5-flash-lite",
        ]);
        expect(findGeminiModelOption("gemini-4-carbon").tier).toBe("paid");
        expect(findGeminiModelOption("gemini-4-hydrogen").tier).toBe("free");
        expect(GOOGLE_AI_STUDIO_KEY_URL).toBe("https://aistudio.google.com/apikey");
    });

    it("formats masked key status badges cleanly", () => {
        expect(formatGeminiKeyBadge(false, "")).toBe("Not configured");
        expect(formatGeminiKeyBadge(true, "9f2a")).toBe("Configured ••••9f2a");
        expect(formatGeminiKeyBadge(true, "")).toBe("Configured");
    });

    it("classifies BYOK Copilot errors with settings CTA and non-BYOK rate limits without it", () => {
        const missing = classifyCopilotError(
            new ApiError(400, "{}", "Add key", null, {}, "byok_missing", false),
        );
        expect(missing.showSettingsAction).toBe(true);
        expect(missing.message).toBe("Add key");

        const invalid = classifyCopilotError(
            new ApiError(403, "{}", "Invalid key", null, {}, "byok_invalid", false),
        );
        expect(invalid.showSettingsAction).toBe(true);

        const depleted = classifyCopilotError(
            new ApiError(429, "{}", null, null, {}, "byok_quota_exhausted", true),
        );
        expect(depleted.showSettingsAction).toBe(true);
        expect(depleted.message.toLowerCase()).toContain("prepayment credits");

        const burstLimit = classifyCopilotError(
            new ApiError(429, "{}", "Rate limit", 30, {}, "copilot_rate_limited", false),
        );
        expect(burstLimit.showSettingsAction).toBe(false);
        expect(burstLimit.message).toContain("30s");
    });
});
