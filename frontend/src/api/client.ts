import type {
    AccountDeactivateResponse,
    ApplicationLead,
    ChangePasswordInput,
    ChangePasswordResponse,
    ContractType,
    CurrentUser,
    DismissedJob,
    DlqDismissResponse,
    DlqInspectResponse,
    DlqReplayRequest,
    DlqReplayResponse,
    JobPostingDetail,
    JobPostingSummary,
    LeadPriority,
    LeadStatus,
    ManualJobImportInput,
    ManualJobImportResponse,
    MatchArtifactGenerateInput,
    MatchArtifactGenerateResponse,
    MatchArtifactListResponse,
    MatchScore,
    MatchScoreListResponse,
    MutedCompany,
    NotificationActionResponse,
    NotificationListResponse,
    PaginatedResponse,
    PersonalAnalyticsResponse,
    PersonalAnalyticsWindow,
    PipelineStatusResponse,
    ReadAllNotificationsResponse,
    RescoreResponse,
    ResumeProfile,
    SavedFilter,
    SavedFilterQueryParams,
    SeniorityLevel,
    StackTrendDaily,
    StackTrendSeriesResponse,
    StaffManagedUser,
    StaffUserCreateInput,
    StaffUserUpdateInput,
    TriggerCollectResponse,
    UserProfileDetail,
    UserProfileUpdateInput,
} from "../types/models";

export class ApiError extends Error {
    readonly status: number;
    readonly detail: string | null;
    readonly retryAfterSeconds: number | null;
    readonly fieldErrors: Record<string, string[]>;
    readonly code: string | null;
    readonly paymentRequired: boolean;

    constructor(
        status: number,
        bodyText: string,
        detail: string | null,
        retryAfterSeconds: number | null,
        fieldErrors: Record<string, string[]> = {},
        code: string | null = null,
        paymentRequired = false,
    ) {
        super(`API ${status}: ${bodyText}`);
        this.name = "ApiError";
        this.status = status;
        this.detail = detail;
        this.retryAfterSeconds = retryAfterSeconds;
        this.fieldErrors = fieldErrors;
        this.code = code;
        this.paymentRequired = paymentRequired;
    }
}

function parseFieldErrors(parsed: Record<string, unknown>): Record<string, string[]> {
    const fieldErrors: Record<string, string[]> = {};
    for (const [key, value] of Object.entries(parsed)) {
        if (
            key === "detail" ||
            key === "retry_after_seconds" ||
            key === "code" ||
            key === "payment_required"
        ) {
            continue;
        }
        if (Array.isArray(value)) {
            const messages = value
                .filter((item): item is string => typeof item === "string" && item.trim().length > 0)
                .map((item) => item.trim());
            if (messages.length > 0) {
                fieldErrors[key] = messages;
            }
        } else if (typeof value === "string" && value.trim()) {
            fieldErrors[key] = [value.trim()];
        }
    }
    return fieldErrors;
}

interface ApiErrorMetadata {
    detail: string | null;
    retryAfterSeconds: number | null;
    fieldErrors: Record<string, string[]>;
    code: string | null;
    paymentRequired: boolean;
}

function firstNonEmptyString(value: unknown): string | null {
    if (typeof value === "string") {
        const trimmed = value.trim();
        return trimmed || null;
    }
    if (Array.isArray(value)) {
        const match = value.find(
            (item): item is string => typeof item === "string" && item.trim().length > 0,
        );
        return match ? match.trim() : null;
    }
    return null;
}

function parseRetryAfterHeader(retryAfterHeader: string | null): number | null {
    if (!retryAfterHeader) {
        return null;
    }
    const parsed = Number.parseInt(retryAfterHeader, 10);
    return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
}

function parsePositiveSeconds(value: unknown): number | null {
    if (typeof value === "number" && Number.isFinite(value) && value > 0) {
        return Math.ceil(value);
    }
    return null;
}

