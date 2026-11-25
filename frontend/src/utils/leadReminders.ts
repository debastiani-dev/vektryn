import type { ApplicationLead } from "../types/models";

const TERMINAL_STATUSES = new Set(["rejected", "withdrawn"]);

export function isLeadFollowupOverdue(
    lead: Pick<ApplicationLead, "status" | "next_action_at">,
    nowMs = Date.now(),
): boolean {
    if (!lead.next_action_at || TERMINAL_STATUSES.has(lead.status)) {
        return false;
    }
    const ts = Date.parse(lead.next_action_at);
    return !Number.isNaN(ts) && ts <= nowMs;
}

export function formatFollowupDate(iso: string | null): string | null {
    if (!iso) return null;
    const ts = Date.parse(iso);
    if (Number.isNaN(ts)) return null;
    return new Date(ts).toLocaleDateString("en-US", {
        month: "short",
        day: "numeric",
    });
}

export function formatFollowupExact(iso: string | null): string | null {
    if (!iso) return null;
    const ts = Date.parse(iso);
    if (Number.isNaN(ts)) return null;
    return new Date(ts).toLocaleString("en-US", {
        year: "numeric",
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
    });
}

export function toDatetimeLocalValue(iso: string | null): string {
    if (!iso) return "";
    const date = new Date(iso);
    if (Number.isNaN(date.getTime())) return "";
    const pad = (n: number) => String(n).padStart(2, "0");
    return (
        `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}` +
        `T${pad(date.getHours())}:${pad(date.getMinutes())}`
    );
}

export function fromDatetimeLocalValue(localValue: string): string | null {
    const trimmed = localValue.trim();
    if (!trimmed) return null;
    const parsed = new Date(trimmed);
    if (Number.isNaN(parsed.getTime())) return null;
    return parsed.toISOString();
}
