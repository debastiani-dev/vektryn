import { useCallback, useEffect, useState } from "react";
import { vektrynApi } from "./api/client";
import { StackTrendsView } from "./components/analytics/StackTrendsView";
import { LoginView } from "./components/auth/LoginView";
import { type ActiveTab, AppShell } from "./components/layout/AppShell";
import { GapAnalysisDrawer } from "./components/radar/GapAnalysisDrawer";
import { JobRadarView } from "./components/radar/JobRadarView";
import { ResumesView } from "./components/resumes/ResumesView";
import { PipelineTrackerView } from "./components/tracker/PipelineTrackerView";
import { useNotifications } from "./hooks/useNotifications";
import type { CurrentUser, MatchScore, NotificationItem } from "./types/models";
import { extractPayloadString } from "./utils/notifications";
import { clearPendingImport } from "./utils/pendingImportStorage";

export function App() {
    const [activeTab, setActiveTab] = useState<ActiveTab>("radar");
    const [user, setUser] = useState<CurrentUser | null>(null);
    const [checkingSession, setCheckingSession] = useState(true);
    const [activeNotificationMatch, setActiveNotificationMatch] = useState<MatchScore | null>(null);
    const [openingMatchId, setOpeningMatchId] = useState<string | null>(null);
    const [savingJobId, setSavingJobId] = useState<string | null>(null);
    const [savedJobIds, setSavedJobIds] = useState<Set<string>>(() => new Set());

    const {
        notifications,
        unreadCount,
        filter,
        setFilter,
        hasMore,
        loading,
        loadingMore,
        error,
        refresh,
        loadMore,
        markRead,
        dismiss,
        markAllRead,
        toasts,
        dismissToast,
        sseConnected,
    } = useNotifications(user?.stream_token ?? null);

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

    const handleLogout = useCallback(async () => {
        try {
            await vektrynApi.logout();
        } catch {
            // Clear local session regardless of server response
        } finally {
            clearPendingImport();
            setUser(null);
            setActiveTab("radar");
            setActiveNotificationMatch(null);
            setSavedJobIds(new Set());
        }
    }, []);

    const handleSaveJobToTracker = useCallback(
        async (jobPostingUuid: string, resumeProfileUuid?: string | null) => {
            setSavingJobId(jobPostingUuid);
            try {
                await vektrynApi.createLead({
                    job_posting: jobPostingUuid,
                    resume_profile: resumeProfileUuid ?? null,
                    status: "saved",
                    priority: "medium",
                });
                setSavedJobIds((prev) => new Set(prev).add(jobPostingUuid));
            } catch (err) {
                const message = err instanceof Error ? err.message.toLowerCase() : "";
                if (message.includes("already") || message.includes("unique")) {
                    setSavedJobIds((prev) => new Set(prev).add(jobPostingUuid));
                }
            } finally {
                setSavingJobId(null);
            }
        },
        [],
    );

    const handleOpenGapFromNotification = useCallback(
        async (item: NotificationItem) => {
            const matchUuid = extractPayloadString(item, "match_score_uuid");
            if (!matchUuid) return;
            setOpeningMatchId(matchUuid);
            try {
                const match = await vektrynApi.getMatch(matchUuid);
                setActiveNotificationMatch(match);
                if (!item.is_read) {
                    void markRead(item.uuid);
                }
            } finally {
                setOpeningMatchId(null);
            }
        },
        [markRead],
    );

    const handleSaveFromNotification = useCallback(
        (item: NotificationItem) => {
            const jobUuid = extractPayloadString(item, "job_posting_uuid");
            if (!jobUuid) return;
            const resumeUuid = extractPayloadString(item, "resume_profile_uuid");
            void handleSaveJobToTracker(jobUuid, resumeUuid);
            if (!item.is_read) {
                void markRead(item.uuid);
            }
        },
        [handleSaveJobToTracker, markRead],
    );

    const handleOpenTrackerFromNotification = useCallback(
        (item: NotificationItem) => {
            setActiveTab("tracker");
            if (!item.is_read) {
                void markRead(item.uuid);
            }
        },
        [markRead],
    );

    const handleOpenRadarFromNotification = useCallback(
        (item: NotificationItem) => {
            setActiveTab("radar");
            if (!item.is_read) {
                void markRead(item.uuid);
            }
        },
        [markRead],
    );

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

    const activeMatchJobId = activeNotificationMatch?.job_posting.uuid ?? "";

    return (
        <>
            <AppShell
                activeTab={activeTab}
                onSelectTab={setActiveTab}
                user={user}
                onLogout={() => void handleLogout()}
                sseConnected={sseConnected}
                alerts={toasts}
                onDismissAlert={dismissToast}
                notificationCenter={{
                    notifications,
                    unreadCount,
                    filter,
                    hasMore,
                    loading,
                    loadingMore,
                    error,
                    openingMatchId,
                    savingJobId,
                    savedJobIds,
                    onFilterChange: setFilter,
                    onRefresh: () => void refresh(),
                    onLoadMore: () => void loadMore(),
                    onMarkRead: (uuid) => void markRead(uuid),
                    onDismiss: (uuid) => void dismiss(uuid),
                    onMarkAllRead: () => void markAllRead(),
                    onOpenGapDetails: (item) => void handleOpenGapFromNotification(item),
                    onSaveToTracker: handleSaveFromNotification,
                    onOpenTracker: handleOpenTrackerFromNotification,
                    onOpenRadar: handleOpenRadarFromNotification,
                }}
            >
                {activeTab === "radar" && <JobRadarView />}
                {activeTab === "tracker" && <PipelineTrackerView />}
                {activeTab === "analytics" && <StackTrendsView />}
                {activeTab === "resumes" && <ResumesView />}
            </AppShell>

            <GapAnalysisDrawer
                match={activeNotificationMatch}
                saving={activeMatchJobId !== "" && savingJobId === activeMatchJobId}
                saved={activeMatchJobId !== "" && savedJobIds.has(activeMatchJobId)}
                onClose={() => setActiveNotificationMatch(null)}
                onSaveLead={(match) =>
                    void handleSaveJobToTracker(match.job_posting.uuid, match.resume_profile_uuid)
                }
            />
        </>
    );
}

export default App;
