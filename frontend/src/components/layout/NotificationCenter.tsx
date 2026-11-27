import {
    AlertTriangle,
    Bell,
    BookmarkCheck,
    BookmarkPlus,
    CalendarClock,
    Check,
    CheckCheck,
    Database,
    FileCheck2,
    Kanban,
    KeyRound,
    Loader2,
    Radar,
    RefreshCw,
    ShieldAlert,
    Sparkles,
    UserCog,
    X,
} from "lucide-react";
import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import type { NotificationFilter } from "../../hooks/useNotifications";
import type { NotificationItem } from "../../types/models";
import { formatExactDate, formatRelativeTime, scoreBadgeStyle } from "../../utils/format";
import { extractPayloadString, formatUnreadBadge } from "../../utils/notifications";
import { Tooltip } from "../ui/Tooltip";

export interface NotificationCenterProps {
    notifications: NotificationItem[];
    unreadCount: number;
    filter: NotificationFilter;
    hasMore: boolean;
    loading: boolean;
    loadingMore: boolean;
    error: string | null;
    openingMatchId: string | null;
    savingJobId: string | null;
    savedJobIds: ReadonlySet<string>;
    onFilterChange: (filter: NotificationFilter) => void;
    onRefresh: () => void;
    onLoadMore: () => void;
    onMarkRead: (uuid: string) => void;
    onDismiss: (uuid: string) => void;
    onMarkAllRead: () => void;
    onOpenGapDetails: (item: NotificationItem) => void;
    onSaveToTracker: (item: NotificationItem) => void;
    onOpenTracker: (item: NotificationItem) => void;
    onOpenRadar: (item: NotificationItem) => void;
    onOpenAccountSettings?: (item: NotificationItem) => void;
}

function NotificationKindBadge({ item }: Readonly<{ item: NotificationItem }>) {
    const fit = typeof item.payload.fit_score === "number" ? item.payload.fit_score : null;
    if (item.kind === "match_alert") {
        return (
            <div className="flex items-center gap-1.5">
                <span className="inline-flex items-center gap-1 rounded-md bg-violet-500/15 px-2 py-0.5 text-[11px] font-semibold text-violet-300 ring-1 ring-violet-500/30">
                    <Sparkles className="h-3 w-3" />
                    High Fit
                </span>
                {fit !== null && (
                    <span
                        className={`rounded-md px-2 py-0.5 font-mono text-[11px] font-semibold tabular-nums ${scoreBadgeStyle(fit)}`}
                    >
                        {fit}%
                    </span>
                )}
            </div>
        );
    }
    if (item.kind === "manual_import_ready") {
        return (
            <div className="flex items-center gap-1.5">
                <span className="inline-flex items-center gap-1 rounded-md bg-sky-500/15 px-2 py-0.5 text-[11px] font-semibold text-sky-300 ring-1 ring-sky-500/30">
                    <FileCheck2 className="h-3 w-3" />
                    Import Scored
                </span>
                {fit !== null && (
                    <span
                        className={`rounded-md px-2 py-0.5 font-mono text-[11px] font-semibold tabular-nums ${scoreBadgeStyle(fit)}`}
                    >
                        {fit}%
                    </span>
                )}
            </div>
        );
    }
    if (item.kind === "rescore_completed") {
        return (
            <span className="inline-flex items-center gap-1 rounded-md bg-indigo-500/15 px-2 py-0.5 text-[11px] font-semibold text-indigo-300 ring-1 ring-indigo-500/30">
                <RefreshCw className="h-3 w-3" />
                Rescore Complete
            </span>
        );
    }
    if (item.kind === "collector_sync_completed") {
        return (
            <span className="inline-flex items-center gap-1 rounded-md bg-emerald-500/15 px-2 py-0.5 text-[11px] font-semibold text-emerald-300 ring-1 ring-emerald-500/30">
                <Database className="h-3 w-3" />
                Collector Sync
            </span>
        );
    }
    if (item.kind === "lead_followup_due") {
        return (
            <span className="inline-flex items-center gap-1 rounded-md bg-amber-500/15 px-2 py-0.5 text-[11px] font-semibold text-amber-300 ring-1 ring-amber-500/35">
                <CalendarClock className="h-3 w-3" />
                Follow-up Due
            </span>
        );
    }
    if (item.kind === "tracked_job_closed") {
        return (
            <span className="inline-flex items-center gap-1 rounded-md bg-amber-500/15 px-2 py-0.5 text-[11px] font-semibold text-amber-300 ring-1 ring-amber-500/30">
                <AlertTriangle className="h-3 w-3" />
                Role Closed
            </span>
        );
    }
    if (item.kind === "ai_key_invalid") {
        return (
            <span className="inline-flex items-center gap-1 rounded-md bg-red-500/15 px-2 py-0.5 text-[11px] font-semibold text-red-300 ring-1 ring-red-500/35">
                <KeyRound className="h-3 w-3" />
                <span>API Key Invalid</span>
            </span>
        );
    }
    if (item.kind === "ai_quota_exhausted") {
        return (
            <span className="inline-flex items-center gap-1 rounded-md bg-amber-500/15 px-2 py-0.5 text-[11px] font-semibold text-amber-300 ring-1 ring-amber-500/35">
                <AlertTriangle className="h-3 w-3" />
                <span>AI Quota / Credits</span>
            </span>
        );
    }
    return (
        <span className="inline-flex items-center gap-1 rounded-md bg-red-500/15 px-2 py-0.5 text-[11px] font-semibold text-red-300 ring-1 ring-red-500/30">
            <ShieldAlert className="h-3 w-3" />
            <span>Pipeline Error</span>
        </span>
    );
}

