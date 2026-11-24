import { useEffect, useState } from "react";
import type { LiveMatchAlert } from "../types/models";

export function useAlertStream(streamToken: string | null) {
    const [alerts, setAlerts] = useState<LiveMatchAlert[]>([]);
    const [connected, setConnected] = useState(false);

    useEffect(() => {
        if (!streamToken) {
            setConnected(false);
            return;
        }

        const query = `?token=${encodeURIComponent(streamToken)}`;
        const source = new EventSource(`/stream/alerts${query}`);

        source.onopen = () => setConnected(true);
        source.onerror = () => setConnected(false);

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
            setConnected(false);
        };
    }, [streamToken]);

    const dismissAlert = (eventId: string) =>
        setAlerts((prev) => prev.filter((item) => item.event_id !== eventId));

    return { alerts, connected, dismissAlert };
}
