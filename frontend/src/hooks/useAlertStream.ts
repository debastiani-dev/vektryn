import { useEffect, useState } from "react";
import type { LiveMatchAlert } from "../types/models";

export function useAlertStream(streamToken: string | null) {
    const [alerts, setAlerts] = useState<LiveMatchAlert[]>([]);
    const [streamConnected, setStreamConnected] = useState(false);

    useEffect(() => {
        if (!streamToken) {
            return;
        }

        const query = `?token=${encodeURIComponent(streamToken)}`;
        const source = new EventSource(`/stream/alerts${query}`);

        source.onopen = () => setStreamConnected(true);
        source.onerror = () => setStreamConnected(false);

        source.addEventListener("match_alert", (event: MessageEvent) => {
            try {
                const parsed = JSON.parse(event.data) as LiveMatchAlert;
                setAlerts((prev) => [parsed, ...prev].slice(0, 10));
            } catch {
                // Ignore malformed SSE frames
            }
        });

        return () => {
            source.close();
            setStreamConnected(false);
        };
    }, [streamToken]);

    const dismissAlert = (eventId: string) =>
        setAlerts((prev) => prev.filter((item) => item.event_id !== eventId));

    return { alerts, connected: Boolean(streamToken) && streamConnected, dismissAlert };
}
