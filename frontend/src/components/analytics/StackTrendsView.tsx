import { useEffect, useState } from "react";
import { vektrynApi } from "../../api/client";
import type { StackTrendDaily, TechCategory } from "../../types/models";

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

function formatUsd(raw: string | null): string {
    if (!raw) return "—";
    const value = Number(raw);
    if (Number.isNaN(value)) return "—";
    return `$${Math.round(value / 1000)}k/yr`;
}

export function StackTrendsView() {
    const [trends, setTrends] = useState<StackTrendDaily[]>([]);
    const [category, setCategory] = useState<TechCategory | "all">("all");
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

    const maxMentions = trends.reduce((max, item) => Math.max(max, item.mention_count), 1);

    function renderContent() {
        if (loading) {
            return <div className="py-16 text-center text-sm text-zinc-500">Loading stack demand trends...</div>;
        }
        if (trends.length === 0) {
            return (
                <div className="rounded-xl border border-zinc-800 bg-zinc-900/40 py-14 text-center text-sm text-zinc-400">
                    No rollup data recorded yet. Run <code className="font-mono text-zinc-200">make worker/rollup</code> to aggregate daily trends.
                </div>
            );
        }

        return (
            <div className="overflow-hidden rounded-xl border border-zinc-800 bg-zinc-900/50">
                <table className="w-full border-collapse text-left text-sm">
                    <thead>
                        <tr className="border-b border-zinc-800 bg-zinc-900 text-xs uppercase tracking-wider text-zinc-400">
                            <th className="px-4 py-3">Tag</th>
                            <th className="px-4 py-3">Category</th>
                            <th className="px-4 py-3">Date</th>
                            <th className="px-4 py-3">Demand Share</th>
                            <th className="px-4 py-3 text-right">Mentions</th>
                            <th className="px-4 py-3 text-right">Companies</th>
                            <th className="px-4 py-3 text-right">Median USD</th>
                        </tr>
                    </thead>
                    <tbody className="divide-y divide-zinc-800/80">
                        {trends.map((row) => {
                            const barWidth = Math.max(4, Math.round((row.mention_count / maxMentions) * 100));

                            return (
                                <tr key={`${row.bucket_date}-${row.tag}`} className="hover:bg-zinc-900/80">
                                    <td className="px-4 py-3 font-mono font-medium text-zinc-100">{row.tag}</td>
                                    <td className="px-4 py-3 text-xs uppercase text-zinc-400">{row.category}</td>
                                    <td className="px-4 py-3 font-mono text-xs text-zinc-400">{row.bucket_date}</td>
                                    <td className="px-4 py-3">
                                        <div className="h-2 w-36 overflow-hidden rounded-full bg-zinc-800">
                                            <div
                                                className="h-full rounded-full bg-violet-500"
                                                style={{ width: `${barWidth}%` }}
                                            />
                                        </div>
                                    </td>
                                    <td className="px-4 py-3 text-right font-mono text-zinc-200">
                                        {row.mention_count}
                                    </td>
                                    <td className="px-4 py-3 text-right font-mono text-zinc-400">
                                        {row.unique_companies_count}
                                    </td>
                                    <td className="px-4 py-3 text-right font-mono text-emerald-300">
                                        {formatUsd(row.median_annual_usd)}
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
        <div className="space-y-5">
            <div className="flex flex-wrap items-center gap-1.5">
                {CATEGORIES.map((item) => {
                    const active = category === item.id;
                    return (
                        <button
                            key={item.id}
                            type="button"
                            onClick={() => setCategory(item.id)}
                            className={`rounded-lg px-3 py-1.5 text-xs font-medium transition ${active
                                    ? "bg-violet-600 text-white"
                                    : "border border-zinc-800 bg-zinc-900 text-zinc-400 hover:text-zinc-200"
                                }`}
                        >
                            {item.label}
                        </button>
                    );
                })}
            </div>

            {error && (
                <div className="rounded-xl border border-red-500/30 bg-red-950/20 p-4 text-sm text-red-300">
                    {error}
                </div>
            )}

            {renderContent()}
        </div>
    );
}