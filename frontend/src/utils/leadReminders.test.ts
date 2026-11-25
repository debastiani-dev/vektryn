import { describe, expect, it } from "vitest";
import {
    formatFollowupDate,
    fromDatetimeLocalValue,
    isLeadFollowupOverdue,
    toDatetimeLocalValue,
} from "./leadReminders";

describe("leadReminders helpers", () => {
    const nowMs = Date.parse("2026-11-25T12:00:00Z");

    it("flags overdue reminders only on active leads", () => {
        expect(
            isLeadFollowupOverdue(
                { status: "applied", next_action_at: "2026-11-24T12:00:00Z" },
                nowMs,
            ),
        ).toBe(true);
        expect(
            isLeadFollowupOverdue(
                { status: "interviewing", next_action_at: "2026-11-26T12:00:00Z" },
                nowMs,
            ),
        ).toBe(false);
        expect(
            isLeadFollowupOverdue(
                { status: "rejected", next_action_at: "2026-11-20T12:00:00Z" },
                nowMs,
            ),
        ).toBe(false);
        expect(
            isLeadFollowupOverdue(
                { status: "withdrawn", next_action_at: "2026-11-20T12:00:00Z" },
                nowMs,
            ),
        ).toBe(false);
        expect(isLeadFollowupOverdue({ status: "saved", next_action_at: null }, nowMs)).toBe(
            false,
        );
    });

    it("formats dates and round-trips datetime-local values cleanly", () => {
        expect(formatFollowupDate(null)).toBeNull();
        expect(formatFollowupDate("2026-11-28T15:00:00Z")).toContain("Nov");

        const local = toDatetimeLocalValue("2026-11-28T15:30:00Z");
        expect(local).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/);
        const backToIso = fromDatetimeLocalValue(local);
        expect(backToIso).toBe("2026-11-28T15:30:00.000Z");
        expect(fromDatetimeLocalValue("   ")).toBeNull();
    });
});
