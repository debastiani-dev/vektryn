import { Fragment } from "react";
import { parseMarkdown, type InlineToken, type MarkdownBlock } from "../../utils/markdown";

interface MarkdownContentProps {
    markdown: string;
    className?: string;
}

function renderInlineTokens(tokens: InlineToken[], keyPrefix: string) {
    return tokens.map((token, index) => {
        const key = `${keyPrefix}-${index}`;
        if (token.type === "bold") {
            return (
                <strong key={key} className="font-semibold text-zinc-100">
                    {token.value}
                </strong>
            );
        }
        if (token.type === "italic") {
            return (
                <em key={key} className="italic text-zinc-200">
                    {token.value}
                </em>
            );
        }
        if (token.type === "code") {
            return (
                <code
                    key={key}
                    className="rounded-md border border-zinc-700/80 bg-zinc-800/80 px-1.5 py-0.5 font-mono text-xs text-violet-200"
                >
                    {token.value}
                </code>
            );
        }
        return <Fragment key={key}>{token.value}</Fragment>;
    });
}

function renderHeading(
    level: 1 | 2 | 3,
    tokens: InlineToken[],
    key: string,
) {
    const content = renderInlineTokens(tokens, key);
    if (level === 1) {
        return (
            <h2 key={key} className="pt-1 text-base font-semibold text-zinc-100">
                {content}
            </h2>
        );
    }
    if (level === 2) {
        return (
            <h3
                key={key}
                className="pt-1 text-xs font-semibold uppercase tracking-wider text-violet-300"
            >
                {content}
            </h3>
        );
    }
    return (
        <h4 key={key} className="text-sm font-semibold text-zinc-200">
            {content}
        </h4>
    );
}

function renderBlock(block: MarkdownBlock, index: number) {
    const key = `md-${index}`;
    if (block.type === "divider") {
        return <hr key={key} className="border-zinc-800/90" />;
    }
    if (block.type === "heading") {
        return renderHeading(block.level, block.tokens, key);
    }
    if (block.type === "unordered_list") {
        return (
            <ul key={key} className="space-y-2.5 text-sm leading-relaxed text-zinc-300">
                {block.items.map((itemTokens, itemIndex) => (
                    <li key={`${key}-u-${itemIndex}`} className="flex gap-3">
                        <span className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-violet-400" />
                        <span>{renderInlineTokens(itemTokens, `${key}-u-${itemIndex}`)}</span>
                    </li>
                ))}
            </ul>
        );
    }
    if (block.type === "ordered_list") {
        return (
            <ol key={key} className="space-y-3 text-sm leading-relaxed text-zinc-300">
                {block.items.map((item, itemIndex) => (
                    <li key={`${key}-o-${itemIndex}`} className="flex gap-3">
                        <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-md bg-violet-500/15 font-mono text-xs font-semibold text-violet-300 ring-1 ring-violet-500/30">
                            {item.number}
                        </span>
                        <span>{renderInlineTokens(item.tokens, `${key}-o-${itemIndex}`)}</span>
                    </li>
                ))}
            </ol>
        );
    }
    return (
        <p key={key} className="text-sm leading-relaxed text-zinc-300">
            {renderInlineTokens(block.tokens, key)}
        </p>
    );
}

export function MarkdownContent({ markdown, className = "" }: Readonly<MarkdownContentProps>) {
    const blocks = parseMarkdown(markdown);
    return <div className={`space-y-3.5 ${className}`}>{blocks.map(renderBlock)}</div>;
}
