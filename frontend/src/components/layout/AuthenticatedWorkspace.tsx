import { useCallback, useEffect, useState } from "react";
import { vektrynApi } from "../../api/client";
import { useNotifications } from "../../hooks/useNotifications";
import type {
    CurrentUser,
    MatchScore,
    NotificationItem,
    UserProfileDetail,
} from "../../types/models";
import { extractPayloadString } from "../../utils/notifications";
import { StackTrendsView } from "../analytics/StackTrendsView";
import { GapAnalysisDrawer } from "../radar/GapAnalysisDrawer";
import { JobRadarView } from "../radar/JobRadarView";
import { ResumesView } from "../resumes/ResumesView";
import { PipelineTrackerView } from "../tracker/PipelineTrackerView";
import { type ActiveTab, AppShell } from "./AppShell";

interface AuthenticatedWorkspaceProps {
    user: CurrentUser;
    onUserProfileSaved: (updatedProfile: UserProfileDetail) => void;
    onAccountDeactivated: () => void;
    onLogout: () => Promise<void>;
}

export function AuthenticatedWorkspace({
    user,
    onUserProfileSaved,
    onAccountDeactivated,
    onLogout,
}: Readonly<AuthenticatedWorkspaceProps>) {
    const [activeTab, setActiveTab] = useState<ActiveTab>("radar");
    const [settingsModalOpen, setSettingsModalOpen] = useState(false);

    useEffect(() => {
        globalThis.scrollTo?.({ top: 0, behavior: "instant" });
    }, [activeTab]);
    const [pendingRadarSearch, setPendingRadarSearch] = useState("");
    const [pendingRadarResume, setPendingRadarResume] = useState("");
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
    } = useNotifications(user.stream_token ?? null);

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

    const handleSearchSkillInRadar = useCallback(
        (skill: string, resumeProfileUuid?: string) => {
            setPendingRadarSearch(skill);
            setPendingRadarResume(resumeProfileUuid ?? "");
            setActiveTab("radar");
        },
        [],
    );

    const handleConsumeRadarSearch = useCallback(() => {
        setPendingRadarSearch("");
        setPendingRadarResume("");
    }, []);

    const handleOpenSettingsFromNotification = useCallback(
        (item: NotificationItem) => {
            setSettingsModalOpen(true);
            if (!item.is_read) {
                void markRead(item.uuid);
            }
        },
        [markRead],
    );

    const handleOpenAccountSettings = useCallback(() => {
        setActiveNotificationMatch(null);
        setSettingsModalOpen(true);
    }, []);

    const activeMatchJobId = activeNotificationMatch?.job_posting.uuid ?? "";
    const defaultCopilotTone = user.profile?.default_copilot_tone ?? "balanced";
    const hasGeminiApiKey = Boolean(user.profile?.has_gemini_api_key);

    return (
        <>
            <AppShell
                activeTab={activeTab}
                onSelectTab={setActiveTab}
                user={user}
                settingsModalOpen={settingsModalOpen}
                onOpenSettings={() => setSettingsModalOpen(true)}
                onCloseSettings={() => setSettingsModalOpen(false)}
                onUserProfileSaved={onUserProfileSaved}
                onAccountDeactivated={onAccountDeactivated}
                onLogout={() => void onLogout()}
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
                    onOpenAccountSettings: handleOpenSettingsFromNotification,
                }}
            >
                {activeTab === "radar" && (
                    <JobRadarView
                        initialSearch={pendingRadarSearch}
                        initialResumeFilter={pendingRadarResume}
                        onConsumeInitialSearch={handleConsumeRadarSearch}
                        defaultCopilotTone={defaultCopilotTone}
                        hasGeminiApiKey={hasGeminiApiKey}
                        onOpenAccountSettings={handleOpenAccountSettings}
                    />
                )}
                {activeTab === "tracker" && (
                    <PipelineTrackerView
                        defaultCopilotTone={defaultCopilotTone}
                        hasGeminiApiKey={hasGeminiApiKey}
                        onOpenAccountSettings={handleOpenAccountSettings}
                    />
                )}
                {activeTab === "analytics" && (
                    <StackTrendsView onSearchSkillInRadar={handleSearchSkillInRadar} />
                )}
                {activeTab === "resumes" && (
                    <ResumesView
                        hasGeminiApiKey={hasGeminiApiKey}
                        onOpenAccountSettings={handleOpenAccountSettings}
                    />
                )}
            </AppShell>

            <GapAnalysisDrawer
                match={activeNotificationMatch}
                defaultCopilotTone={defaultCopilotTone}
                hasGeminiApiKey={hasGeminiApiKey}
                onOpenAccountSettings={handleOpenAccountSettings}
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

export default AuthenticatedWorkspace;