interface NotificationCardProps {
    item: NotificationItem;
    isOpeningGap: boolean;
    isSavingJob: boolean;
    isSavedJob: boolean;
    onOpenGapDetails: (item: NotificationItem) => void;
    onSaveToTracker: (item: NotificationItem) => void;
    onOpenTracker: (item: NotificationItem) => void;
    onOpenRadar: (item: NotificationItem) => void;
    onOpenAccountSettings?: (item: NotificationItem) => void;
    onMarkRead: (uuid: string) => void;
    onDismiss: (uuid: string) => void;
}

function getSaveButtonText(isSavedJob: boolean, isSavingJob: boolean): string {
    if (isSavedJob) return "Saved";
    if (isSavingJob) return "Saving...";
    return "Save to Tracker";
}

function isJobMatchNotification(kind: NotificationItem["kind"]): boolean {
    return kind === "match_alert" || kind === "manual_import_ready";
}

function NotificationCard({
    item,
    isOpeningGap,
    isSavingJob,
    isSavedJob,
    onOpenGapDetails,
    onSaveToTracker,
    onOpenTracker,
    onOpenRadar,
    onOpenAccountSettings,
    onMarkRead,
    onDismiss,
}: Readonly<NotificationCardProps>) {
    const matchScoreUuid = extractPayloadString(item, "match_score_uuid");
    const jobPostingUuid = extractPayloadString(item, "job_posting_uuid");
    const isMatchItem = isJobMatchNotification(item.kind);
    const relativeTime = formatRelativeTime(item.created_at) ?? "Just now";
    const exactTime = formatExactDate(item.created_at) ?? item.created_at;

    return (
        <article
            className={`rounded-2xl border p-4 transition ${
                item.is_read
                    ? "border-zinc-800/80 bg-zinc-900/35"
                    : "border-violet-500/30 bg-zinc-900/80 ring-1 ring-inset ring-violet-500/15"
            }`}
        >
            <div className="flex items-start justify-between gap-3">
                <div className="min-w-0 flex-1 space-y-1.5">
                    <div className="flex flex-wrap items-center gap-2">
                        {!item.is_read && (
                            <span
                                aria-label="Unread"
                                className="h-2 w-2 shrink-0 rounded-full bg-violet-400"
                            />
                        )}
                        <NotificationKindBadge item={item} />
                        <Tooltip content={exactTime} side="bottom">
                            <span className="font-mono text-[11px] text-zinc-500">
                                {relativeTime}
                            </span>
                        </Tooltip>
                    </div>
                    <h3 className="text-sm font-semibold leading-snug text-zinc-100">
                        {item.title}
                    </h3>
                    {item.body && (
                        <p className="text-xs leading-relaxed text-zinc-400">{item.body}</p>
                    )}
                </div>

                <Tooltip content="Dismiss notification" side="bottom">
                    <button
                        type="button"
                        onClick={() => onDismiss(item.uuid)}
                        aria-label="Dismiss notification"
                        className="rounded-lg p-1.5 text-zinc-500 transition hover:bg-zinc-800 hover:text-zinc-200"
                    >
                        <X className="h-3.5 w-3.5" />
                    </button>
                </Tooltip>
            </div>

            <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-zinc-800/70 pt-3">
                {isMatchItem && matchScoreUuid && (
                    <button
                        type="button"
                        disabled={isOpeningGap}
                        onClick={() => onOpenGapDetails(item)}
                        className="inline-flex items-center gap-1.5 rounded-lg bg-violet-600 px-2.5 py-1.5 text-xs font-medium text-white transition hover:bg-violet-500 disabled:opacity-60"
                    >
                        {isOpeningGap ? (
                            <Loader2 className="h-3.5 w-3.5 animate-spin" />
                        ) : (
                            <Sparkles className="h-3.5 w-3.5" />
                        )}
                        Open Gap Details
                    </button>
                )}

                {isMatchItem && jobPostingUuid && (
                    <button
                        type="button"
                        disabled={isSavingJob || isSavedJob}
                        onClick={() => onSaveToTracker(item)}
                        className={`inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-xs font-medium transition disabled:cursor-not-allowed ${
                            isSavedJob
                                ? "border-emerald-500/30 bg-emerald-950/30 text-emerald-300"
                                : "border-zinc-700 bg-zinc-800/80 text-zinc-200 hover:bg-zinc-700 disabled:opacity-50"
                        }`}
                    >
                        {isSavedJob ? (
                            <BookmarkCheck className="h-3.5 w-3.5 text-emerald-400" />
                        ) : (
                            <BookmarkPlus className="h-3.5 w-3.5 text-violet-400" />
                        )}
                        {getSaveButtonText(isSavedJob, isSavingJob)}
                    </button>
                )}

                {item.kind === "rescore_completed" && (
                    <button
                        type="button"
                        onClick={() => onOpenRadar(item)}
                        className="inline-flex items-center gap-1.5 rounded-lg bg-indigo-500/20 px-2.5 py-1.5 text-xs font-medium text-indigo-200 ring-1 ring-indigo-500/30 transition hover:bg-indigo-500/30"
                    >
                        <Radar className="h-3.5 w-3.5" />
                        Open Job Radar
                    </button>
                )}

                {(item.kind === "tracked_job_closed" || item.kind === "lead_followup_due") && (
                    <button
                        type="button"
                        onClick={() => onOpenTracker(item)}
                        className="inline-flex items-center gap-1.5 rounded-lg bg-amber-500/20 px-2.5 py-1.5 text-xs font-medium text-amber-200 ring-1 ring-amber-500/30 transition hover:bg-amber-500/30"
                    >
                        <Kanban className="h-3.5 w-3.5" />
                        <span>Open Tracker</span>
                    </button>
                )}

                {(item.kind === "ai_key_invalid" || item.kind === "ai_quota_exhausted") &&
                    onOpenAccountSettings && (
                        <button
                            type="button"
                            onClick={() => onOpenAccountSettings(item)}
                            className="inline-flex items-center gap-1.5 rounded-lg bg-violet-600 px-2.5 py-1.5 text-xs font-medium text-white transition hover:bg-violet-500"
                        >
                            <UserCog className="h-3.5 w-3.5" />
                            <span>Open Account Settings</span>
                        </button>
                    )}

                {!item.is_read && (
                    <button
                        type="button"
                        onClick={() => onMarkRead(item.uuid)}
                        className="ml-auto inline-flex items-center gap-1 rounded-lg px-2 py-1.5 text-xs font-medium text-zinc-400 transition hover:bg-zinc-800 hover:text-zinc-100"
                    >
                        <Check className="h-3.5 w-3.5" />
                        Mark Read
                    </button>
                )}
            </div>
        </article>
    );
}

