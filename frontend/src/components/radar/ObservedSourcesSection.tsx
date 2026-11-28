import { ExternalLink, Layers, Mail, Repeat } from "lucide-react";
import type { JobPostingSource } from "../../types/models";
import { formatAtsSource, formatExactDate, isMailtoUrl } from "../../utils/format";
import { formatRepostLabel, isDirectAtsSource } from "../../utils/radarFilters";

interface ObservedSourcesSectionProps {
    sources?: ReadonlyArray<JobPostingSource>;
    loading?: boolean;
    repostCount?: number;
    createdAt?: string | null;
    lastRepostedAt?: string | null;
}

function formatRepostHistorySummary(
    firstSeenExact: string | null,
    lastRepostExact: string | null,
    repostCount: number,
): string {
    const cycleLabel = repostCount === 1 ? "cycle" : "cycles";
    if (firstSeenExact && lastRepostExact) {
        return `First observed ${firstSeenExact} · Last reposted ${lastRepostExact} (${repostCount} ${cycleLabel}).`;
    }
    if (lastRepostExact) {
        return `Last reposted ${lastRepostExact} (${repostCount} ${cycleLabel}).`;
    }
    return `Observed across ${repostCount} repost ${cycleLabel}.`;
}

export function ObservedSourcesSection({
    sources = [],
    loading = false,
    repostCount = 0,
    createdAt = null,
    lastRepostedAt = null,
}: Readonly<ObservedSourcesSectionProps>) {
    const hasReposts = repostCount >= 1;
    if (!loading && sources.length === 0 && !hasReposts) {
        return null;
    }

    const firstSeenExact = formatExactDate(createdAt);
    const lastRepostExact = formatExactDate(lastRepostedAt);

    return (
        <section
            aria-label="Observed Sources"
            className="rounded-2xl border border-zinc-800/90 bg-zinc-900/45 p-4 ring-1 ring-inset ring-white/[0.03] sm:p-5"
        >
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                <h3 className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-zinc-300">
                    <Layers className="h-4 w-4 text-violet-400" />
                    Observed Sources
                    {sources.length > 0 && (
                        <span className="font-mono text-zinc-500">({sources.length})</span>
                    )}
                </h3>
                {hasReposts && (
                    <span className="inline-flex items-center gap-1 rounded-md bg-amber-500/15 px-2 py-0.5 text-[11px] font-semibold text-amber-300 ring-1 ring-amber-500/30">
                        <Repeat className="h-3 w-3" />
                        {formatRepostLabel(repostCount)}
                    </span>
                )}
            </div>

            {hasReposts && (
                <p className="mb-3 rounded-xl border border-amber-500/20 bg-amber-950/20 px-3 py-2 text-xs text-amber-200/90">
                    {formatRepostHistorySummary(firstSeenExact, lastRepostExact, repostCount)}
                </p>
            )}

            {loading ? (
                <div className="space-y-2 animate-pulse" aria-label="Loading observed sources">
                    <div className="h-9 w-full rounded-xl bg-zinc-800/70" />
                </div>
            ) : (
                sources.length > 0 && (
                    <ul className="space-y-2">
                        {sources.map((src) => {
                            const directAts = isDirectAtsSource(src.ats_source);
                            const isEmail = isMailtoUrl(src.apply_url);
                            const seenDate = formatExactDate(src.first_seen_at);
                            return (
                                <li
                                    key={src.uuid}
                                    className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-zinc-800/80 bg-zinc-950/60 px-3 py-2 text-xs"
                                >
                                    <div className="flex flex-wrap items-center gap-2 min-w-0">
                                        <span
                                            aria-label={src.is_active ? "Open" : "Closed"}
                                            title={
                                                src.is_active
                                                    ? "Active upstream"
                                                    : "Closed upstream"
                                            }
                                            className={`h-2 w-2 shrink-0 rounded-full ${
                                                src.is_active ? "bg-emerald-400" : "bg-zinc-600"
                                            }`}
                                        />
                                        <span className="font-medium text-zinc-100">
                                            {formatAtsSource(src.ats_source)}
                                        </span>
                                        {src.is_primary && (
                                            <span className="rounded-md bg-violet-500/15 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-violet-300 ring-1 ring-violet-500/30">
                                                Primary
                                            </span>
                                        )}
                                        {directAts && (
                                            <span className="rounded-md bg-emerald-500/10 px-1.5 py-0.5 text-[10px] font-medium text-emerald-300 ring-1 ring-emerald-500/25">
                                                Direct ATS
                                            </span>
                                        )}
                                        {seenDate && (
                                            <span className="font-mono text-[11px] text-zinc-500">
                                                Seen {seenDate}
                                            </span>
                                        )}
                                    </div>
                                    <a
                                        href={src.apply_url}
                                        target={isEmail ? undefined : "_blank"}
                                        rel={isEmail ? undefined : "noreferrer"}
                                        className="inline-flex items-center gap-1 rounded-lg border border-zinc-800 bg-zinc-900 px-2.5 py-1 text-[11px] font-medium text-zinc-200 transition hover:border-violet-500/40 hover:text-violet-200"
                                    >
                                        {isEmail ? "Email" : "Apply"}
                                        {isEmail ? (
                                            <Mail className="h-3 w-3" />
                                        ) : (
                                            <ExternalLink className="h-3 w-3" />
                                        )}
                                    </a>
                                </li>
                            );
                        })}
                    </ul>
                )
            )}
        </section>
    );
}