function parseErrorBodyObject(
    obj: Record<string, unknown>,
    headerRetryAfter: number | null,
): ApiErrorMetadata {
    const fieldErrors = parseFieldErrors(obj);
    const detail = firstNonEmptyString(obj.detail) ?? fieldErrors.non_field_errors?.[0] ?? null;
    const code = firstNonEmptyString(obj.code);
    const paymentRequired = obj.payment_required === true;
    const retryAfterSeconds = parsePositiveSeconds(obj.retry_after_seconds) ?? headerRetryAfter;
    return { detail, retryAfterSeconds, fieldErrors, code, paymentRequired };
}

function parseApiErrorMetadata(
    bodyText: string,
    retryAfterHeader: string | null,
): ApiErrorMetadata {
    const headerRetryAfter = parseRetryAfterHeader(retryAfterHeader);
    const empty: ApiErrorMetadata = {
        detail: null,
        retryAfterSeconds: headerRetryAfter,
        fieldErrors: {},
        code: null,
        paymentRequired: false,
    };

    let parsed: unknown;
    try {
        parsed = JSON.parse(bodyText);
    } catch {
        return empty;
    }

    if (Array.isArray(parsed)) {
        return { ...empty, detail: firstNonEmptyString(parsed) };
    }
    if (parsed && typeof parsed === "object") {
        return parseErrorBodyObject(parsed as Record<string, unknown>, headerRetryAfter);
    }
    return empty;
}

export function formatApiError(err: unknown, fallback: string): string {
    if (err instanceof ApiError) {
        if (err.detail) {
            return err.detail;
        }
        const firstFieldMessages = Object.values(err.fieldErrors).flat();
        if (firstFieldMessages.length > 0) {
            return firstFieldMessages[0];
        }
        return fallback;
    }
    if (err instanceof Error && err.message.trim()) {
        return err.message.trim();
    }
    return fallback;
}

type SessionExpiredHandler = () => void;

let sessionExpiredHandler: SessionExpiredHandler | null = null;

const SESSION_EXPIRY_IGNORED_PREFIXES = [
    "/api/v1/auth/login/",
    "/api/v1/auth/csrf/",
    "/api/v1/auth/logout/",
    "/api/v1/auth/me/",
];

export function registerSessionExpiredHandler(handler: SessionExpiredHandler | null): () => void {
    sessionExpiredHandler = handler;
    return () => {
        if (sessionExpiredHandler === handler) {
            sessionExpiredHandler = null;
        }
    };
}

function isSessionExpiredResponse(path: string, status: number, detail: string | null): boolean {
    if (SESSION_EXPIRY_IGNORED_PREFIXES.some((prefix) => path.startsWith(prefix))) {
        return false;
    }
    if (status === 401) {
        return true;
    }
    if (status === 403 && detail) {
        return detail.toLowerCase().includes("authentication credentials were not provided");
    }
    return false;
}

