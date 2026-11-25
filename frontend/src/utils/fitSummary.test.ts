import { describe, expect, it } from "vitest";
import { splitLegacySummaryParagraphs, splitSummarySentences } from "./fitSummary";

describe("splitSummarySentences", () => {
    it("preserves tech names, decimals, and common abbreviations", () => {
        const text =
            "Your Node.js and Python 3.12 experience (e.g. FastAPI services) fits well. You also led U.S. enterprise rollouts.";
        expect(splitSummarySentences(text)).toEqual([
            "Your Node.js and Python 3.12 experience (e.g. FastAPI services) fits well.",
            "You also led U.S. enterprise rollouts.",
        ]);
    });
});

describe("splitLegacySummaryParagraphs", () => {
    it("splits long legacy single-block summaries into lead sentence + 2-sentence paragraphs", () => {
        const raw = [
            "This role is a strong match for your senior backend engineering profile.",
            "Your production work with Python, Django, and PostgreSQL maps directly to their core stack.",
            "Building Kafka event pipelines aligns cleanly with their ingestion scope.",
            "Your track record owning end-to-end architecture matches Staff-level expectations.",
        ].join(" ");

        expect(splitLegacySummaryParagraphs(raw)).toEqual([
            "This role is a strong match for your senior backend engineering profile.",
            "Your production work with Python, Django, and PostgreSQL maps directly to their core stack. Building Kafka event pipelines aligns cleanly with their ingestion scope.",
            "Your track record owning end-to-end architecture matches Staff-level expectations.",
        ]);
    });

    it("preserves explicit paragraph breaks without re-chunking", () => {
        const raw = "First paragraph.\n\nSecond paragraph with detail.";
        expect(splitLegacySummaryParagraphs(raw)).toEqual([
            "First paragraph.",
            "Second paragraph with detail.",
        ]);
    });

    it("keeps short 1-2 sentence legacy summaries as a single paragraph", () => {
        expect(splitLegacySummaryParagraphs("Strong overall fit. Solid Python overlap.")).toEqual([
            "Strong overall fit. Solid Python overlap.",
        ]);
    });
});
