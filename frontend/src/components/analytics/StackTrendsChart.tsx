import { TrendingUp } from "lucide-react";
import { useState } from "react";
import type { StackTrendDaily } from "../../types/models";
import { formatUsdAnnual } from "../../utils/format";
import {
    DEFAULT_TREND_CHART_DIMS,
    type TrendChartSeries,
    buildTrendChartModel,
} from "../../utils/trendChart";
import { Tooltip } from "../ui/Tooltip";

interface StackTrendsChartProps {
    trends: StackTrendDaily[];
    dates?: string[];
    tags?: string[];
}

const SERIES_COLORS = [
    { stroke: "#a78bfa", dot: "bg-violet-400", text: "text-violet-300" },
    { stroke: "#38bdf8", dot: "bg-sky-400", text: "text-sky-300" },
    { stroke: "#34d399", dot: "bg-emerald-400", text: "text-emerald-300" },
    { stroke: "#fbbf24", dot: "bg-amber-400", text: "text-amber-300" },
    { stroke: "#f472b6", dot: "bg-pink-400", text: "text-pink-300" },
];

function getSeriesOpacity(tag: string, activeTag: string | null): number {
    if (!activeTag) return 0.92;
    return activeTag === tag ? 1 : 0.16;
}

function renderSingleDaySnapshot(
    singleDate: string,
    topTags: string[],
    maxValue: number,
    lookup: Map<string, StackTrendDaily>,
) {
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

export function StackTrendsChart({
    trends,
    dates: explicitDates,
    tags: explicitTags,
}: Readonly<StackTrendsChartProps>) {
    const [hoveredTag, setHoveredTag] = useState<string | null>(null);
    const [pinnedTag, setPinnedTag] = useState<string | null>(null);
    const [hoveredDateIdx, setHoveredDateIdx] = useState<number | null>(null);

    if (trends.length === 0) {
        return null;
    }

    const model = buildTrendChartModel(trends, {
        dates: explicitDates,
        tags: explicitTags,
        dimensions: DEFAULT_TREND_CHART_DIMS,
    });
    const { dates, topTags, maxValue, series, lookup } = model;

    if (dates.length === 0 || topTags.length === 0) {
        return null;
    }

    if (dates.length < 2) {
        return renderSingleDaySnapshot(dates[0], topTags, maxValue, lookup);
    }

    const { width: chartWidth, height: chartHeight, padLeft, padRight, padTop, padBottom } =
        DEFAULT_TREND_CHART_DIMS;
    const innerWidth = chartWidth - padLeft - padRight;
    const innerHeight = chartHeight - padTop - padBottom;
    const xForIndex = (index: number) =>
        padLeft + (index / Math.max(1, dates.length - 1)) * innerWidth;
    const yForValue = (value: number) =>
        padTop + innerHeight - (value / maxValue) * innerHeight;
    const gridTicks = [0, 0.25, 0.5, 0.75, 1];

    const validPinnedTag = pinnedTag && topTags.includes(pinnedTag) ? pinnedTag : null;
    const activeTag = hoveredTag ?? validPinnedTag;

    // Render focused series last so it always sits cleanly on top of tied/crossing lines.
    const orderedSeries: TrendChartSeries[] = activeTag
        ? [
              ...series.filter((item) => item.tag !== activeTag),
              ...series.filter((item) => item.tag === activeTag),
          ]
        : series;

    const readoutDateIdx =
        hoveredDateIdx !== null && hoveredDateIdx < dates.length
            ? hoveredDateIdx
            : dates.length - 1;
    const readoutDate = dates[readoutDateIdx];
    const readoutRows = series
        .map((item) => ({
            tag: item.tag,
            colorIndex: item.colorIndex,
            count: item.points[readoutDateIdx]?.count ?? 0,
        }))
        .sort((a, b) => b.count - a.count || a.tag.localeCompare(b.tag));

    const hitColumnWidth = innerWidth / Math.max(1, dates.length - 1);

    function togglePinnedTag(tag: string) {
        setPinnedTag((prev) => (prev === tag ? null : tag));
    }

    return (
        <section className="space-y-4 rounded-2xl border border-zinc-800/90 bg-zinc-900/45 p-6 ring-1 ring-inset ring-white/[0.03]">
            <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="flex items-center gap-2">
                    <TrendingUp className="h-4 w-4 text-violet-400" />
                    <h2 className="text-sm font-semibold text-zinc-100">
                        Daily Mention Velocity (Top {topTags.length} Stacks)
                    </h2>
                </div>

                <div className="flex flex-wrap items-center gap-1.5">
                    {series.map((item) => {
                        const palette = SERIES_COLORS[item.colorIndex % SERIES_COLORS.length];
                        const isPinned = validPinnedTag === item.tag;
                        const isDimmed = Boolean(activeTag) && activeTag !== item.tag;
                        return (
                            <button
                                key={item.tag}
                                type="button"
                                aria-pressed={isPinned}
                                onMouseEnter={() => setHoveredTag(item.tag)}
                                onMouseLeave={() => setHoveredTag(null)}
                                onFocus={() => setHoveredTag(item.tag)}
                                onBlur={() => setHoveredTag(null)}
                                onClick={() => togglePinnedTag(item.tag)}
                                className={`inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1 font-mono text-xs transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-500/70 ${
                                    isPinned
                                        ? "border-violet-500/50 bg-violet-500/15 text-zinc-100"
                                        : "border-zinc-800/90 bg-zinc-950/60 text-zinc-300 hover:border-zinc-700 hover:text-zinc-100"
                                } ${isDimmed ? "opacity-45" : "opacity-100"}`}
                            >
                                <span className={`h-2 w-2 rounded-full ${palette.dot}`} />
                                <span>{item.tag}</span>
                            </button>
                        );
                    })}
                </div>
            </div>

            <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 rounded-xl border border-zinc-800/75 bg-zinc-950/60 px-3.5 py-2 text-xs">
                <span className="font-mono font-medium text-zinc-400">{readoutDate}</span>
                {readoutRows.map((entry) => {
                    const palette = SERIES_COLORS[entry.colorIndex % SERIES_COLORS.length];
                    const dimmed = Boolean(activeTag) && activeTag !== entry.tag;
                    return (
                        <span
                            key={entry.tag}
                            className={`inline-flex items-center gap-1.5 font-mono tabular-nums transition ${
                                dimmed ? "opacity-35" : "opacity-100"
                            }`}
                        >
                            <span className={`h-1.5 w-1.5 rounded-full ${palette.dot}`} />
                            <span className="text-zinc-300">{entry.tag}</span>
                            <span className={`font-semibold ${palette.text}`}>{entry.count}</span>
                        </span>
                    );
                })}
            </div>

            <div className="overflow-x-auto">
                <svg
                    viewBox={`0 0 ${chartWidth} ${chartHeight}`}
                    className="h-60 w-full min-w-[600px]"
                    aria-label="Daily technology demand time-series chart"
                    onMouseLeave={() => setHoveredDateIdx(null)}
                >
                    <title>Daily technology demand time-series chart</title>
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

                    {hoveredDateIdx !== null && hoveredDateIdx < dates.length && (
                        <line
                            x1={xForIndex(hoveredDateIdx)}
                            x2={xForIndex(hoveredDateIdx)}
                            y1={padTop}
                            y2={padTop + innerHeight}
                            stroke="rgba(167,139,250,0.45)"
                            strokeDasharray="3 3"
                        />
                    )}

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

                    {orderedSeries.map((item) => {
                        const palette = SERIES_COLORS[item.colorIndex % SERIES_COLORS.length];
                        const isFocused = activeTag === item.tag;
                        const opacity = getSeriesOpacity(item.tag, activeTag);
                        const polyline = item.points.map((p) => `${p.x},${p.y}`).join(" ");

                        return (
                            <g key={item.tag} opacity={opacity}>
                                <polyline
                                    fill="none"
                                    stroke={palette.stroke}
                                    strokeWidth={isFocused ? "3" : "2.25"}
                                    strokeLinecap="round"
                                    strokeLinejoin="round"
                                    points={polyline}
                                />
                                {item.points.map((pt) => (
                                    <circle
                                        key={`${item.tag}-${pt.date}`}
                                        cx={pt.x}
                                        cy={pt.y}
                                        r={isFocused ? "4.5" : "3.5"}
                                        fill="#09090b"
                                        stroke={palette.stroke}
                                        strokeWidth="2"
                                    >
                                        <title>{`${item.tag} (${pt.date}): ${pt.count} mentions`}</title>
                                    </circle>
                                ))}
                            </g>
                        );
                    })}

                    {/* Invisible per-date hover columns for smooth multi-series inspection */}
                    {dates.map((date, idx) => {
                        const cx = xForIndex(idx);
                        const xStart = idx === 0 ? padLeft : cx - hitColumnWidth / 2;
                        const colWidth =
                            idx === 0 || idx === dates.length - 1
                                ? hitColumnWidth / 2
                                : hitColumnWidth;
                        return (
                            <rect
                                key={`hit-${date}`}
                                x={xStart}
                                y={padTop}
                                width={Math.max(12, colWidth)}
                                height={innerHeight}
                                fill="transparent"
                                onMouseEnter={() => setHoveredDateIdx(idx)}
                            />
                        );
                    })}
                </svg>
            </div>

            <div className="flex flex-wrap items-center justify-between gap-2 border-t border-zinc-800/70 pt-3 text-xs text-zinc-500">
                <Tooltip content="Date range represented in the top-stack velocity series">
                    <span className="font-mono tabular-nums">
                        Range: {dates[0]} → {dates[dates.length - 1]}
                    </span>
                </Tooltip>
                <span>Hover chart dates or click legend tags to isolate a series</span>
            </div>
        </section>
    );
}
