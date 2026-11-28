import { useEffect, useRef, useState } from "react";
import type { LiveMatchAlert } from "../types/models";
import { getAlertDedupeKey } from "../utils/notifications";

const INITIAL_RECONNECT_DELAY_MS = 1_500;
const MAX_RECONNECT_DELAY_MS = 30_000;

export function computeReconnectDelayMs(attempt: number): number {
    const safeAttempt = Math.max(0, Math.floor(attempt));
    return Math.min(MAX_RECONNECT_DELAY_MS, INITIAL_RECONNECT_DELAY_MS * 2 ** safeAttempt);
}

interface UseAlertStreamOptions {
    onAlert?: (alert: LiveMatchAlert) => void;
    onOpen?: () => void;
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

    useEffect(() => {
        onAlertRef.current = options.onAlert;
        onOpenRef.current = options.onOpen;
    }, [options.onAlert, options.onOpen]);

    useEffect(() => {
        if (!streamToken) {
            return;
        }

        const query = `?token=${encodeURIComponent(streamToken)}`;
        let disposed = false;
        let reconnectAttempt = 0;
        let reconnectTimer: number | null = null;
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

        const scheduleReconnect = () => {
            if (disposed || reconnectTimer !== null) {
                return;
            }
            const delayMs = computeReconnectDelayMs(reconnectAttempt);
            reconnectAttempt += 1;
            reconnectTimer = window.setTimeout(() => {
                reconnectTimer = null;
                if (!disposed) {
                    connect();
                }
            }, delayMs);
        };

        const connect = () => {
            const nextSource = new EventSource(`/stream/alerts${query}`);
            source = nextSource;

            nextSource.onopen = () => {
                reconnectAttempt = 0;
                setStreamConnected(true);
                onOpenRef.current?.();
            };
            nextSource.onerror = () => {
                setStreamConnected(false);
                if (!disposed && nextSource.readyState === EventSource.CLOSED) {
                    nextSource.removeEventListener("match_alert", handleMatchAlert);
                    nextSource.close();
                    scheduleReconnect();
                }
            };
            nextSource.addEventListener("match_alert", handleMatchAlert);
        };

        connect();

        return () => {
            disposed = true;
            if (reconnectTimer !== null) {
                window.clearTimeout(reconnectTimer);
                reconnectTimer = null;
            }
            if (source) {
                source.removeEventListener("match_alert", handleMatchAlert);
                source.close();
            }
            setStreamConnected(false);
        };
    }, [streamToken]);

    const dismissAlert = (id: string) =>
        setAlerts((prev) =>
            prev.filter((item) => getAlertDedupeKey(item) !== id && item.event_id !== id),
        );

    return { alerts, connected: Boolean(streamToken) && streamConnected, dismissAlert };
}
