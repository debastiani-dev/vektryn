import type {
    ApplicationLead,
    CurrentUser,
    JobPostingDetail,
    LeadPriority,
    LeadStatus,
    MatchScore,
    PaginatedResponse,
    StackTrendDaily,
} from "../types/models";

function getCookie(name: string): string {
    const match = document.cookie.match(new RegExp(`(^| )${name}=([^;]+)`));
    return match ? decodeURIComponent(match[2]) : "";
}

async function apiFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
    const headers = new Headers(init.headers);
    headers.set("Content-Type", "application/json");
    const csrf = getCookie("csrftoken");
    if (csrf && init.method && init.method !== "GET") {
        headers.set("X-CSRFToken", csrf);
    }

    const res = await fetch(path, {
        ...init,
        credentials: "include",
        headers,
    });
    if (!res.ok) {
        throw new Error(`API ${res.status}: ${await res.text()}`);
    }
    if (res.status === 204) {
        return undefined as T;
    }
    return res.json() as Promise<T>;
}

export const vektrynApi = {
    getCurrentUser: () => apiFetch<CurrentUser>("/api/v1/auth/me/"),

    getJob: (uuid: string) =>
        apiFetch<JobPostingDetail>(`/api/v1/jobs/${encodeURIComponent(uuid)}/`),

    listMatches: (params = "") =>
        apiFetch<PaginatedResponse<MatchScore>>(`/api/v1/matches/${params}`),

    listLeads: (params = "") =>
        apiFetch<PaginatedResponse<ApplicationLead>>(`/api/v1/leads/${params}`),

    createLead: (payload: {
        job_posting: string;
        resume_profile?: string | null;
        status?: LeadStatus;
        priority?: LeadPriority;
        notes?: string;
    }) =>
        apiFetch<ApplicationLead>("/api/v1/leads/", {
            method: "POST",
            body: JSON.stringify(payload),
        }),

    updateLead: (
        uuid: string,
        payload: Partial<Pick<ApplicationLead, "status" | "priority" | "notes">>,
    ) =>
        apiFetch<ApplicationLead>(`/api/v1/leads/${uuid}/`, {
            method: "PATCH",
            body: JSON.stringify(payload),
        }),

    deleteLead: (uuid: string) =>
        apiFetch<void>(`/api/v1/leads/${uuid}/`, {
            method: "DELETE",
        }),

    listTrends: (params = "") =>
        apiFetch<PaginatedResponse<StackTrendDaily>>(`/api/v1/analytics/trends/${params}`),
};