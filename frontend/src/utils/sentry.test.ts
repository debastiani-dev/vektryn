import * as Sentry from "@sentry/react";
import type { ErrorEvent } from "@sentry/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../api/client";
import {
    initFrontendSentry,
    scrubFrontendSentryEvent,
    scrubSensitiveUrl,
    syncSentryUser,
} from "./sentry";

vi.mock("@sentry/react", () => ({
    init: vi.fn(),
    setUser: vi.fn(),
}));

describe("frontend Sentry telemetry helpers", () => {
    beforeEach(() => {
        vi.mocked(Sentry.init).mockClear();
        vi.mocked(Sentry.setUser).mockClear();
    });

    it("is a zero-op when VITE_SENTRY_DSN is empty", () => {
        expect(initFrontendSentry({ VITE_SENTRY_DSN: "   ", MODE: "development" })).toBe(false);
        expect(Sentry.init).not.toHaveBeenCalled();
    });

    it("initializes Sentry with Free-plan defaults and release metadata", () => {
        const enabled = initFrontendSentry({
            VITE_SENTRY_DSN: "https://public@example.ingest.sentry.io/123",
            VITE_SENTRY_ENVIRONMENT: "production",
            VITE_SENTRY_RELEASE: "abc1234",
            MODE: "production",
        });

        expect(enabled).toBe(true);
        expect(Sentry.init).toHaveBeenCalledOnce();
        const config = vi.mocked(Sentry.init).mock.calls[0]?.[0];
        expect(config?.dsn).toBe("https://public@example.ingest.sentry.io/123");
        expect(config?.environment).toBe("production");
        expect(config?.release).toBe("abc1234");
        expect(config?.dataCollection).toEqual({
            userInfo: false,
            cookies: false,
            httpBodies: [],
        });
        expect(config?.tracesSampleRate).toBe(0);
        expect(config?.replaysSessionSampleRate).toBe(0);
        expect(config?.replaysOnErrorSampleRate).toBe(0);
        expect(config?.beforeSend).toBe(scrubFrontendSentryEvent);
    });

    it("drops expected 4xx ApiError and AbortError events", () => {
        for (const status of [400, 401, 403, 404, 429]) {
            const err = new ApiError(status, "client error", "client error", null);
            const result = scrubFrontendSentryEvent({} as ErrorEvent, {
                originalException: err,
            });
            expect(result).toBeNull();
        }

        const abortError = new Error("The operation was aborted");
        abortError.name = "AbortError";
        expect(
            scrubFrontendSentryEvent({} as ErrorEvent, {
                originalException: abortError,
            }),
        ).toBeNull();

        expect(
            scrubFrontendSentryEvent({
                exception: { values: [{ type: "ApiError", value: "API 403: Forbidden" }] },
            } as ErrorEvent),
        ).toBeNull();
    });

    it("keeps 5xx ApiError events and scrubs tokens, headers, and user PII", () => {
        const serverErr = new ApiError(502, "Bad Gateway", null, null);
        const event = {
            request: {
                url: "https://vektryn.debastiani.dev/stream/alerts?token=hmac-secret&tab=radar",
                query_string: "token=hmac-secret&tab=radar",
                headers: {
                    Cookie: "sessionid=abc",
                    Authorization: "Bearer tok",
                    "X-CSRFToken": "csrf",
                    Accept: "application/json",
                },
                cookies: { sessionid: "abc" },
            },
            user: {
                id: "7",
                username: "rafa",
                email: "rafa@example.com",
                ip_address: "1.2.3.4",
            },
            breadcrumbs: [
                {
                    data: {
                        url: "https://vektryn.debastiani.dev/stream/alerts?token=crumb-secret&keep=yes",
                    },
                },
            ],
        } as unknown as ErrorEvent;

        const cleaned = scrubFrontendSentryEvent(event, { originalException: serverErr });
        expect(cleaned).not.toBeNull();
        expect(cleaned?.request?.url).not.toContain("hmac-secret");
        expect(cleaned?.request?.url).toContain("tab=radar");
        expect(cleaned?.request?.query_string).not.toContain("hmac-secret");
        expect(cleaned?.request?.headers?.Cookie).toBe("[Filtered]");
        expect(cleaned?.request?.headers?.Authorization).toBe("[Filtered]");
        expect(cleaned?.request?.headers?.["X-CSRFToken"]).toBe("[Filtered]");
        expect(cleaned?.request?.headers?.Accept).toBe("application/json");
        expect(cleaned?.request?.cookies).toBeUndefined();
        expect(cleaned?.user).toEqual({ id: "7", username: "rafa" });
        expect(cleaned?.breadcrumbs?.[0]?.data?.url).not.toContain("crumb-secret");
        expect(cleaned?.breadcrumbs?.[0]?.data?.url).toContain("keep=yes");
    });

    it("scrubSensitiveUrl preserves hash fragments while redacting tokens", () => {
        expect(scrubSensitiveUrl("/stream/alerts?token=abc&foo=bar#top")).toBe(
            "/stream/alerts?token=%5BFiltered%5D&foo=bar#top",
        );
    });

    it("syncSentryUser sets only id and username and clears on logout", () => {
        syncSentryUser({ id: "42", username: "rafa" });
        expect(Sentry.setUser).toHaveBeenCalledWith({ id: "42", username: "rafa" });

        syncSentryUser(null);
        expect(Sentry.setUser).toHaveBeenCalledWith(null);
    });
});
