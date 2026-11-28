import type { LiveMatchAlert, NotificationItem } from "../types/models";

export function getAlertDedupeKey(alert: LiveMatchAlert): string {
    return alert.notification_uuid || alert.event_id;
}

export function alertToNotification(alert: LiveMatchAlert): NotificationItem {
    const nowIso = new Date().toISOString();
    const simPct = Math.round(alert.cosine_similarity * 100);
    const matchedTarget = alert.resume_profile_label?.trim() || "your resume";
    return {
        uuid: getAlertDedupeKey(alert),
        kind: "match_alert",
        title: `${alert.fit_score}% Fit: ${alert.title}`,
        body: `${alert.company_name} matched ${matchedTarget} (${simPct}% vector similarity).`,
        payload: {
            job_posting_uuid: alert.job_posting_uuid,
            resume_profile_uuid: alert.resume_profile_uuid,
            resume_profile_label: alert.resume_profile_label,
            resume_language: alert.resume_language,
            match_score_uuid: alert.match_score_uuid,
            title: alert.title,
            company_name: alert.company_name,
            fit_score: alert.fit_score,
            cosine_similarity: alert.cosine_similarity,
            matched_skills: alert.matched_skills,
            missing_keywords: alert.missing_keywords,
            apply_url: alert.apply_url,
        },
        read_at: null,
        dismissed_at: null,
        is_read: false,
        created_at: nowIso,
        modified_at: nowIso,
    };
}

function isSameNotification(a: NotificationItem, b: NotificationItem): boolean {
    if (a.uuid === b.uuid) {
        return true;
    }
    if (a.kind === "match_alert" && b.kind === "match_alert") {
        const scoreA = a.payload?.match_score_uuid;
        const scoreB = b.payload?.match_score_uuid;
        if (typeof scoreA === "string" && scoreA.length > 0 && scoreA === scoreB) {
            return true;
        }
    }
    return false;
}

export function mergeLiveNotification(
    existing: ReadonlyArray<NotificationItem>,
    incoming: NotificationItem,
): { items: NotificationItem[]; addedUnread: boolean } {
    const alreadyPresent = existing.some((item) => isSameNotification(item, incoming));
    if (alreadyPresent) {
        return { items: [...existing], addedUnread: false };
    }
    return {
        items: [incoming, ...existing],
        addedUnread: !incoming.is_read,
    };
}

export function formatUnreadBadge(count: number): string {
    if (count > 99) return "99+";
    return String(Math.max(0, count));
}

export function extractPayloadString(
    item: NotificationItem,
    key:
        | "match_score_uuid"
        | "job_posting_uuid"
        | "resume_profile_uuid"
        | "resume_profile_label"
        | "resume_language"
        | "apply_url",
): string | null {
    const value = item.payload?.[key];
    return typeof value === "string" && value.trim().length > 0 ? value.trim() : null;
}
