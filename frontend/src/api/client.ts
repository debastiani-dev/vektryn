import type {
    ApplicationLead,
    ContractType,
    CurrentUser,
    JobPostingDetail,
    LeadPriority,
    LeadStatus,
    MatchScoreListResponse,
    PaginatedResponse,
    RescoreResponse,
    ResumeProfile,
    SeniorityLevel,
    StackTrendDaily,
} from "../types/models";

function getCookie(name: string): string {
    if (typeof document === "undefined") return "";
    const match = document.cookie.match(new RegExp(`(^| )${name}=([^;]+)`));
    return match ? decodeURIComponent(match[2]) : "";
}

async function apiFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
    const headers = new Headers(init.headers);
    const isFormData = init.body instanceof FormData;
    if (!isFormData && !headers.has("Content-Type")) {
        headers.set("Content-Type", "application/json");
    }
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

export interface ResumeProfileInput {
    label: string;
    raw_text?: string;
    file?: File | null;
    target_seniority?: SeniorityLevel[];
    target_contract_types?: ContractType[];
    target_regions?: string[];
    min_alert_score?: number;
    is_active?: boolean;
}

function buildResumeBody(payload: Partial<ResumeProfileInput>): BodyInit {
    if (payload.file) {
        const form = new FormData();
        form.append("file", payload.file);
        if (payload.label !== undefined) form.append("label", payload.label);
        if (payload.raw_text !== undefined) form.append("raw_text", payload.raw_text);
        if (payload.min_alert_score !== undefined) {
            form.append("min_alert_score", String(payload.min_alert_score));
        }
        if (payload.is_active !== undefined) {
            form.append("is_active", String(payload.is_active));
        }
        for (const item of payload.target_seniority ?? []) {
            form.append("target_seniority", item);
        }
        for (const item of payload.target_contract_types ?? []) {
            form.append("target_contract_types", item);
        }
        for (const item of payload.target_regions ?? []) {
            form.append("target_regions", item);
        }
        return form;
    }

    const { file: _ignored, ...jsonPayload } = payload;
    return JSON.stringify(jsonPayload);
}

export async function fetchAllPagesWithCount<T>(
    fetchPage: (query: string) => Promise<PaginatedResponse<T>>,
    baseParams = "",
    maxPages = 10,
): Promise<{ items: T[]; totalCount: number }> {
    const items: T[] = [];
    let totalCount = 0;
    const params = new URLSearchParams(baseParams.replace(/^\?/, ""));

    for (let page = 1; page <= maxPages; page += 1) {
        params.set("page", String(page));
        const res = await fetchPage(`?${params.toString()}`);
        if (page === 1) {
            totalCount = res.count;
        }
        items.push(...res.results);
        if (!res.next) {
            break;
        }
    }
    return { items, totalCount };
}

export async function fetchAllPages<T>(
    fetchPage: (query: string) => Promise<PaginatedResponse<T>>,
    baseParams = "",
    maxPages = 10,
): Promise<T[]> {
    const { items } = await fetchAllPagesWithCount(fetchPage, baseParams, maxPages);
    return items;
}

export const vektrynApi = {
    ensureCsrf: () => apiFetch<{ detail: string }>("/api/v1/auth/csrf/"),

    login: (username: string, password: string) =>
        apiFetch<CurrentUser>("/api/v1/auth/login/", {
            method: "POST",
            body: JSON.stringify({ username, password }),
        }),

    logout: () =>
        apiFetch<void>("/api/v1/auth/logout/", {
            method: "POST",
        }),

    getCurrentUser: () => apiFetch<CurrentUser>("/api/v1/auth/me/"),

    getJob: (uuid: string) =>
        apiFetch<JobPostingDetail>(`/api/v1/jobs/${encodeURIComponent(uuid)}/`),

    listResumes: (params = "") =>
        apiFetch<PaginatedResponse<ResumeProfile>>(`/api/v1/resumes/${params}`),

    createResume: (payload: ResumeProfileInput) =>
        apiFetch<ResumeProfile>("/api/v1/resumes/", {
            method: "POST",
            body: buildResumeBody(payload),
        }),

    updateResume: (uuid: string, payload: Partial<ResumeProfileInput>) =>
        apiFetch<ResumeProfile>(`/api/v1/resumes/${encodeURIComponent(uuid)}/`, {
            method: "PATCH",
            body: buildResumeBody(payload),
        }),

    deleteResume: (uuid: string) =>
        apiFetch<void>(`/api/v1/resumes/${encodeURIComponent(uuid)}/`, {
            method: "DELETE",
        }),

    rescoreResume: (uuid: string, options: { max_jobs?: number; force?: boolean } = {}) =>
        apiFetch<RescoreResponse>(`/api/v1/resumes/${encodeURIComponent(uuid)}/rescore/`, {
            method: "POST",
            body: JSON.stringify(options),
        }),

    listMatches: (params = "") =>
        apiFetch<MatchScoreListResponse>(`/api/v1/matches/${params}`),

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
