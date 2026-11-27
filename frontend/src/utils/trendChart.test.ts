import { describe, expect, it } from "vitest";
import type { StackTrendDaily } from "../types/models";
import { buildTrendChartModel } from "./trendChart";

function makeRow(bucket_date: string, tag: string, mention_count: number): StackTrendDaily {
    return {
        bucket_date,
        tag,
        category: "language",
        mention_count,
        unique_companies_count: mention_count,
        median_annual_usd: null,
    };
}

describe("buildTrendChartModel", () => {
    it("separates tied series vertically so overlapping lines remain visible", () => {
        const rows = [
            makeRow("2026-11-24", "python", 5),
            makeRow("2026-11-24", "go", 5),
            makeRow("2026-11-24", "rust", 5),
            makeRow("2026-11-25", "python", 8),
            makeRow("2026-11-25", "go", 8),
            makeRow("2026-11-25", "rust", 8),
        ];

        const model = buildTrendChartModel(rows);
        expect(model.dates).toEqual(["2026-11-24", "2026-11-25"]);
        expect(model.series).toHaveLength(3);

        const day0Ys = model.series.map((s) => s.points[0].y);
        expect(new Set(day0Ys).size).toBe(3);
        expect(model.series.every((s) => s.points[0].tieCount === 3)).toBe(true);
    });

    it("keeps zero vertical offset when counts are distinct", () => {
        const rows = [
            makeRow("2026-11-24", "python", 20),
            makeRow("2026-11-24", "go", 10),
            makeRow("2026-11-25", "python", 25),
            makeRow("2026-11-25", "go", 12),
        ];

        const model = buildTrendChartModel(rows);
        for (const s of model.series) {
            for (const pt of s.points) {
                expect(pt.tieCount).toBe(1);
                expect(pt.y).toBe(pt.baseY);
            }
        }
    });

    it("preserves explicit date range and server-ranked tags including zero-mention days", () => {
        const rows = [
            makeRow("2026-11-24", "python", 10),
            makeRow("2026-11-26", "python", 14),
            makeRow("2026-11-26", "rust", 9),
        ];

        const model = buildTrendChartModel(rows, {
            dates: ["2026-11-24", "2026-11-25", "2026-11-26"],
            tags: ["python", "rust"],
        });

        expect(model.dates).toEqual(["2026-11-24", "2026-11-25", "2026-11-26"]);
        expect(model.topTags).toEqual(["python", "rust"]);
        expect(model.series[0].points.map((p) => p.count)).toEqual([10, 0, 14]);
        expect(model.series[1].points.map((p) => p.count)).toEqual([0, 0, 9]);
    });
});
