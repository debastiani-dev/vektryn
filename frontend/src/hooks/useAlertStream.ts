import { useEffect, useRef, useState } from "react";
import type { LiveMatchAlert } from "../types/models";
import { getAlertDedupeKey } from "../utils/notifications";

const INITIAL_RECONNECT_DELAY_MS = 1_500;
const MAX_RECONNECT_DELAY_MS = 30_000;
const TOKEN_REFRESH_BUFFER_MS = 120_000;

export function computeReconnectDelayMs(attempt: number): number {
    const safeAttempt = Math.max(0, Math.floor(attempt));
    return Math.min(MAX_RECONNECT_DELAY_MS, INITIAL_RECONNECT_DELAY_MS * 2 ** safeAttempt);
}

export function parseStreamTokenExpiryMs(token: string | null | undefined): number | null {
    if (!token) {
        return null;
    }
    const parts = token.trim().split(".");
    if (parts.length !== 3) {
        return null;
    }
    const expiresSeconds = Number.parseInt(parts[1] ?? "", 10);
    if (!Number.isFinite(expiresSeconds) || expiresSeconds <= 0) {
        return null;
    }
    return expiresSeconds * 1_000;
}

export function isStreamTokenExpiringSoon(
    token: string | null | undefined,
    nowMs = Date.now(),
    bufferMs = TOKEN_REFRESH_BUFFER_MS,
): boolean {
    const expiryMs = parseStreamTokenExpiryMs(token);
    return expiryMs !== null && expiryMs - nowMs <= bufferMs;
}

export function computeTokenRefreshDelayMs(
    token: string | null | undefined,
    nowMs = Date.now(),
    bufferMs = TOKEN_REFRESH_BUFFER_MS,
): number | null {
    const expiryMs = parseStreamTokenExpiryMs(token);
    if (expiryMs === null) {
        return null;
    }
    return Math.max(1_000, expiryMs - nowMs - bufferMs);
}

interface UseAlertStreamOptions {
    onAlert?: (alert: LiveMatchAlert) => void;
    onOpen?: () => void;
    refreshToken?: () => Promise<string | null>;
}

function closeEventSource(
    source: EventSource | null,
    handler: (event: MessageEvent) => void,
): void {
    if (!source) {
        return;
    }
    source.removeEventListener("match_alert", handler);
    source.close();
}

function clearTimer(timerId: number | null): null {
    if (timerId !== null) {
        window.clearTimeout(timerId);
    }
    return null;
}

function prependUniqueAlert(
    prev: LiveMatchAlert[],
    incoming: LiveMatchAlert,
): LiveMatchAlert[] {
    const dedupeKey = getAlertDedupeKey(incoming);
    if (prev.some((item) => getAlertDedupeKey(item) === dedupeKey)) {
        return prev;
    }
    return [incoming, ...prev].slice(0, 10);
}

export function useAlertStream(
    streamToken: string | null,
    options: UseAlertStreamOptions = {},
) {
    const [alerts, setAlerts] = useState<LiveMatchAlert[]>([]);
    const [streamConnected, setStreamConnected] = useState(false);
    const onAlertRef = useRef(options.onAlert);
    const onOpenRef = useRef(options.onOpen);
    const refreshTokenRef = useRef(options.refreshToken);

    useEffect(() => {
        onAlertRef.current = options.onAlert;
        onOpenRef.current = options.onOpen;
        refreshTokenRef.current = options.refreshToken;
    }, [options.onAlert, options.onOpen, options.refreshToken]);

    useEffect(() => {
        if (!streamToken) {
            return;
        }

        let activeToken = streamToken;
        let disposed = false;
        let isOpen = false;
        let reconnectAttempt = 0;
        let reconnectTimer: number | null = null;
        let tokenRefreshTimer: number | null = null;
        let source: EventSource | null = null;

        const handleMatchAlert = (event: MessageEvent) => {
            try {
                const parsed = JSON.parse(event.data) as LiveMatchAlert;
                setAlerts((prev) => prependUniqueAlert(prev, parsed));
                onAlertRef.current?.(parsed);
            } catch {
                // Ignore malformed SSE frames
            }
        };

        const resolveToken = async (forceRefresh: boolean): Promise<string | null> => {
            const refresher = refreshTokenRef.current;
            if (!refresher || (!forceRefresh && !isStreamTokenExpiringSoon(activeToken))) {
                return activeToken;
            }
            try {
                const nextToken = await refresher();
                if (nextToken) {
                    activeToken = nextToken;
                }
            } catch {
                return null;
            }
            return activeToken;
        };

        const scheduleProactiveRefresh = () => {
            tokenRefreshTimer = clearTimer(tokenRefreshTimer);
            if (!refreshTokenRef.current) {
                return;
            }
            const delayMs = computeTokenRefreshDelayMs(activeToken);
            if (delayMs === null) {
                return;
            }
            tokenRefreshTimer = window.setTimeout(() => {
                tokenRefreshTimer = null;
                if (!disposed) {
                    void connect(true);
                }
            }, delayMs);
        };

        const scheduleReconnect = (forceRefresh: boolean) => {
            if (disposed || reconnectTimer !== null) {
                return;
            }
            const delayMs = computeReconnectDelayMs(reconnectAttempt);
            reconnectAttempt += 1;
            reconnectTimer = window.setTimeout(() => {
                reconnectTimer = null;
                if (!disposed) {
                    void connect(forceRefresh);
                }
            }, delayMs);
        };

        const connect = async (forceRefresh: boolean) => {
            const tokenToUse = await resolveToken(forceRefresh);
            if (disposed) {
                return;
            }
            if (!tokenToUse) {
                scheduleReconnect(true);
                return;
            }

            closeEventSource(source, handleMatchAlert);
            const query = `?token=${encodeURIComponent(tokenToUse)}`;
            const nextSource = new EventSource(`/stream/alerts${query}`);
            source = nextSource;

            nextSource.onopen = () => {
                isOpen = true;
                reconnectAttempt = 0;
                setStreamConnected(true);
                scheduleProactiveRefresh();
                onOpenRef.current?.();
            };
            nextSource.onerror = () => {
                isOpen = false;
                setStreamConnected(false);
                if (!disposed && nextSource.readyState === EventSource.CLOSED) {
                    closeEventSource(nextSource, handleMatchAlert);
                    scheduleReconnect(true);
                }
            };
            nextSource.addEventListener("match_alert", handleMatchAlert);
        };

        const handleVisibilityChange = () => {
            if (disposed || document.hidden || isOpen) {
                return;
            }
            reconnectTimer = clearTimer(reconnectTimer);
            reconnectAttempt = 0;
            void connect(true);
        };

        document.addEventListener("visibilitychange", handleVisibilityChange);
        void connect(false);

        return () => {
            disposed = true;
            document.removeEventListener("visibilitychange", handleVisibilityChange);
            reconnectTimer = clearTimer(reconnectTimer);
            tokenRefreshTimer = clearTimer(tokenRefreshTimer);
            closeEventSource(source, handleMatchAlert);
            setStreamConnected(false);
        };
    }, [streamToken]);

    const dismissAlert = (id: string) =>
        setAlerts((prev) =>
            prev.filter((item) => getAlertDedupeKey(item) !== id && item.event_id !== id),
        );

    return { alerts, connected: Boolean(streamToken) && streamConnected, dismissAlert };
}
