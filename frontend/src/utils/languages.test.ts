import { describe, expect, it } from "vitest";
import {
    filterLanguageOptions,
    formatKnownLanguageBadge,
    formatLanguageBadge,
    formatLanguageLabel,
    getLanguageName,
    getLanguageOptions,
    ISO_639_1_CODES,
    languageBadgeStyle,
} from "./languages";

describe("languages utility", () => {
    it("includes all 184 canonical ISO 639-1 codes without synthetic 'other'", () => {
        expect(ISO_639_1_CODES).toHaveLength(184);
        expect(ISO_639_1_CODES).toContain("en");
        expect(ISO_639_1_CODES).toContain("pt");
        expect(ISO_639_1_CODES).toContain("es");
        expect(ISO_639_1_CODES).toContain("de");
        expect(ISO_639_1_CODES).toContain("fr");
        expect(ISO_639_1_CODES).toContain("ja");
        expect(ISO_639_1_CODES).not.toContain("other");
        expect(ISO_639_1_CODES).not.toContain("unknown");
    });

    it("resolves human-readable names, uppercase badges, and labels", () => {
        expect(getLanguageName("pt")).toBe("Portuguese");
        expect(getLanguageName("EN")).toBe("English");
        expect(getLanguageName("aa")).toBe("Afar");
        expect(getLanguageName("ab")).toBe("Abkhazian");
        expect(getLanguageName("ae")).toBe("Avestan");
        expect(getLanguageName("tw")).toBe("Twi");
        expect(getLanguageName("unknown")).toBe("Unknown");
        expect(getLanguageName(undefined)).toBe("Unknown");

        const allNames = ISO_639_1_CODES.map((code) => getLanguageName(code));
        expect(allNames.every((name) => name.length > 2)).toBe(true);
        expect(new Set(allNames).size).toBe(184);

        expect(formatLanguageBadge("de")).toBe("DE");
        expect(formatLanguageBadge("unknown")).toBe("UNK");
        expect(formatKnownLanguageBadge("de")).toBe("DE");
        expect(formatKnownLanguageBadge("unknown")).toBeNull();
        expect(formatKnownLanguageBadge("")).toBeNull();

        expect(formatLanguageLabel("fr")).toBe("French (FR)");
        expect(formatLanguageLabel("unknown")).toBe("Unknown");
        expect(languageBadgeStyle("pt")).toContain("sky");
        expect(languageBadgeStyle("unknown")).toContain("zinc");
    });

    it("pins active-resume languages to the top without duplicating them", () => {
        const options = getLanguageOptions(["pt", "de", "unknown", "pt"]);
        expect(options).toHaveLength(ISO_639_1_CODES.length);
        expect(options[0].code).toBe("pt");
        expect(options[0].pinned).toBe(true);
        expect(options[1].code).toBe("de");
        expect(options[1].pinned).toBe(true);
        expect(options.filter((opt) => opt.code === "pt")).toHaveLength(1);
    });

    it("filters options by both language name and ISO 639-1 code", () => {
        const all = getLanguageOptions(["pt"]);
        expect(filterLanguageOptions(all, "portu").map((o) => o.code)).toContain("pt");
        expect(filterLanguageOptions(all, "de").some((o) => o.code === "de")).toBe(true);
        expect(filterLanguageOptions(all, "  ").length).toBe(all.length);
    });
});
