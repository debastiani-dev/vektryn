import { describe, expect, it } from "vitest";
import type { LiveMatchAlert, NotificationItem } from "../types/models";
import {
    alertToNotification,
    extractPayloadString,
    formatUnreadBadge,
    mergeLiveNotification,
} from "./notifications";

function makeAlert(overrides: Partial<LiveMatchAlert> = {}): LiveMatchAlert {
    return {
        event_id: "evt-1",
        notification_uuid: "notif-1",
        user_id: "42",
        job_posting_uuid: "job-1",
        resume_profile_uuid: "resume-1",
        match_score_uuid: "match-1",
        title: "Staff Python Engineer",
        company_name: "Acme Cloud",
        fit_score: 92,
        cosine_similarity: 0.87,
        matched_skills: ["python", "kafka"],
        missing_keywords: ["rust"],
        apply_url: "https://acme.test/jobs/1",
        ...overrides,
    };
}

describe("notifications utilities", () => {
    it("converts a LiveMatchAlert to a NotificationItem keyed by notification_uuid", () => {
        const item = alertToNotification(makeAlert());
        expect(item.uuid).toBe("notif-1");
        expect(item.kind).toBe("match_alert");
        expect(item.is_read).toBe(false);
        expect(item.title).toContain("92% Fit");
        expect(extractPayloadString(item, "match_score_uuid")).toBe("match-1");
        expect(extractPayloadString(item, "job_posting_uuid")).toBe("job-1");
    });

    it("deduplicates live SSE arrivals by notification uuid and by match_score_uuid fallback", () => {
        const restItem: NotificationItem = {
            uuid: "notif-1",
            kind: "match_alert",
            title: "92% Fit: Staff Python Engineer",
            body: "Acme Cloud matched your resume.",
            payload: { match_score_uuid: "match-1", job_posting_uuid: "job-1" },
            read_at: null,
            dismissed_at: null,
            is_read: false,
            created_at: "2026-11-25T10:00:00Z",
            modified_at: "2026-11-25T10:00:00Z",
        };

        // Exact uuid duplicate
        const dupByUuid = mergeLiveNotification([restItem], alertToNotification(makeAlert()));
        expect(dupByUuid.addedUnread).toBe(false);
        expect(dupByUuid.items).toHaveLength(1);

        // Legacy SSE event without notification_uuid still deduplicates via match_score_uuid
        const dupByMatch = mergeLiveNotification(
            [restItem],
            alertToNotification(makeAlert({ notification_uuid: null, event_id: "evt-legacy" })),
        );
        expect(dupByMatch.addedUnread).toBe(false);
        expect(dupByMatch.items).toHaveLength(1);

        // Distinct alert prepends and increments unread
        const fresh = mergeLiveNotification(
            [restItem],
            alertToNotification(
                makeAlert({
                    notification_uuid: "notif-2",
                    match_score_uuid: "match-2",
                    title: "Principal Backend Engineer",
                }),
            ),
        );
        expect(fresh.addedUnread).toBe(true);
        expect(fresh.items).toHaveLength(2);
        expect(fresh.items[0].uuid).toBe("notif-2");
    });

    it("caps unread badge display at 99+", () => {
        expect(formatUnreadBadge(0)).toBe("0");
        expect(formatUnreadBadge(7)).toBe("7");
        expect(formatUnreadBadge(99)).toBe("99");
        expect(formatUnreadBadge(142)).toBe("99+");
    });
});
