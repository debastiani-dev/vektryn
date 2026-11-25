export type InlineToken =
    | { type: "text"; value: string }
    | { type: "bold"; value: string }
    | { type: "italic"; value: string }
    | { type: "code"; value: string };

export interface OrderedListItem {
    number: number;
    tokens: InlineToken[];
}

export type MarkdownBlock =
    | { type: "heading"; level: 1 | 2 | 3; tokens: InlineToken[] }
    | { type: "paragraph"; tokens: InlineToken[] }
    | { type: "unordered_list"; items: InlineToken[][] }
    | { type: "ordered_list"; items: OrderedListItem[] }
    | { type: "divider" };

const HEADING_RE = /^(#{1,3})\s+(.+)$/;
const UNORDERED_ITEM_RE = /^[-*+]\s+(.+)$/;
const ORDERED_ITEM_RE = /^(\d+)[.)]\s+(.+)$/;
const DIVIDER_RE = /^([-*_])\1{2,}$/;

interface InlineMatch {
    type: "code" | "bold" | "italic";
    content: string;
    nextIndex: number;
}

function tryMatchDelimited(
    text: string,
    index: number,
    delimiter: string,
    type: InlineMatch["type"],
): InlineMatch | null {
    if (!text.startsWith(delimiter, index)) {
        return null;
    }
    const contentStart = index + delimiter.length;
    const closeIndex = text.indexOf(delimiter, contentStart);
    if (closeIndex <= contentStart) {
        return null;
    }
    return {
        type,
        content: text.slice(contentStart, closeIndex),
        nextIndex: closeIndex + delimiter.length,
    };
}

function matchInlineAt(text: string, index: number): InlineMatch | null {
    const ch = text[index];
    if (ch === "`") {
        return tryMatchDelimited(text, index, "`", "code");
    }
    if (ch === "*" && text[index + 1] === "*") {
        return tryMatchDelimited(text, index, "**", "bold");
    }
    if (ch === "_" && text[index + 1] === "_") {
        return tryMatchDelimited(text, index, "__", "bold");
    }
    if (ch === "*") {
        return tryMatchDelimited(text, index, "*", "italic");
    }
    return null;
}

export function parseInlineMarkdown(input: string): InlineToken[] {
    const tokens: InlineToken[] = [];
    let buffer = "";
    let index = 0;

    const flushText = () => {
        if (buffer) {
            tokens.push({ type: "text", value: buffer });
            buffer = "";
        }
    };

    while (index < input.length) {
        const matched = matchInlineAt(input, index);
        if (matched) {
            flushText();
            tokens.push({ type: matched.type, value: matched.content });
            index = matched.nextIndex;
        } else {
            buffer += input[index];
            index += 1;
        }
    }

    flushText();
    return tokens;
}

function isBlockStarter(trimmed: string): boolean {
    return (
        HEADING_RE.test(trimmed) ||
        UNORDERED_ITEM_RE.test(trimmed) ||
        ORDERED_ITEM_RE.test(trimmed) ||
        DIVIDER_RE.test(trimmed)
    );
}

function consumeUnorderedList(
    lines: string[],
    startIndex: number,
): { items: InlineToken[][]; nextIndex: number } {
    const items: InlineToken[][] = [];
    let index = startIndex;

    while (index < lines.length) {
        const trimmed = lines[index].trim();
        const match = UNORDERED_ITEM_RE.exec(trimmed);
        if (!match) {
            break;
        }
        items.push(parseInlineMarkdown(match[1].trim()));
        index += 1;
    }

    return { items, nextIndex: index };
}

function consumeOrderedList(
    lines: string[],
    startIndex: number,
): { items: OrderedListItem[]; nextIndex: number } {
    const items: OrderedListItem[] = [];
    let index = startIndex;

    while (index < lines.length) {
        const trimmed = lines[index].trim();
        const match = ORDERED_ITEM_RE.exec(trimmed);
        if (!match) {
            break;
        }
        items.push({
            number: Number.parseInt(match[1], 10),
            tokens: parseInlineMarkdown(match[2].trim()),
        });
        index += 1;
    }

    return { items, nextIndex: index };
}

function consumeParagraph(
    lines: string[],
    startIndex: number,
): { tokens: InlineToken[]; nextIndex: number } {
    const parts: string[] = [];
    let index = startIndex;

    while (index < lines.length) {
        const trimmed = lines[index].trim();
        if (!trimmed || (parts.length > 0 && isBlockStarter(trimmed))) {
            break;
        }
        parts.push(trimmed);
        index += 1;
    }

    return {
        tokens: parseInlineMarkdown(parts.join(" ")),
        nextIndex: index,
    };
}

export function parseMarkdown(markdown: string): MarkdownBlock[] {
    const normalized = markdown.replaceAll("\r\n", "\n");
    const lines = normalized.split("\n");
    const blocks: MarkdownBlock[] = [];
    let index = 0;

    while (index < lines.length) {
        const trimmed = lines[index].trim();
        if (!trimmed) {
            index += 1;
            continue;
        }

        if (DIVIDER_RE.test(trimmed)) {
            blocks.push({ type: "divider" });
            index += 1;
            continue;
        }

        const headingMatch = HEADING_RE.exec(trimmed);
        if (headingMatch) {
            const level = Math.min(3, headingMatch[1].length) as 1 | 2 | 3;
            blocks.push({
                type: "heading",
                level,
                tokens: parseInlineMarkdown(headingMatch[2].trim()),
            });
            index += 1;
            continue;
        }

        if (UNORDERED_ITEM_RE.test(trimmed)) {
            const { items, nextIndex } = consumeUnorderedList(lines, index);
            blocks.push({ type: "unordered_list", items });
            index = nextIndex;
            continue;
        }

        if (ORDERED_ITEM_RE.test(trimmed)) {
            const { items, nextIndex } = consumeOrderedList(lines, index);
            blocks.push({ type: "ordered_list", items });
            index = nextIndex;
            continue;
        }

        const { tokens, nextIndex } = consumeParagraph(lines, index);
        blocks.push({ type: "paragraph", tokens });
        index = nextIndex;
    }

    return blocks;
}