export function NotificationCenter({
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
    onFilterChange,
    onRefresh,
    onLoadMore,
    onMarkRead,
    onDismiss,
    onMarkAllRead,
    onOpenGapDetails,
    onSaveToTracker,
    onOpenTracker,
    onOpenRadar,
    onOpenAccountSettings,
}: Readonly<NotificationCenterProps>) {
    const [open, setOpen] = useState(false);

    useEffect(() => {
        if (!open) return;
        const handleKeyDown = (event: KeyboardEvent) => {
            if (event.key === "Escape") {
                setOpen(false);
            }
        };
        window.addEventListener("keydown", handleKeyDown);
        return () => window.removeEventListener("keydown", handleKeyDown);
    }, [open]);

    const handleOpenGap = (item: NotificationItem) => {
        setOpen(false);
        onOpenGapDetails(item);
    };

    const handleOpenTracker = (item: NotificationItem) => {
        setOpen(false);
        onOpenTracker(item);
    };

    const handleOpenRadar = (item: NotificationItem) => {
        setOpen(false);
        onOpenRadar(item);
    };

    const handleOpenAccountSettings = (item: NotificationItem) => {
        setOpen(false);
        onOpenAccountSettings?.(item);
    };

    return (
        <>
            <Tooltip
                content={
                    unreadCount > 0
                        ? `Notifications (${unreadCount} unread)`
                        : "Notifications inbox"
                }
                side="bottom"
            >
                <button
                    type="button"
                    aria-label="Open notifications"
                    aria-expanded={open}
                    aria-haspopup="dialog"
                    onClick={() => {
                        const nextOpen = !open;
                        setOpen(nextOpen);
                        if (nextOpen) {
                            onRefresh();
                        }
                    }}
                    className={`relative inline-flex items-center justify-center rounded-full p-2 text-xs font-medium ring-1 ring-inset transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-500/70 ${
                        unreadCount > 0
                            ? "bg-violet-950/40 text-violet-200 ring-violet-500/40 hover:bg-violet-950/60"
                            : "bg-zinc-900/80 text-zinc-300 ring-zinc-800 hover:bg-zinc-900 hover:text-zinc-100"
                    }`}
                >
                    <Bell className="h-4 w-4" />
                    {unreadCount > 0 && (
                        <span className="absolute -top-1 -right-1 flex min-w-4.5 items-center justify-center rounded-full bg-violet-500 px-1 py-0.2 font-mono text-[10px] font-bold leading-4 text-white shadow-sm shadow-violet-900/60">
                            {formatUnreadBadge(unreadCount)}
                        </span>
                    )}
                </button>
            </Tooltip>

            {open &&
                createPortal(
                    <div className="fixed inset-0 z-50 flex justify-end overflow-hidden">
                        <button
                            type="button"
                            aria-label="Close notifications drawer"
                            onClick={() => setOpen(false)}
                            className="fixed inset-0 cursor-default bg-black/65 backdrop-blur-xs"
                        />
                        <dialog
                            open
                            aria-modal="true"
                            aria-labelledby="notification-drawer-title"
                            className="animate-drawer-in relative inset-auto z-10 m-0 flex h-dvh max-h-none w-full max-w-[min(28rem,100vw)] min-w-0 flex-col overflow-x-hidden border-0 border-zinc-800 bg-zinc-950 p-0 text-zinc-100 shadow-2xl sm:h-full sm:border-l"
                        >
                            <div className="space-y-3 border-b border-zinc-800/90 bg-zinc-950/95 px-5 py-4">
                                <div className="flex items-center justify-between gap-2">
                                    <div className="flex items-center gap-2.5">
                                        <Bell className="h-4 w-4 text-violet-400" />
                                        <h2
                                            id="notification-drawer-title"
                                            className="text-base font-semibold text-zinc-100"
                                        >
                                            Notifications
                                        </h2>
                                        {unreadCount > 0 && (
                                            <span className="rounded-full bg-violet-500/20 px-2 py-0.5 font-mono text-[11px] font-semibold text-violet-300 ring-1 ring-violet-500/35">
                                                {unreadCount} unread
                                            </span>
                                        )}
                                    </div>
                                    <div className="flex items-center gap-1">
                                        <button
                                            type="button"
                                            onClick={onRefresh}
                                            disabled={loading}
                                            aria-label="Refresh notifications"
                                            className="rounded-lg p-1.5 text-zinc-400 transition hover:bg-zinc-800 hover:text-zinc-100 disabled:opacity-50"
                                        >
                                            <RefreshCw
                                                className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`}
                                            />
                                        </button>
                                        <button
                                            type="button"
                                            onClick={() => setOpen(false)}
                                            aria-label="Close notifications"
                                            className="rounded-lg p-1.5 text-zinc-400 transition hover:bg-zinc-800 hover:text-zinc-100"
                                        >
                                            <X className="h-4 w-4" />
                                        </button>
                                    </div>
                                </div>

                                <div className="flex items-center justify-between gap-2">
                                    <div className="inline-flex rounded-xl border border-zinc-800 bg-zinc-900/70 p-0.5 text-xs">
                                        <button
                                            type="button"
                                            onClick={() => onFilterChange("all")}
                                            className={`rounded-lg px-3 py-1 font-medium transition ${
                                                filter === "all"
                                                    ? "bg-zinc-800 text-zinc-100"
                                                    : "text-zinc-400 hover:text-zinc-200"
                                            }`}
                                        >
                                            All
                                        </button>
                                        <button
                                            type="button"
                                            onClick={() => onFilterChange("unread")}
                                            className={`rounded-lg px-3 py-1 font-medium transition ${
                                                filter === "unread"
                                                    ? "bg-zinc-800 text-zinc-100"
                                                    : "text-zinc-400 hover:text-zinc-200"
                                            }`}
                                        >
                                            Unread
                                        </button>
                                    </div>

                                    <button
                                        type="button"
                                        disabled={unreadCount === 0}
                                        onClick={onMarkAllRead}
                                        className="inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1 text-xs font-medium text-violet-300 transition hover:bg-violet-500/15 disabled:cursor-not-allowed disabled:opacity-40"
                                    >
                                        <CheckCheck className="h-3.5 w-3.5" />
                                        Mark all read
                                    </button>
                                </div>
                            </div>

                            <div className="flex-1 space-y-3 overflow-y-auto px-5 py-4">
                                {error && (
                                    <div className="rounded-xl border border-red-500/30 bg-red-950/25 px-3.5 py-2.5 text-xs text-red-300">
                                        {error}
                                    </div>
                                )}

                                {!loading && notifications.length === 0 && (
                                    <div className="flex flex-col items-center justify-center rounded-2xl border border-zinc-800/70 bg-zinc-900/35 px-6 py-12 text-center">
                                        <Bell className="h-8 w-8 text-zinc-600" />
                                        <p className="mt-3 text-sm font-medium text-zinc-300">
                                            {filter === "unread"
                                                ? "No unread notifications"
                                                : "You're all caught up"}
                                        </p>
                                        <p className="mt-1 text-xs text-zinc-500">
                                            High-fit matches, tracked role closures, and pipeline
                                            alerts will appear here.
                                        </p>
                                    </div>
                                )}

                                {notifications.map((item) => {
                                    const matchUuid = extractPayloadString(
                                        item,
                                        "match_score_uuid",
                                    );
                                    const jobUuid = extractPayloadString(item, "job_posting_uuid");
                                    return (
                                        <NotificationCard
                                            key={item.uuid}
                                            item={item}
                                            isOpeningGap={
                                                matchUuid !== null && openingMatchId === matchUuid
                                            }
                                            isSavingJob={
                                                jobUuid !== null && savingJobId === jobUuid
                                            }
                                            isSavedJob={
                                                jobUuid !== null && savedJobIds.has(jobUuid)
                                            }
                                            onOpenGapDetails={handleOpenGap}
                                            onSaveToTracker={onSaveToTracker}
                                            onOpenTracker={handleOpenTracker}
                                            onOpenRadar={handleOpenRadar}
                                            onOpenAccountSettings={
                                                onOpenAccountSettings
                                                    ? handleOpenAccountSettings
                                                    : undefined
                                            }
                                            onMarkRead={onMarkRead}
                                            onDismiss={onDismiss}
                                        />
                                    );
                                })}

                                {hasMore && (
                                    <button
                                        type="button"
                                        disabled={loadingMore}
                                        onClick={onLoadMore}
                                        className="inline-flex w-full items-center justify-center gap-2 rounded-xl border border-zinc-800 bg-zinc-900/60 px-4 py-2 text-xs font-medium text-zinc-300 transition hover:bg-zinc-800 disabled:opacity-50"
                                    >
                                        {loadingMore && (
                                            <Loader2 className="h-3.5 w-3.5 animate-spin" />
                                        )}
                                        {loadingMore ? "Loading..." : "Load older notifications"}
                                    </button>
                                )}
                            </div>
                        </dialog>
                    </div>,
                    document.body,
                )}
        </>
    );
}