function getCookie(name: string): string {
    if (typeof document === "undefined") return "";
    const match = new RegExp(`(^| )${name}=([^;]+)`).exec(document.cookie);
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
        const bodyText = await res.text();
        const meta = parseApiErrorMetadata(bodyText, res.headers.get("Retry-After"));
        if (isSessionExpiredResponse(path, res.status, meta.detail)) {
            sessionExpiredHandler?.();
        }
        throw new ApiError(
            res.status,
            bodyText,
            meta.detail,
            meta.retryAfterSeconds,
            meta.fieldErrors,
            meta.code,
            meta.paymentRequired,
        );
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

    getUserProfile: () => apiFetch<UserProfileDetail>("/api/v1/auth/profile/"),

    updateUserProfile: (payload: UserProfileUpdateInput) =>
        apiFetch<UserProfileDetail>("/api/v1/auth/profile/", {
            method: "PATCH",
            body: JSON.stringify(payload),
        }),

    changePassword: (payload: ChangePasswordInput) =>
        apiFetch<ChangePasswordResponse>("/api/v1/auth/change-password/", {
            method: "POST",
            body: JSON.stringify(payload),
        }),

    deactivateAccount: (currentPassword: string) =>
        apiFetch<AccountDeactivateResponse>("/api/v1/auth/deactivate/", {
            method: "POST",
            body: JSON.stringify({ current_password: currentPassword }),
        }),

    listUsers: (options?: {
        search?: string;
        is_active?: string;
        is_staff?: string;
        page?: number;
    }) => {
        const params = new URLSearchParams();
        if (options?.search?.trim()) {
            params.set("search", options.search.trim());
        }
        if (options?.is_active) {
            params.set("is_active", options.is_active);
        }
        if (options?.is_staff) {
            params.set("is_staff", options.is_staff);
        }
        if (options?.page !== undefined && options.page > 1) {
            params.set("page", String(options.page));
        }
        const qs = params.toString();
        const path = qs ? `/api/v1/users/?${qs}` : "/api/v1/users/";
        return apiFetch<PaginatedResponse<StaffManagedUser>>(path);
    },

    createUser: (payload: StaffUserCreateInput) =>
        apiFetch<StaffManagedUser>("/api/v1/users/", {
            method: "POST",
            body: JSON.stringify(payload),
        }),

    updateUser: (id: number, payload: StaffUserUpdateInput) =>
        apiFetch<StaffManagedUser>(`/api/v1/users/${id}/`, {
            method: "PATCH",
            body: JSON.stringify(payload),
        }),

    deactivateUser: (id: number) =>
        apiFetch<StaffManagedUser>(`/api/v1/users/${id}/`, {
            method: "DELETE",
        }),

    listJobs: (params = "") =>
        apiFetch<PaginatedResponse<JobPostingSummary>>(`/api/v1/jobs/${params}`),

    getJob: (uuid: string) =>
        apiFetch<JobPostingDetail>(`/api/v1/jobs/${encodeURIComponent(uuid)}/`),

    importJob: (payload: ManualJobImportInput) =>
        apiFetch<ManualJobImportResponse>("/api/v1/jobs/import/", {
            method: "POST",
            body: JSON.stringify(payload),
        }),

    listSavedFilters: (params = "") =>
        apiFetch<PaginatedResponse<SavedFilter>>(`/api/v1/jobs/filters/${params}`),

    createSavedFilter: (payload: { name: string; query_params: SavedFilterQueryParams }) =>
        apiFetch<SavedFilter>("/api/v1/jobs/filters/", {
            method: "POST",
            body: JSON.stringify(payload),
        }),

    updateSavedFilter: (
        uuid: string,
        payload: Partial<{ name: string; query_params: SavedFilterQueryParams }>,
    ) =>
        apiFetch<SavedFilter>(`/api/v1/jobs/filters/${encodeURIComponent(uuid)}/`, {
            method: "PATCH",
            body: JSON.stringify(payload),
        }),

    deleteSavedFilter: (uuid: string) =>
        apiFetch<void>(`/api/v1/jobs/filters/${encodeURIComponent(uuid)}/`, {
            method: "DELETE",
        }),

    listDismissedJobs: (page = 1) =>
        apiFetch<PaginatedResponse<DismissedJob>>(`/api/v1/jobs/dismissed/?page=${page}`),

    dismissJob: (jobPostingUuid: string) =>
        apiFetch<DismissedJob>("/api/v1/jobs/dismissed/", {
            method: "POST",
            body: JSON.stringify({ job_posting: jobPostingUuid }),
        }),

    restoreDismissedJob: (uuid: string) =>
        apiFetch<void>(`/api/v1/jobs/dismissed/${encodeURIComponent(uuid)}/`, {
            method: "DELETE",
        }),

    listMutedCompanies: (page = 1) =>
        apiFetch<PaginatedResponse<MutedCompany>>(`/api/v1/jobs/muted-companies/?page=${page}`),

    muteCompany: (companyName: string) =>
        apiFetch<MutedCompany>("/api/v1/jobs/muted-companies/", {
            method: "POST",
            body: JSON.stringify({ company_name: companyName }),
        }),

    unmuteCompany: (uuid: string) =>
        apiFetch<void>(`/api/v1/jobs/muted-companies/${encodeURIComponent(uuid)}/`, {
            method: "DELETE",
        }),

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

    getMatch: (uuid: string) =>
        apiFetch<MatchScore>(`/api/v1/matches/${encodeURIComponent(uuid)}/`),

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
        payload: Partial<
            Pick<ApplicationLead, "status" | "priority" | "notes" | "next_action_at">
        >,
    ) =>
        apiFetch<ApplicationLead>(`/api/v1/leads/${encodeURIComponent(uuid)}/`, {
            method: "PATCH",
            body: JSON.stringify(payload),
        }),

    deleteLead: (uuid: string) =>
        apiFetch<void>(`/api/v1/leads/${encodeURIComponent(uuid)}/`, {
            method: "DELETE",
        }),

    exportLeads: async (format: "csv" | "json"): Promise<{ blob: Blob; filename: string }> => {
        const response = await fetch(`/api/v1/leads/export/?format=${format}`, {
            credentials: "same-origin",
        });
        if (!response.ok) {
            const text = await response.text();
            throw new Error(`API ${response.status}: ${text || response.statusText}`);
        }
        const disposition = response.headers.get("Content-Disposition") ?? "";
        const match = /filename="([^"]+)"/.exec(disposition);
        const filename = match?.[1] ?? `vektryn-leads.${format}`;
        const blob = await response.blob();
        return { blob, filename };
    },

    listTrends: (params = "") =>
        apiFetch<PaginatedResponse<StackTrendDaily>>(`/api/v1/analytics/trends/${params}`),

    getTrendSeries: (params = "") =>
        apiFetch<StackTrendSeriesResponse>(`/api/v1/analytics/trends/series/${params}`),

    getSystemStatus: () => apiFetch<PipelineStatusResponse>("/api/v1/system/status/"),

    triggerCollectorSync: () =>
        apiFetch<TriggerCollectResponse>("/api/v1/system/collect/", {
            method: "POST",
        }),

    listNotifications: (params = "") =>
        apiFetch<NotificationListResponse>(`/api/v1/notifications/${params}`),

    markNotificationRead: (uuid: string) =>
        apiFetch<NotificationActionResponse>(
            `/api/v1/notifications/${encodeURIComponent(uuid)}/read/`,
            { method: "PATCH" },
        ),

    dismissNotification: (uuid: string) =>
        apiFetch<NotificationActionResponse>(
            `/api/v1/notifications/${encodeURIComponent(uuid)}/dismiss/`,
            { method: "PATCH" },
        ),

    markAllNotificationsRead: () =>
        apiFetch<ReadAllNotificationsResponse>("/api/v1/notifications/read-all/", {
            method: "POST",
        }),

    listMatchArtifacts: (matchUuid: string) =>
        apiFetch<MatchArtifactListResponse>(`/api/v1/matches/${matchUuid}/artifacts/`),

    generateMatchArtifact: (matchUuid: string, payload: MatchArtifactGenerateInput) =>
        apiFetch<MatchArtifactGenerateResponse>(`/api/v1/matches/${matchUuid}/artifacts/`, {
            method: "POST",
            body: JSON.stringify(payload),
        }),

    listDlqMessages: (options?: { limit?: number; original_topic?: string }) => {
        const params = new URLSearchParams();
        if (options?.limit !== undefined) {
            params.set("limit", String(options.limit));
        }
        if (options?.original_topic) {
            params.set("original_topic", options.original_topic);
        }
        const qs = params.toString();
        const path = qs ? `/api/v1/system/dlq/?${qs}` : "/api/v1/system/dlq/";
        return apiFetch<DlqInspectResponse>(path);
    },

    replayDlqMessages: (payload: DlqReplayRequest) =>
        apiFetch<DlqReplayResponse>("/api/v1/system/dlq/replay/", {
            method: "POST",
            body: JSON.stringify(payload),
        }),

    dismissDlqMessages: (eventIds: string[]) =>
        apiFetch<DlqDismissResponse>("/api/v1/system/dlq/dismiss/", {
            method: "POST",
            body: JSON.stringify({ event_ids: eventIds }),
        }),

    getPersonalAnalytics: (options?: {
        days?: PersonalAnalyticsWindow;
        resumeProfileUuid?: string;
    }) => {
        const params = new URLSearchParams();
        if (options?.days) {
            params.set("days", options.days);
        }
        if (options?.resumeProfileUuid) {
            params.set("resume_profile", options.resumeProfileUuid);
        }
        const qs = params.toString();
        const path = qs ? `/api/v1/analytics/personal/?${qs}` : "/api/v1/analytics/personal/";
        return apiFetch<PersonalAnalyticsResponse>(path);
    },
};
