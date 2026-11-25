import { useEffect, useRef, useState } from "react";
import type { LiveMatchAlert } from "../types/models";
import { getAlertDedupeKey } from "../utils/notifications";

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
        const source = new EventSource(`/stream/alerts${query}`);

        source.onopen = () => {
            setStreamConnected(true);
            onOpenRef.current?.();
        };
        source.onerror = () => setStreamConnected(false);

        const handleMatchAlert = (event: MessageEvent) => {
            try {
                const parsed = JSON.parse(event.data) as LiveMatchAlert;
                setAlerts((prev) => prependUniqueAlert(prev, parsed));
                onAlertRef.current?.(parsed);
            } catch {
                // Ignore malformed SSE frames
            }
        };
        source.addEventListener("match_alert", handleMatchAlert);

        return () => {
            source.removeEventListener("match_alert", handleMatchAlert);
            source.close();
            setStreamConnected(false);
        };
    }, [streamToken]);

    const dismissAlert = (id: string) =>
        setAlerts((prev) =>
            prev.filter((item) => getAlertDedupeKey(item) !== id && item.event_id !== id),
        );

    return { alerts, connected: Boolean(streamToken) && streamConnected, dismissAlert };
}
