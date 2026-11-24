import { TrendingUp } from "lucide-react";
import type { StackTrendDaily } from "../../types/models";
import { formatUsdAnnual } from "../../utils/format";
import { Tooltip } from "../ui/Tooltip";

interface StackTrendsChartProps {
    trends: StackTrendDaily[];
}

const SERIES_COLORS = [
    { stroke: "#a78bfa", dot: "bg-violet-400", text: "text-violet-300" },
    { stroke: "#38bdf8", dot: "bg-sky-400", text: "text-sky-300" },
    { stroke: "#34d399", dot: "bg-emerald-400", text: "text-emerald-300" },
    { stroke: "#fbbf24", dot: "bg-amber-400", text: "text-amber-300" },
    { stroke: "#f472b6", dot: "bg-pink-400", text: "text-pink-300" },
];

export function StackTrendsChart({ trends }: Readonly<StackTrendsChartProps>) {
    if (trends.length === 0) {
        return null;
    }

    const totalsByTag = new Map<string, number>();
    const datesSet = new Set<string>();
    const lookup = new Map<string, StackTrendDaily>();

    for (const row of trends) {
        datesSet.add(row.bucket_date);
        totalsByTag.set(row.tag, (totalsByTag.get(row.tag) ?? 0) + row.mention_count);
        lookup.set(`${row.tag}::${row.bucket_date}`, row);
    }

    const dates = [...datesSet].sort((a, b) => a.localeCompare(b));
    const topTags = [...totalsByTag.entries()]
        .sort((a, b) => b[1] - a[1])
        .slice(0, 5)
        .map(([tag]) => tag);

    const maxValue = Math.max(
        1,
        ...topTags.flatMap((tag) =>
            dates.map((date) => lookup.get(`${tag}::${date}`)?.mention_count ?? 0),
        ),
    );

    if (dates.length < 2) {
        const singleDate = dates[0];
        return (
            <section className="space-y-5 rounded-2xl border border-zinc-800/90 bg-zinc-900/45 p-6 ring-1 ring-inset ring-white/[0.03]">
                <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="flex items-center gap-2">
                        <TrendingUp className="h-4 w-4 text-violet-400" />
                        <h2 className="text-sm font-semibold text-zinc-100">
                            Top Stack Demand Snapshot ({singleDate})
                        </h2>
                    </div>
                    <span className="text-xs text-zinc-500">
                        Multi-day time-series lines appear automatically once 2+ rollup dates exist
                    </span>
                </div>

                <div className="grid gap-3">
                    {topTags.map((tag, idx) => {
                        const row = lookup.get(`${tag}::${singleDate}`);
                        const count = row?.mention_count ?? 0;
                        const pct = Math.max(6, Math.round((count / maxValue) * 100));
                        const palette = SERIES_COLORS[idx % SERIES_COLORS.length];
                        const compLabel = formatUsdAnnual(row?.median_annual_usd ?? null);

                        return (
                            <div key={tag} className="flex items-center gap-4">
                                <span className="w-28 shrink-0 truncate font-mono text-xs font-medium text-zinc-200">
                                    {tag}
                                </span>
                                <div className="h-3 flex-1 overflow-hidden rounded-full bg-zinc-800/90">
                                    <div
                                        className="h-full rounded-full transition-all"
                                        style={{
                                            width: `${pct}%`,
                                            backgroundColor: palette.stroke,
                                        }}
                                    />
                                </div>
                                <span className="w-28 shrink-0 text-right font-mono text-xs tabular-nums text-zinc-400">
                                    {count} · {compLabel}
                                </span>
                            </div>
                        );
                    })}
                </div>
            </section>
        );
    }

    const chartWidth = 920;
    const chartHeight = 240;
    const padLeft = 44;
    const padRight = 24;
    const padTop = 18;
    const padBottom = 34;
    const innerWidth = chartWidth - padLeft - padRight;
    const innerHeight = chartHeight - padTop - padBottom;

    const xForIndex = (index: number) =>
        padLeft + (index / Math.max(1, dates.length - 1)) * innerWidth;
    const yForValue = (value: number) =>
        padTop + innerHeight - (value / maxValue) * innerHeight;

    const gridTicks = [0, 0.25, 0.5, 0.75, 1];

    return (
        <section className="space-y-5 rounded-2xl border border-zinc-800/90 bg-zinc-900/45 p-6 ring-1 ring-inset ring-white/[0.03]">
            <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="flex items-center gap-2">
                    <TrendingUp className="h-4 w-4 text-violet-400" />
                    <h2 className="text-sm font-semibold text-zinc-100">
                        Daily Mention Velocity (Top {topTags.length} Stacks)
                    </h2>
                </div>

                <div className="flex flex-wrap items-center gap-3">
                    {topTags.map((tag, idx) => {
                        const palette = SERIES_COLORS[idx % SERIES_COLORS.length];
                        return (
                            <span
                                key={tag}
                                className="inline-flex items-center gap-1.5 font-mono text-xs text-zinc-300"
                            >
                                <span className={`h-2 w-2 rounded-full ${palette.dot}`} />
                                {tag}
                            </span>
                        );
                    })}
                </div>
            </div>

            <div className="overflow-x-auto">
                <svg
                    viewBox={`0 0 ${chartWidth} ${chartHeight}`}
                    className="h-60 w-full min-w-[600px]"
                    role="img"
                    aria-label="Daily technology demand time-series chart"
                >
                    {gridTicks.map((ratio) => {
                        const val = Math.round(maxValue * ratio);
                        const y = yForValue(val);
                        return (
                            <g key={ratio}>
                                <line
                                    x1={padLeft}
                                    x2={chartWidth - padRight}
                                    y1={y}
                                    y2={y}
                                    stroke="rgba(63,63,70,0.5)"
                                    strokeDasharray="3 4"
                                />
                                <text
                                    x={padLeft - 8}
                                    y={y + 4}
                                    textAnchor="end"
                                    className="fill-zinc-500 font-mono text-[10px]"
                                >
                                    {val}
                                </text>
                            </g>
                        );
                    })}

                    {dates.map((date, idx) => {
                        const step = Math.max(1, Math.ceil(dates.length / 8));
                        if (idx % step !== 0 && idx !== dates.length - 1) return null;
                        return (
                            <text
                                key={date}
                                x={xForIndex(idx)}
                                y={chartHeight - 10}
                                textAnchor="middle"
                                className="fill-zinc-500 font-mono text-[10px]"
                            >
                                {date.slice(5)}
                            </text>
                        );
                    })}

                    {topTags.map((tag, seriesIdx) => {
                        const palette = SERIES_COLORS[seriesIdx % SERIES_COLORS.length];
                        const points = dates.map((date, idx) => {
                            const row = lookup.get(`${tag}::${date}`);
                            const count = row?.mention_count ?? 0;
                            return {
                                date,
                                count,
                                x: xForIndex(idx),
                                y: yForValue(count),
                            };
                        });
                        const polyline = points.map((p) => `${p.x},${p.y}`).join(" ");

                        return (
                            <g key={tag}>
                                <polyline
                                    fill="none"
                                    stroke={palette.stroke}
                                    strokeWidth="2.25"
                                    strokeLinecap="round"
                                    strokeLinejoin="round"
                                    points={polyline}
                                />
                                {points.map((pt) => (
                                    <circle
                                        key={`${tag}-${pt.date}`}
                                        cx={pt.x}
                                        cy={pt.y}
                                        r="3.5"
                                        fill="#09090b"
                                        stroke={palette.stroke}
                                        strokeWidth="2"
                                    >
                                        <title>{`${tag} (${pt.date}): ${pt.count} mentions`}</title>
                                    </circle>
                                ))}
                            </g>
                        );
                    })}
                </svg>
            </div>

            <div className="flex flex-wrap items-center gap-2 border-t border-zinc-800/70 pt-3 text-xs text-zinc-500">
                <Tooltip content="Date range represented in the current loaded trend page">
                    <span className="font-mono tabular-nums">
                        Range: {dates[0]} → {dates[dates.length - 1]}
                    </span>
                </Tooltip>
            </div>
        </section>
    );
}
