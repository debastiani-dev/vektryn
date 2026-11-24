import { ArrowDown, ArrowUp, ArrowUpDown, BarChart3 } from "lucide-react";
import { useEffect, useState } from "react";
import { vektrynApi } from "../../api/client";
import type { StackTrendDaily, TechCategory } from "../../types/models";
import { categoryBadgeStyle, formatCategoryLabel, formatUsdAnnual } from "../../utils/format";
import { Tooltip } from "../ui/Tooltip";

type SortColumn = "mention_count" | "unique_companies_count" | "median_annual_usd" | "bucket_date";
type SortDirection = "asc" | "desc";

const CATEGORIES: Array<{ id: TechCategory | "all"; label: string }> = [
    { id: "all", label: "All Categories" },
    { id: "language", label: "Languages" },
    { id: "framework", label: "Frameworks" },
    { id: "database", label: "Databases" },
    { id: "broker", label: "Brokers" },
    { id: "cloud", label: "Cloud" },
    { id: "devops", label: "DevOps" },
    { id: "ai_ml", label: "AI / ML" },
];

function parseNumericSalary(raw: string | null): number {
    if (!raw) return -1;
    const val = Number(raw);
    return Number.isFinite(val) ? val : -1;
}

function rankBadgeStyle(rank: number): string {
    if (rank === 1) return "bg-amber-500/15 text-amber-300 ring-1 ring-amber-500/35";
    if (rank === 2) return "bg-zinc-400/15 text-zinc-200 ring-1 ring-zinc-400/30";
    if (rank === 3) return "bg-orange-500/15 text-orange-300 ring-1 ring-orange-500/30";
    return "text-zinc-500";
}

function TrendsSkeleton() {
    return (
        <div
            className="overflow-hidden rounded-2xl border border-zinc-800/80 bg-zinc-900/45"
            aria-label="Loading stack demand trends"
        >
            <div className="border-b border-zinc-800 bg-zinc-900/90 px-6 py-4">
                <div className="h-4 w-48 animate-pulse rounded bg-zinc-800" />
            </div>
            <div className="divide-y divide-zinc-800/70">
                {[0, 1, 2, 3, 4, 5].map((row) => (
                    <div key={row} className="flex animate-pulse items-center gap-6 px-6 py-4">
                        <div className="h-5 w-8 rounded bg-zinc-800/70" />
                        <div className="h-5 w-28 rounded bg-zinc-800" />
                        <div className="h-5 w-20 rounded-md bg-zinc-800/70" />
                        <div className="h-3 w-44 rounded-full bg-zinc-800/70" />
                        <div className="ml-auto h-5 w-16 rounded bg-zinc-800/70" />
                    </div>
                ))}
            </div>
        </div>
    );
}

