const ABBREVIATIONS = new Set([
    "e.g.",
    "i.e.",
    "vs.",
    "etc.",
    "u.s.",
    "u.k.",
    "sr.",
    "jr.",
    "dr.",
    "mr.",
    "ms.",
    "mrs.",
    "inc.",
    "ltd.",
    "corp.",
]);

function endsWithAbbreviation(text: string): boolean {
    const rawToken = text.split(/\s+/).at(-1)?.toLowerCase() ?? "";
    const lastToken = rawToken.replace(/^["'([{\s]+/, "");
    return ABBREVIATIONS.has(lastToken);
}

export function splitSummarySentences(block: string): string[] {
    const normalized = block.replaceAll(/\s+/g, " ").trim();
    if (!normalized) {
        return [];
    }

    const sentences: string[] = [];
    let start = 0;

    for (let i = 0; i < normalized.length; i += 1) {
        const ch = normalized[i];
        if (ch !== "." && ch !== "!" && ch !== "?") {
            continue;
        }
        const nextChar = normalized[i + 1];
        const afterSpace = normalized[i + 2];
        if (nextChar !== " " || !afterSpace || !/[A-Z"'(]/.test(afterSpace)) {
            continue;
        }

        const candidate = normalized.slice(start, i + 1).trim();
        if (ch === "." && endsWithAbbreviation(candidate)) {
            continue;
        }
        if (candidate) {
            sentences.push(candidate);
        }
        start = i + 2;
    }

    const tail = normalized.slice(start).trim();
    if (tail) {
        sentences.push(tail);
    }

    return sentences;
}

/**
 * Fallback readability helper for legacy flat gap_summary rows that predate
 * structured fit_highlights / watchout_note fields: preserves explicit paragraph
 * breaks and groups long single-block prose into concise 2-sentence paragraphs.
 */
export function splitLegacySummaryParagraphs(raw: string | null | undefined): string[] {
    const trimmed = (raw ?? "").trim();
    if (!trimmed) {
        return [];
    }

    const explicitParagraphs = trimmed
        .split(/\n{2,}/)
        .map((p) => p.replaceAll(/\s+/g, " ").trim())
        .filter(Boolean);

    if (explicitParagraphs.length > 1) {
        return explicitParagraphs;
    }

    const sentences = splitSummarySentences(explicitParagraphs[0]);
    if (sentences.length <= 2) {
        return sentences.length > 0 ? [sentences.join(" ")] : [];
    }

    const paragraphs: string[] = [sentences[0]];
    for (let i = 1; i < sentences.length; i += 2) {
        paragraphs.push(sentences.slice(i, i + 2).join(" "));
    }
    return paragraphs;
}
