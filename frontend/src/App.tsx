import { useEffect, useState } from "react";
import { vektrynApi } from "./api/client";
import { StackTrendsView } from "./components/analytics/StackTrendsView";
import { LoginView } from "./components/auth/LoginView";
import { type ActiveTab, AppShell } from "./components/layout/AppShell";
import { JobRadarView } from "./components/radar/JobRadarView";
import { ResumesView } from "./components/resumes/ResumesView";
import { PipelineTrackerView } from "./components/tracker/PipelineTrackerView";
import { useAlertStream } from "./hooks/useAlertStream";
import type { CurrentUser } from "./types/models";
import { clearPendingImport } from "./utils/pendingImportStorage";

export function App() {
    const [activeTab, setActiveTab] = useState<ActiveTab>("radar");
    const [user, setUser] = useState<CurrentUser | null>(null);
    const [checkingSession, setCheckingSession] = useState(true);
    const { alerts, connected, dismissAlert } = useAlertStream(user?.stream_token ?? null);

    useEffect(() => {
        let cancelled = false;
        async function fetchSession() {
            try {
                const me = await vektrynApi.getCurrentUser();
                if (!cancelled) {
                    setUser(me);
                }
            } catch {
                if (!cancelled) {
                    setUser(null);
                }
            } finally {
                if (!cancelled) {
                    setCheckingSession(false);
                }
            }
        }
        void fetchSession();
        return () => {
            cancelled = true;
        };
    }, []);

    async function handleLogout() {
        try {
            await vektrynApi.logout();
        } catch {
            // Clear local session regardless of server response
        } finally {
            clearPendingImport();
            setUser(null);
            setActiveTab("radar");
        }
    }

    if (checkingSession) {
        return (
            <div className="flex min-h-screen items-center justify-center text-sm text-zinc-500">
                Checking session...
            </div>
        );
    }

    if (!user) {
        return <LoginView onAuthenticated={setUser} />;
    }

    return (
        <AppShell
            activeTab={activeTab}
            onSelectTab={setActiveTab}
            user={user}
            onLogout={() => void handleLogout()}
            sseConnected={connected}
            alerts={alerts}
            onDismissAlert={dismissAlert}
        >
            {activeTab === "radar" && <JobRadarView />}
            {activeTab === "tracker" && <PipelineTrackerView />}
            {activeTab === "analytics" && <StackTrendsView />}
            {activeTab === "resumes" && <ResumesView />}
        </AppShell>
    );
}

export default App;
