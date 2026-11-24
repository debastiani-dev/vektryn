import { useEffect, useState } from "react";
import { vektrynApi } from "./api/client";
import { StackTrendsView } from "./components/analytics/StackTrendsView";
import { type ActiveTab, AppShell } from "./components/layout/AppShell";
import { JobRadarView } from "./components/radar/JobRadarView";
import { PipelineTrackerView } from "./components/tracker/PipelineTrackerView";
import { useAlertStream } from "./hooks/useAlertStream";

export function App() {
    const [activeTab, setActiveTab] = useState<ActiveTab>("radar");
    const [streamToken, setStreamToken] = useState<string | null>(null);
    const { alerts, connected, dismissAlert } = useAlertStream(streamToken);

    useEffect(() => {
        let cancelled = false;
        async function fetchSession() {
            try {
                const me = await vektrynApi.getCurrentUser();
                if (!cancelled) {
                    setStreamToken(me.stream_token);
                }
            } catch {
                if (!cancelled) {
                    setStreamToken(null);
                }
            }
        }
        void fetchSession();
        return () => {
            cancelled = true;
        };
    }, []);

    return (
        <AppShell
            activeTab={activeTab}
            onSelectTab={setActiveTab}
            sseConnected={connected}
            alerts={alerts}
            onDismissAlert={dismissAlert}
        >
            {activeTab === "radar" && <JobRadarView />}
            {activeTab === "tracker" && <PipelineTrackerView />}
            {activeTab === "analytics" && <StackTrendsView />}
        </AppShell>
    );
}

export default App;