export function StackTrendsView() {
    const [trends, setTrends] = useState<StackTrendDaily[]>([]);
    const [category, setCategory] = useState<TechCategory | "all">("all");
    const [sortBy, setSortBy] = useState<SortColumn>("mention_count");
    const [sortDir, setSortDir] = useState<SortDirection>("desc");
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        let cancelled = false;
        async function load() {
            setLoading(true);
            setError(null);
            try {
                const query = category === "all" ? "" : `?category=${encodeURIComponent(category)}`;
                const res = await vektrynApi.listTrends(query);
                if (!cancelled) setTrends(res.results);
            } catch (err) {
                if (!cancelled) {
                    setError(err instanceof Error ? err.message : "Failed to load stack trends");
                }
            } finally {
                if (!cancelled) setLoading(false);
            }
        }
        void load();
        return () => {
            cancelled = true;
        };
    }, [category]);

    function toggleSort(column: SortColumn) {
        if (sortBy === column) {
            setSortDir((prev) => (prev === "desc" ? "asc" : "desc"));
        } else {
            setSortBy(column);
            setSortDir("desc");
        }
    }

    function renderSortIcon(column: SortColumn) {
        if (sortBy !== column) {
            return <ArrowUpDown className="h-3.5 w-3.5 text-zinc-600" />;
        }
        return sortDir === "desc" ? (
            <ArrowDown className="h-3.5 w-3.5 text-violet-400" />
        ) : (
            <ArrowUp className="h-3.5 w-3.5 text-violet-400" />
        );
    }

    const maxMentions = trends.reduce((max, item) => Math.max(max, item.mention_count), 1);
    const totalMentions = trends.reduce((sum, item) => sum + item.mention_count, 0);
    const topDemandRow = trends.reduce<StackTrendDaily | null>(
        (best, item) => (!best || item.mention_count > best.mention_count ? item : best),
        null,
    );
    const topDemandLabel = loading ? "—" : (topDemandRow?.tag ?? "—");
    const salarySamples = trends
        .map((row) => parseNumericSalary(row.median_annual_usd))
        .filter((val) => val > 0);
    const avgMedianSalary =
        salarySamples.length > 0
            ? formatUsdAnnual(
                String(
                    salarySamples.reduce((sum, val) => sum + val, 0) / salarySamples.length,
                ),
            )
            : "—";

    const sortedTrends = [...trends].sort((a, b) => {
        const direction = sortDir === "asc" ? 1 : -1;
        if (sortBy === "bucket_date") {
            return a.bucket_date.localeCompare(b.bucket_date) * direction;
        }
        if (sortBy === "median_annual_usd") {
            return (
                (parseNumericSalary(a.median_annual_usd) -
                    parseNumericSalary(b.median_annual_usd)) *
                direction
            );
        }
        return (a[sortBy] - b[sortBy]) * direction;
    });

    function renderContent() {
        if (loading) {
            return <TrendsSkeleton />;
        }
        if (trends.length === 0) {
            return (
                <div className="flex flex-col items-center justify-center gap-3 rounded-2xl border border-zinc-800/90 bg-zinc-900/40 px-6 py-20 text-center ring-1 ring-inset ring-white/[0.03]">
                    <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-zinc-900 ring-1 ring-zinc-800">
                        <BarChart3 className="h-5 w-5 text-zinc-500" />
                    </div>
                    <p className="text-base font-medium text-zinc-200">No rollup data recorded yet</p>
                    <p className="text-sm text-zinc-400">
                        Run <code className="rounded bg-zinc-900 px-2 py-0.5 font-mono text-xs text-zinc-200 ring-1 ring-zinc-800">make worker/rollup</code> to aggregate daily stack demand trends.
                    </p>
                </div>
            );
        }

        return (
            <div className="overflow-x-auto rounded-2xl border border-zinc-800/90 bg-zinc-900/50 ring-1 ring-inset ring-white/[0.03]">
                <table className="w-full min-w-[820px] border-collapse text-left text-sm">
                    <thead>
                        <tr className="border-b border-zinc-800 bg-zinc-900/95 text-xs uppercase tracking-wider text-zinc-400">
                            <th className="w-16 px-6 py-4">Rank</th>
                            <th className="px-6 py-4">Tag</th>
                            <th className="px-6 py-4">Category</th>
                            <th className="px-6 py-4">
                                <Tooltip content="Sort by daily rollup bucket date">
                                    <button
                                        type="button"
                                        onClick={() => toggleSort("bucket_date")}
                                        className="inline-flex items-center gap-1.5 uppercase tracking-wider transition hover:text-zinc-200 focus-visible:rounded focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-500/70"
                                    >
                                        Date {renderSortIcon("bucket_date")}
                                    </button>
                                </Tooltip>
                            </th>
                            <th className="px-6 py-4">Demand Share</th>
                            <th className="px-6 py-4 text-right">
                                <Tooltip content="Sort by total job posting mentions">
                                    <button
                                        type="button"
                                        onClick={() => toggleSort("mention_count")}
                                        className="inline-flex items-center gap-1.5 uppercase tracking-wider transition hover:text-zinc-200 focus-visible:rounded focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-500/70"
                                    >
                                        Mentions {renderSortIcon("mention_count")}
                                    </button>
                                </Tooltip>
                            </th>
                            <th className="px-6 py-4 text-right">
                                <Tooltip content="Sort by distinct hiring companies">
                                    <button
                                        type="button"
                                        onClick={() => toggleSort("unique_companies_count")}
                                        className="inline-flex items-center gap-1.5 uppercase tracking-wider transition hover:text-zinc-200 focus-visible:rounded focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-500/70"
                                    >
                                        Companies {renderSortIcon("unique_companies_count")}
                                    </button>
                                </Tooltip>
                            </th>
                            <th className="px-6 py-4 text-right">
                                <Tooltip content="Sort by median annual USD salary">
                                    <button
                                        type="button"
                                        onClick={() => toggleSort("median_annual_usd")}
                                        className="inline-flex items-center gap-1.5 uppercase tracking-wider transition hover:text-zinc-200 focus-visible:rounded focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-500/70"
                                    >
                                        Median USD {renderSortIcon("median_annual_usd")}
                                    </button>
                                </Tooltip>
                            </th>
                        </tr>
                    </thead>
                    <tbody className="divide-y divide-zinc-800/75">
                        {sortedTrends.map((row, index) => {
                            const rank = index + 1;
                            const relativeShare = Math.round((row.mention_count / maxMentions) * 100);
                            const barWidth = Math.max(4, relativeShare);
                            const categoryLabel = formatCategoryLabel(row.category);
                            const salaryTooltip = row.median_annual_usd
                                ? `Median annual USD compensation across roles mentioning ${row.tag}`
                                : `No salary data reported for ${row.tag}`;

                            return (
                                <tr
                                    key={`${row.bucket_date}-${row.tag}`}
                                    className="transition hover:bg-zinc-900/80"
                                >
                                    <td className="px-6 py-4">
                                        <Tooltip content={`Rank #${rank} in current sort order`}>
                                            <span
                                                className={`inline-flex min-w-8 items-center justify-center rounded-md px-2 py-0.5 font-mono text-xs font-semibold tabular-nums ${rankBadgeStyle(
                                                    rank,
                                                )}`}
                                            >
                                                #{rank}
                                            </span>
                                        </Tooltip>
                                    </td>
                                    <td className="px-6 py-4 font-mono font-medium text-zinc-100">
                                        {row.tag}
                                    </td>
                                    <td className="px-6 py-4">
                                        <Tooltip content={`Technology category: ${categoryLabel}`}>
                                            <span
                                                className={`inline-flex rounded-md px-2.5 py-1 text-xs font-medium ${categoryBadgeStyle(
                                                    row.category,
                                                )}`}
                                            >
                                                {categoryLabel}
                                            </span>
                                        </Tooltip>
                                    </td>
                                    <td className="px-6 py-4 font-mono text-xs tabular-nums text-zinc-400">
                                        {row.bucket_date}
                                    </td>
                                    <td className="px-6 py-4">
                                        <Tooltip
                                            content={`${relativeShare}% of leading tag volume (${row.mention_count} of ${maxMentions} mentions)`}
                                        >
                                            <div className="flex items-center gap-3">
                                                <div className="h-2.5 w-40 overflow-hidden rounded-full bg-zinc-800/90">
                                                    <div
                                                        className="h-full rounded-full bg-gradient-to-r from-violet-600 to-fuchsia-400"
                                                        style={{ width: `${barWidth}%` }}
                                                    />
                                                </div>
                                                <span className="w-10 font-mono text-xs tabular-nums text-zinc-400">
                                                    {relativeShare}%
                                                </span>
                                            </div>
                                        </Tooltip>
                                    </td>
                                    <td className="px-6 py-4 text-right font-mono font-medium tabular-nums text-zinc-200">
                                        {row.mention_count}
                                    </td>
                                    <td className="px-6 py-4 text-right font-mono tabular-nums text-zinc-400">
                                        {row.unique_companies_count}
                                    </td>
                                    <td className="px-6 py-4 text-right font-mono font-medium tabular-nums text-emerald-300">
                                        <Tooltip content={salaryTooltip}>
                                            <span>{formatUsdAnnual(row.median_annual_usd)}</span>
                                        </Tooltip>
                                    </td>
                                </tr>
                            );
                        })}
                    </tbody>
                </table>
            </div>
        );
    }

    return (
        <div className="space-y-8">
            <header className="space-y-6">
                <div className="flex flex-col gap-1">
                    <h1 className="text-2xl font-semibold tracking-tight text-zinc-100">
                        Stack Trends
                    </h1>
                    <p className="text-sm text-zinc-400">
                        Daily market demand, company adoption, and median compensation across technologies.
                    </p>
                </div>

                <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
                    <Tooltip
                        content="Distinct technology trend rows in the current category filter"
                        className="block"
                    >
                        <div className="rounded-2xl border border-zinc-800/90 bg-zinc-900/45 px-5 py-4 ring-1 ring-inset ring-white/[0.03]">
                            <p className="text-xs font-medium uppercase tracking-wider text-zinc-400">
                                Tracked Tags
                            </p>
                            <p className="mt-2 font-mono text-2xl font-semibold tabular-nums text-zinc-100">
                                {loading ? "—" : trends.length}
                            </p>
                        </div>
                    </Tooltip>

                    <Tooltip
                        content="Most frequently mentioned technology in the active category"
                        className="block"
                    >
                        <div className="rounded-2xl border border-violet-500/20 bg-violet-950/15 px-5 py-4 ring-1 ring-inset ring-white/[0.03]">
                            <p className="text-xs font-medium uppercase tracking-wider text-violet-300/80">
                                Top Demand
                            </p>
                            <p className="mt-2 truncate font-mono text-2xl font-semibold text-violet-300">
                                {topDemandLabel}
                            </p>
                        </div>
                    </Tooltip>

                    <Tooltip
                        content="Sum of job posting mentions across displayed technologies"
                        className="block"
                    >
                        <div className="rounded-2xl border border-zinc-800/90 bg-zinc-900/45 px-5 py-4 ring-1 ring-inset ring-white/[0.03]">
                            <p className="text-xs font-medium uppercase tracking-wider text-zinc-400">
                                Total Mentions
                            </p>
                            <p className="mt-2 font-mono text-2xl font-semibold tabular-nums text-sky-300">
                                {loading ? "—" : totalMentions}
                            </p>
                        </div>
                    </Tooltip>

                    <Tooltip
                        content="Average of reported median annual USD salaries in this view"
                        className="block"
                    >
                        <div className="rounded-2xl border border-emerald-500/20 bg-emerald-950/15 px-5 py-4 ring-1 ring-inset ring-white/[0.03]">
                            <p className="text-xs font-medium uppercase tracking-wider text-emerald-300/80">
                                Avg Median Comp
                            </p>
                            <p className="mt-2 font-mono text-2xl font-semibold tabular-nums text-emerald-300">
                                {loading ? "—" : avgMedianSalary}
                            </p>
                        </div>
                    </Tooltip>
                </div>
            </header>

            <div className="flex flex-wrap items-center gap-2.5">
                {CATEGORIES.map((item) => {
                    const active = category === item.id;
                    const categoryTooltip =
                        item.id === "all"
                            ? "Show demand trends across all technology categories"
                            : `Filter demand trends to ${item.label.toLowerCase()}`;
                    return (
                        <Tooltip key={item.id} content={categoryTooltip}>
                            <button
                                type="button"
                                onClick={() => setCategory(item.id)}
                                className={`rounded-xl px-4 py-2 text-sm font-medium transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-500/70 ${active
                                        ? "bg-violet-600 text-white shadow-sm shadow-violet-600/25"
                                        : "border border-zinc-800 bg-zinc-900/70 text-zinc-400 hover:border-zinc-700 hover:text-zinc-200"
                                    }`}
                            >
                                {item.label}
                            </button>
                        </Tooltip>
                    );
                })}
            </div>

            {error && (
                <div className="rounded-2xl border border-red-500/30 bg-red-950/20 px-5 py-4 text-sm text-red-300">
                    {error}
                </div>
            )}

            {renderContent()}
        </div>
    );
}
