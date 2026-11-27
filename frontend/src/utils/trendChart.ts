import type { StackTrendDaily } from "../types/models";

export interface TrendChartDimensions {
    width: number;
    height: number;
    padLeft: number;
    padRight: number;
    padTop: number;
    padBottom: number;
}

export interface TrendChartPoint {
    date: string;
    count: number;
    x: number;
    y: number;
    baseY: number;
    tieCount: number;
}

export interface TrendChartSeries {
    tag: string;
    colorIndex: number;
    totalMentions: number;
    points: TrendChartPoint[];
}

export interface TrendChartModel {
    dates: string[];
    topTags: string[];
    maxValue: number;
    series: TrendChartSeries[];
    lookup: Map<string, StackTrendDaily>;
}

export const DEFAULT_TREND_CHART_DIMS: TrendChartDimensions = {
    width: 920,
    height: 240,
    padLeft: 44,
    padRight: 24,
    padTop: 18,
    padBottom: 34,
};

const TIE_OFFSET_PX = 2.6;

function clamp(value: number, min: number, max: number): number {
    return Math.min(max, Math.max(min, value));
}

export function buildTrendChartModel(
    trends: StackTrendDaily[],
    options?: {
        dates?: string[];
        tags?: string[];
        dimensions?: TrendChartDimensions;
    },
): TrendChartModel {
    const dims = options?.dimensions ?? DEFAULT_TREND_CHART_DIMS;
    const totalsByTag = new Map<string, number>();
    const datesSet = new Set<string>(options?.dates ?? []);
    const lookup = new Map<string, StackTrendDaily>();

    for (const row of trends) {
        datesSet.add(row.bucket_date);
        totalsByTag.set(row.tag, (totalsByTag.get(row.tag) ?? 0) + row.mention_count);
        lookup.set(`${row.tag}::${row.bucket_date}`, row);
    }

    const dates = [...datesSet].sort((a, b) => a.localeCompare(b));
    const topTags =
        options?.tags && options.tags.length > 0
            ? options.tags.slice(0, 5)
            : [...totalsByTag.entries()]
                  .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
                  .slice(0, 5)
                  .map(([tag]) => tag);

    const maxValue = Math.max(
        1,
        ...topTags.flatMap((tag) =>
            dates.map((date) => lookup.get(`${tag}::${date}`)?.mention_count ?? 0),
        ),
    );

    const innerWidth = dims.width - dims.padLeft - dims.padRight;
    const innerHeight = dims.height - dims.padTop - dims.padBottom;
    const xForIndex = (index: number) =>
        dims.padLeft + (index / Math.max(1, dates.length - 1)) * innerWidth;
    const yForValue = (value: number) =>
        dims.padTop + innerHeight - (value / maxValue) * innerHeight;

    // Group series indices that share the exact same (dateIndex, count) so tied lines spread cleanly.
    const tieGroups = new Map<string, number[]>();
    for (let seriesIdx = 0; seriesIdx < topTags.length; seriesIdx++) {
        const tag = topTags[seriesIdx];
        for (let dateIdx = 0; dateIdx < dates.length; dateIdx++) {
            const count = lookup.get(`${tag}::${dates[dateIdx]}`)?.mention_count ?? 0;
            const key = `${dateIdx}::${count}`;
            const group = tieGroups.get(key);
            if (group) {
                group.push(seriesIdx);
            } else {
                tieGroups.set(key, [seriesIdx]);
            }
        }
    }

    const minY = dims.padTop;
    const maxY = dims.padTop + innerHeight;

    const series: TrendChartSeries[] = topTags.map((tag, seriesIdx) => {
        const points: TrendChartPoint[] = dates.map((date, dateIdx) => {
            const count = lookup.get(`${tag}::${date}`)?.mention_count ?? 0;
            const baseY = yForValue(count);
            const group = tieGroups.get(`${dateIdx}::${count}`) ?? [seriesIdx];
            const posInGroup = group.indexOf(seriesIdx);
            const rawOffset =
                group.length > 1 ? (posInGroup - (group.length - 1) / 2) * TIE_OFFSET_PX : 0;
            const y = clamp(baseY + rawOffset, minY, maxY);

            return {
                date,
                count,
                x: xForIndex(dateIdx),
                y,
                baseY,
                tieCount: group.length,
            };
        });

        return {
            tag,
            colorIndex: seriesIdx,
            totalMentions: totalsByTag.get(tag) ?? 0,
            points,
        };
    });

    return { dates, topTags, maxValue, series, lookup };
}
