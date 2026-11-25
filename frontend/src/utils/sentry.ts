import * as Sentry from "@sentry/react";
import type { ErrorEvent, EventHint } from "@sentry/react";
import { ApiError } from "../api/client";
import type { CurrentUser } from "../types/models";

export interface FrontendSentryEnv {
    VITE_SENTRY_DSN?: string;
    VITE_SENTRY_ENVIRONMENT?: string;
    VITE_SENTRY_RELEASE?: string;
    MODE?: string;
}

const REDACTED = "[Filtered]";
const SENSITIVE_QUERY_KEYS = new Set([
    "token",
    "api_key",
    "key",
    "secret",
    "password",
    "access_token",
    "stream_token",
]);
const SENSITIVE_HEADERS = new Set([
    "cookie",
    "set-cookie",
    "authorization",
    "proxy-authorization",
    "x-csrftoken",
    "x-ingest-api-key",
]);
const API_4XX_PATTERN = /^API 4\d\d:/;

export const SENTRY_IGNORE_ERRORS: Array<string | RegExp> = [
    /ResizeObserver loop limit exceeded/i,
    /ResizeObserver loop completed with undelivered notifications/i,
    /Non-Error promise rejection captured/i,
    /AbortError/i,
    /The operation was aborted/i,
    /The user aborted a request/i,
    /chrome-extension:\/\//i,
    /moz-extension:\/\//i,
    /safari-extension:\/\//i,
];

export const SENTRY_DENY_URLS: RegExp[] = [
    /extensions\//i,
    /^chrome:\/\//i,
    /^chrome-extension:\/\//i,
    /^moz-extension:\/\//i,
    /^safari-extension:\/\//i,
    /^safari-web-extension:\/\//i,
];

function scrubQueryString(rawQuery: string): string {
    if (!rawQuery) {
        return rawQuery;
    }
    const params = new URLSearchParams(rawQuery);
    let mutated = false;
    for (const key of Array.from(params.keys())) {
        if (SENSITIVE_QUERY_KEYS.has(key.trim().toLowerCase())) {
            params.set(key, REDACTED);
            mutated = true;
        }
    }
    return mutated ? params.toString() : rawQuery;
}

export function scrubSensitiveUrl(rawUrl: string): string {
    if (!rawUrl?.includes("?")) {
        return rawUrl;
    }
    const [base, rest] = rawUrl.split("?", 2);
    const [query, hash] = rest.split("#", 2);
    const scrubbed = scrubQueryString(query);
    return hash !== undefined ? `${base}?${scrubbed}#${hash}` : `${base}?${scrubbed}`;
}

function isExpectedClientOrNoiseError(event: ErrorEvent, hint?: EventHint): boolean {
    const original = hint?.originalException;
    if (original instanceof ApiError && original.status >= 400 && original.status < 500) {
        return true;
    }
    if (original instanceof DOMException && original.name === "AbortError") {
        return true;
    }
    if (original instanceof Error && original.name === "AbortError") {
        return true;
    }

    const values = event.exception?.values ?? [];
    for (const entry of values) {
        const message = entry.value ?? "";
        if (entry.type === "AbortError" || API_4XX_PATTERN.test(message)) {
            return true;
        }
    }
    return false;
}

function scrubHeaders(headers: Record<string, string>): Record<string, string> {
    const cleaned: Record<string, string> = {};
    for (const [key, value] of Object.entries(headers)) {
        cleaned[key] = SENSITIVE_HEADERS.has(key.trim().toLowerCase()) ? REDACTED : value;
    }
    return cleaned;
}

function scrubRequest(request: NonNullable<ErrorEvent["request"]>): void {
    if (typeof request.url === "string") {
        request.url = scrubSensitiveUrl(request.url);
    }
    if (typeof request.query_string === "string") {
        request.query_string = scrubQueryString(request.query_string);
    }
    if (request.headers && typeof request.headers === "object") {
        request.headers = scrubHeaders(request.headers);
    }
    if ("cookies" in request) {
        delete request.cookies;
    }
}

function scrubBreadcrumbs(breadcrumbs: ErrorEvent["breadcrumbs"]): void {
    for (const crumb of breadcrumbs ?? []) {
        if (typeof crumb.data?.url === "string") {
            crumb.data.url = scrubSensitiveUrl(crumb.data.url);
        }
    }
}

export function scrubFrontendSentryEvent(event: ErrorEvent, hint?: EventHint): ErrorEvent | null {
    if (isExpectedClientOrNoiseError(event, hint)) {
        return null;
    }

    if (event.request) {
        scrubRequest(event.request);
    }

    if (event.user) {
        delete event.user.email;
        delete event.user.ip_address;
    }

    scrubBreadcrumbs(event.breadcrumbs);
    return event;
}

export function initFrontendSentry(env: FrontendSentryEnv = import.meta.env): boolean {
    const dsn = env.VITE_SENTRY_DSN?.trim() ?? "";
    if (!dsn) {
        return false;
    }

    const environment =
        env.VITE_SENTRY_ENVIRONMENT?.trim() || env.MODE?.trim() || "production";
    const release = env.VITE_SENTRY_RELEASE?.trim() || undefined;

    Sentry.init({
        dsn,
        environment,
        release,
        dataCollection: {
            userInfo: false,
            cookies: false,
            httpBodies: [],
        },
        tracesSampleRate: 0,
        replaysSessionSampleRate: 0,
        replaysOnErrorSampleRate: 0,
        ignoreErrors: SENTRY_IGNORE_ERRORS,
        denyUrls: SENTRY_DENY_URLS,
        beforeSend: scrubFrontendSentryEvent,
    });
    return true;
}

export function syncSentryUser(user: Pick<CurrentUser, "id" | "username"> | null): void {
    if (!user) {
        Sentry.setUser(null);
        return;
    }
    Sentry.setUser({
        id: String(user.id),
        username: user.username,
    });
}
