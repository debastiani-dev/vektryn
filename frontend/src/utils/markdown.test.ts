import { describe, expect, it } from "vitest";
import { parseInlineMarkdown, parseMarkdown } from "./markdown";

describe("parseInlineMarkdown", () => {
    it("parses bold, italic, inline code, and plain text segments", () => {
        const tokens = parseInlineMarkdown(
            "Built **high-throughput** *Kafka* pipelines in `Python`.",
        );
        expect(tokens).toEqual([
            { type: "text", value: "Built " },
            { type: "bold", value: "high-throughput" },
            { type: "text", value: " " },
            { type: "italic", value: "Kafka" },
            { type: "text", value: " pipelines in " },
            { type: "code", value: "Python" },
            { type: "text", value: "." },
        ]);
    });

    it("keeps unclosed delimiters and raw HTML tags as plain literal text", () => {
        const tokens = parseInlineMarkdown("Use <script>alert(1)</script> with *unclosed");
        expect(tokens).toEqual([
            { type: "text", value: "Use <script>alert(1)</script> with *unclosed" },
        ]);
    });
});

describe("parseMarkdown", () => {
    it("parses headings, unordered lists, ordered lists, dividers, and paragraphs", () => {
        const md = [
            "## Tailored Resume Bullets",
            "- Scaled **PostgreSQL** indexing across `pgvector`.",
            "- Reduced p99 latency by *40%*.",
            "",
            "---",
            "",
            "### Interview Prep",
            "1. How do you partition Kafka topics?",
            "2. Explain savepoint handling in Django.",
            "",
            "Closing paragraph line one",
            "continued on line two.",
        ].join("\n");

        const blocks = parseMarkdown(md);
        expect(blocks).toEqual([
            {
                type: "heading",
                level: 2,
                tokens: [{ type: "text", value: "Tailored Resume Bullets" }],
            },
            {
                type: "unordered_list",
                items: [
                    [
                        { type: "text", value: "Scaled " },
                        { type: "bold", value: "PostgreSQL" },
                        { type: "text", value: " indexing across " },
                        { type: "code", value: "pgvector" },
                        { type: "text", value: "." },
                    ],
                    [
                        { type: "text", value: "Reduced p99 latency by " },
                        { type: "italic", value: "40%" },
                        { type: "text", value: "." },
                    ],
                ],
            },
            { type: "divider" },
            {
                type: "heading",
                level: 3,
                tokens: [{ type: "text", value: "Interview Prep" }],
            },
            {
                type: "ordered_list",
                items: [
                    {
                        number: 1,
                        tokens: [{ type: "text", value: "How do you partition Kafka topics?" }],
                    },
                    {
                        number: 2,
                        tokens: [{ type: "text", value: "Explain savepoint handling in Django." }],
                    },
                ],
            },
            {
                type: "paragraph",
                tokens: [
                    {
                        type: "text",
                        value: "Closing paragraph line one continued on line two.",
                    },
                ],
            },
        ]);
    });

    it("preserves explicit numbering when paragraphs separate ordered items", () => {
        const md = [
            "1. First question?",
            "**Why they ask:** Context one.",
            "",
            "2. Second question?",
            "**Why they ask:** Context two.",
            "",
            "3. Third question?",
        ].join("\n");

        const orderedBlocks = parseMarkdown(md).filter((block) => block.type === "ordered_list");
        expect(orderedBlocks.map((block) => block.items[0].number)).toEqual([1, 2, 3]);
    });
});
