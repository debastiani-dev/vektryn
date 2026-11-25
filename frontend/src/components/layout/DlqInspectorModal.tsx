import {
    AlertTriangle,
    Archive,
    CheckCircle2,
    ChevronDown,
    ChevronRight,
    Eye,
    Loader2,
    RefreshCw,
    RotateCcw,
    ShieldAlert,
    X,
} from "lucide-react";
import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { ApiError, vektrynApi } from "../../api/client";
import type {
    DlqInspectResponse,
    DlqMessageItem,
    DlqReplayItemResult,
    DlqReplayRequest,
    DlqReplayResponse,
    ReplayableTopic,
} from "../../types/models";
import { formatExactDate, formatRelativeTime } from "../../utils/format";

interface DlqInspectorModalProps {
    open: boolean;
    onClose: () => void;
    onReplayed?: () => void;
}

const TOPIC_OPTIONS: { value: "" | ReplayableTopic; label: string }[] = [
    { value: "", label: "All topics" },
    { value: "jobs.raw", label: "jobs.raw" },
    { value: "jobs.enriched", label: "jobs.enriched" },
    { value: "jobs.rescore", label: "jobs.rescore" },
];

const DEFAULT_BATCH_LIMIT = 10;

function formatDlqError(err: unknown): string {
    if (err instanceof ApiError) {
        if (err.status === 403) {
            return "Staff permissions are required to inspect or replay DLQ messages.";
        }
        if (err.status === 429) {
            if (err.retryAfterSeconds) {
                return `Replay cooldown active. Try again in ${err.retryAfterSeconds}s.`;
            }
            return err.detail || "Replay cooldown active. Please wait before retrying.";
        }
        if (err.status === 503) {
            return err.detail || "Kafka broker is currently unavailable.";
        }
        if (err.detail) {
            return err.detail;
        }
    }
    return "Failed to communicate with the DLQ service.";
}

function formatStatusWithReason(prefix: string, reason: string): string {
    return reason ? `${prefix}: ${reason}` : prefix;
}

function getReplayResultBadge(result: DlqReplayItemResult): { label: string; style: string } {
    if (result.status === "replayed") {
        return {
            label: "Replayed",
            style: "bg-emerald-500/15 text-emerald-300 ring-emerald-500/30",
        };
    }
    if (result.status === "would_replay") {
        return {
            label: "Dry-run: would replay",
            style: "bg-sky-500/15 text-sky-300 ring-sky-500/30",
        };
    }
    if (result.status === "failed") {
        return {
            label: formatStatusWithReason("Failed", result.reason),
            style: "bg-red-500/15 text-red-300 ring-red-500/35",
        };
    }
    return {
        label: formatStatusWithReason("Skipped", result.reason),
        style: "bg-zinc-800 text-zinc-400 ring-zinc-700",
    };
}

function isDlqItemResolved(item: DlqMessageItem): boolean {
    return Boolean(item.replayed_at || item.dismissed_at);
}

function DlqMessageRow({
    item,
    selected,
    expanded,
    replayResult,
    dismissing,
    onToggleSelect,
    onToggleExpand,
    onDismissSingle,
}: Readonly<{
    item: DlqMessageItem;
    selected: boolean;
    expanded: boolean;
    replayResult?: DlqReplayItemResult;
    dismissing: boolean;
    onToggleSelect: () => void;
    onToggleExpand: () => void;
    onDismissSingle: () => void;
}>) {
    const producedRelative = formatRelativeTime(item.produced_at);
    const producedExact = formatExactDate(item.produced_at);
    const resultBadge = replayResult ? getReplayResultBadge(replayResult) : null;
    const resolved = isDlqItemResolved(item);

    return (
        <div
            className={`rounded-xl border transition ${
                resolved
                    ? "border-zinc-800/60 bg-zinc-900/30 opacity-80"
                    : "border-zinc-800/90 bg-zinc-900/55 hover:border-zinc-700/80"
            }`}
        >
            <div className="flex items-start gap-3 px-3.5 py-3">
                <input
                    type="checkbox"
                    checked={selected}
                    onChange={onToggleSelect}
                    aria-label={`Select DLQ event ${item.event_id}`}
                    className="mt-1 h-4 w-4 rounded border-zinc-700 bg-zinc-950 text-violet-500 focus:ring-violet-500/60"
                />
                <div className="min-w-0 flex-1 space-y-1.5">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                        <div className="flex flex-wrap items-center gap-1.5 text-xs">
                            <span className="rounded-md bg-violet-500/15 px-2 py-0.5 font-mono text-[11px] font-medium text-violet-300 ring-1 ring-violet-500/30">
                                {item.original_topic}
                            </span>
                            <span className="rounded-md bg-red-500/15 px-2 py-0.5 font-mono text-[11px] font-medium text-red-300 ring-1 ring-red-500/30">
                                {item.error_type}
                            </span>
                            <span className="font-mono text-[11px] text-zinc-500">
                                p{item.dlq_partition}:{item.dlq_offset}
                            </span>
                            <span className="font-mono text-[11px] text-zinc-500">
                                retries:{item.retry_count}
                            </span>
                            {item.replayed_at && (
                                <span
                                    title={`Replayed at ${formatExactDate(item.replayed_at) ?? item.replayed_at}`}
                                    className="rounded-md bg-emerald-500/12 px-2 py-0.5 text-[11px] font-medium text-emerald-300 ring-1 ring-emerald-500/25"
                                >
                                    Previously replayed
                                </span>
                            )}
                            {item.dismissed_at && (
                                <span
                                    title={`Dismissed at ${formatExactDate(item.dismissed_at) ?? item.dismissed_at}`}
                                    className="rounded-md bg-zinc-800 px-2 py-0.5 text-[11px] font-medium text-zinc-300 ring-1 ring-zinc-700"
                                >
                                    Dismissed
                                </span>
                            )}
                            {resultBadge && (
                                <span
                                    className={`rounded-md px-2 py-0.5 text-[11px] font-medium ring-1 ${resultBadge.style}`}
                                >
                                    {resultBadge.label}
                                </span>
                            )}
                        </div>
                        <span
                            title={producedExact ?? undefined}
                            className="shrink-0 font-mono text-[11px] text-zinc-500"
                        >
                            {producedRelative ?? "Unknown time"}
                        </span>
                    </div>

                    <p className="line-clamp-2 text-xs leading-relaxed text-zinc-300">
                        {item.error_message}
                    </p>

                    <div className="flex flex-wrap items-center justify-between gap-2">
                        <button
                            type="button"
                            onClick={onToggleExpand}
                            className="inline-flex items-center gap-1 text-[11px] font-medium text-violet-300 hover:text-violet-200"
                        >
                            {expanded ? (
                                <ChevronDown className="h-3.5 w-3.5" />
                            ) : (
                                <ChevronRight className="h-3.5 w-3.5" />
                            )}
                            {expanded ? "Hide details" : "Inspect payload & error"}
                        </button>

                        {!resolved && (
                            <button
                                type="button"
                                disabled={dismissing}
                                onClick={onDismissSingle}
                                className="inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-[11px] font-medium text-zinc-400 transition hover:bg-zinc-800 hover:text-zinc-200 disabled:opacity-50"
                            >
                                <Archive className="h-3 w-3" />
                                Dismiss
                            </button>
                        )}
                    </div>
                </div>
            </div>

            {expanded && (
                <div className="space-y-2.5 border-t border-zinc-800/80 bg-zinc-950/70 px-4 py-3 text-xs">
                    <div className="flex flex-wrap gap-x-4 gap-y-1 font-mono text-[11px] text-zinc-400">
                        <span>event_id: {item.event_id}</span>
                        <span>
                            source p{item.partition}:{item.offset}
                        </span>
                    </div>
                    <div>
                        <div className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-zinc-400">
                            Error Message
                        </div>
                        <pre className="max-h-28 overflow-auto whitespace-pre-wrap break-words rounded-lg border border-zinc-800 bg-zinc-950 p-2.5 font-mono text-[11px] text-red-200">
                            {item.error_message}
                        </pre>
                    </div>
                    <div>
                        <div className="mb-1 flex items-center justify-between text-[11px] font-semibold uppercase tracking-wider text-zinc-400">
                            <span>Payload Preview</span>
                            {item.payload_truncated && (
                                <span className="font-normal normal-case text-amber-300">
                                    Truncated to 500 chars
                                </span>
                            )}
                        </div>
                        <pre className="max-h-40 overflow-auto whitespace-pre-wrap break-words rounded-lg border border-zinc-800 bg-zinc-950 p-2.5 font-mono text-[11px] text-zinc-300">
                            {item.payload_preview || "(empty payload)"}
                        </pre>
                    </div>
                </div>
            )}
        </div>
    );
}

function DlqModalFooter({
    targetLabel,
    selectedCount,
    isBusy,
    hasVisibleItems,
    confirmingReplay,
    submittingMode,
    onDismissSelected,
    onDryRun,
    onStartConfirm,
    onCancelConfirm,
    onConfirmReplay,
}: Readonly<{
    targetLabel: string;
    selectedCount: number;
    isBusy: boolean;
    hasVisibleItems: boolean;
    confirmingReplay: boolean;
    submittingMode: "dry_run" | "replay" | "dismiss" | null;
    onDismissSelected: () => void;
    onDryRun: () => void;
    onStartConfirm: () => void;
    onCancelConfirm: () => void;
    onConfirmReplay: () => void;
}>) {
    const replayButtonLabel =
        selectedCount > 0 ? `Replay Selected (${selectedCount})` : "Replay Batch";

    return (
        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-zinc-800/90 bg-zinc-900/60 px-6 py-4">
            <span className="text-xs text-zinc-400">
                Target: <strong className="text-zinc-200">{targetLabel}</strong>
            </span>

            <div className="flex flex-wrap items-center gap-2">
                {selectedCount > 0 && (
                    <button
                        type="button"
                        disabled={isBusy}
                        onClick={onDismissSelected}
                        className="inline-flex items-center gap-1.5 rounded-xl border border-zinc-700 bg-zinc-900 px-3.5 py-2 text-xs font-medium text-zinc-200 transition hover:bg-zinc-800 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                        {submittingMode === "dismiss" ? (
                            <Loader2 className="h-3.5 w-3.5 animate-spin" />
                        ) : (
                            <Archive className="h-3.5 w-3.5 text-zinc-400" />
                        )}
                        Dismiss ({selectedCount})
                    </button>
                )}

                <button
                    type="button"
                    disabled={isBusy || !hasVisibleItems}
                    onClick={onDryRun}
                    className="inline-flex items-center gap-1.5 rounded-xl border border-zinc-700 bg-zinc-800 px-3.5 py-2 text-xs font-medium text-zinc-100 transition hover:bg-zinc-700 disabled:cursor-not-allowed disabled:opacity-50"
                >
                    {submittingMode === "dry_run" ? (
                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    ) : (
                        <Eye className="h-3.5 w-3.5 text-sky-400" />
                    )}
                    Dry Run
                </button>

                {confirmingReplay ? (
                    <>
                        <button
                            type="button"
                            disabled={isBusy}
                            onClick={onConfirmReplay}
                            className="inline-flex items-center gap-1.5 rounded-xl bg-amber-600 px-3.5 py-2 text-xs font-semibold text-white transition hover:bg-amber-500 disabled:opacity-50"
                        >
                            {submittingMode === "replay" ? (
                                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                            ) : (
                                <RotateCcw className="h-3.5 w-3.5" />
                            )}
                            Confirm Replay ({targetLabel})
                        </button>
                        <button
                            type="button"
                            onClick={onCancelConfirm}
                            className="rounded-xl border border-zinc-700 px-3 py-2 text-xs text-zinc-300 hover:bg-zinc-800"
                        >
                            Cancel
                        </button>
                    </>
                ) : (
                    <button
                        type="button"
                        disabled={isBusy || !hasVisibleItems}
                        onClick={onStartConfirm}
                        className="inline-flex items-center gap-1.5 rounded-xl bg-violet-600 px-3.5 py-2 text-xs font-semibold text-white transition hover:bg-violet-500 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                        <RotateCcw className="h-3.5 w-3.5" />
                        {replayButtonLabel}
                    </button>
                )}
            </div>
        </div>
    );
}

function DlqModalToolbar({
    topicFilter,
    visibleCount,
    selectedCount,
    resolvedCount,
    showResolved,
    loading,
    isBusy,
    disabledSelect,
    onTopicChange,
    onToggleSelectAll,
    onToggleShowResolved,
    onRefresh,
}: Readonly<{
    topicFilter: "" | ReplayableTopic;
    visibleCount: number;
    selectedCount: number;
    resolvedCount: number;
    showResolved: boolean;
    loading: boolean;
    isBusy: boolean;
    disabledSelect: boolean;
    onTopicChange: (next: "" | ReplayableTopic) => void;
    onToggleSelectAll: () => void;
    onToggleShowResolved: () => void;
    onRefresh: () => void;
}>) {
    const allSelected = selectedCount === visibleCount && visibleCount > 0;
    const selectButtonLabel = allSelected
        ? "Clear selection"
        : `Select all (${visibleCount})`;

    return (
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-zinc-800/80 bg-zinc-900/40 px-6 py-3">
            <div className="flex flex-wrap items-center gap-2.5">
                <label htmlFor="dlq-topic-filter" className="text-xs text-zinc-400">
                    Topic
                </label>
                <select
                    id="dlq-topic-filter"
                    value={topicFilter}
                    onChange={(e) => onTopicChange(e.target.value as "" | ReplayableTopic)}
                    disabled={disabledSelect}
                    className="rounded-lg border border-zinc-700/80 bg-zinc-950 px-2.5 py-1.5 text-xs text-zinc-200 focus:border-violet-500 focus:outline-none"
                >
                    {TOPIC_OPTIONS.map((opt) => (
                        <option key={opt.value || "all"} value={opt.value}>
                            {opt.label}
                        </option>
                    ))}
                </select>

                {visibleCount > 0 && (
                    <button
                        type="button"
                        onClick={onToggleSelectAll}
                        className="rounded-lg border border-zinc-800 bg-zinc-900 px-2.5 py-1.5 text-xs text-zinc-300 transition hover:border-zinc-700 hover:text-zinc-100"
                    >
                        {selectButtonLabel}
                    </button>
                )}

                {resolvedCount > 0 && (
                    <label className="inline-flex cursor-pointer items-center gap-1.5 text-xs text-zinc-400 hover:text-zinc-200">
                        <input
                            type="checkbox"
                            checked={showResolved}
                            onChange={onToggleShowResolved}
                            className="h-3.5 w-3.5 rounded border-zinc-700 bg-zinc-950 text-violet-500 focus:ring-violet-500/60"
                        />
                        Show resolved ({resolvedCount})
                    </label>
                )}
            </div>

            <button
                type="button"
                onClick={onRefresh}
                disabled={isBusy}
                className="inline-flex items-center gap-1.5 rounded-lg border border-zinc-800 bg-zinc-900 px-3 py-1.5 text-xs font-medium text-zinc-200 transition hover:border-zinc-700 hover:bg-zinc-800 disabled:opacity-50"
            >
                <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
                Refresh
            </button>
        </div>
    );
}

function DlqEmptyState({ resolvedCount }: Readonly<{ resolvedCount: number }>) {
    const title =
        resolvedCount > 0
            ? "All recent DLQ entries are resolved"
            : "No matching DLQ messages";
    const subtitle =
        resolvedCount > 0
            ? `Enable "Show resolved (${resolvedCount})" above to view replayed or dismissed items.`
            : "The dead-letter queue has no recent failures for this filter.";

    return (
        <div className="rounded-xl border border-dashed border-zinc-800 bg-zinc-900/30 py-12 text-center">
            <CheckCircle2 className="mx-auto mb-2 h-6 w-6 text-emerald-400" />
            <p className="text-sm font-medium text-zinc-200">{title}</p>
            <p className="mt-1 text-xs text-zinc-500">{subtitle}</p>
        </div>
    );
}

function DlqInspectorModalContent({
    onClose,
    onReplayed,
}: Readonly<{
    onClose: () => void;
    onReplayed?: () => void;
}>) {
    const [topicFilter, setTopicFilter] = useState<"" | ReplayableTopic>("");
    const [showResolved, setShowResolved] = useState(false);
    const [reloadToken, setReloadToken] = useState(0);
    const [data, setData] = useState<DlqInspectResponse | null>(null);
    const [loading, setLoading] = useState(true);
    const [errorMessage, setErrorMessage] = useState<string | null>(null);
    const [selectedIds, setSelectedIds] = useState<string[]>([]);
    const [expandedIds, setExpandedIds] = useState<string[]>([]);
    const [confirmingReplay, setConfirmingReplay] = useState(false);
    const [submittingMode, setSubmittingMode] = useState<
        "dry_run" | "replay" | "dismiss" | null
    >(null);
    const [replaySummary, setReplaySummary] = useState<DlqReplayResponse | null>(null);
    const [dismissFeedback, setDismissFeedback] = useState<string | null>(null);

    useEffect(() => {
        let active = true;
        vektrynApi
            .listDlqMessages({
                limit: 25,
                original_topic: topicFilter || undefined,
            })
            .then((res) => {
                if (!active) return;
                setData(res);
                setErrorMessage(null);
            })
            .catch((err) => {
                if (!active) return;
                setErrorMessage(formatDlqError(err));
            })
            .finally(() => {
                if (active) setLoading(false);
            });

        return () => {
            active = false;
        };
    }, [topicFilter, reloadToken]);

    const allItems = data?.items ?? [];
    const resolvedCount = allItems.filter(isDlqItemResolved).length;
    const visibleItems = showResolved
        ? allItems
        : allItems.filter((item) => !isDlqItemResolved(item));
    const visibleIds = visibleItems.map((item) => item.event_id);
    const resultsByEventId = new Map<string, DlqReplayItemResult>(
        (replaySummary?.items ?? []).map((entry) => [entry.event_id, entry]),
    );

    function handleTopicChange(nextTopic: "" | ReplayableTopic) {
        setTopicFilter(nextTopic);
        setSelectedIds([]);
        setConfirmingReplay(false);
        setReplaySummary(null);
        setDismissFeedback(null);
        setLoading(true);
    }

    function handleToggleShowResolved() {
        setShowResolved((prev) => !prev);
        setSelectedIds([]);
        setConfirmingReplay(false);
    }

    function handleRefresh() {
        setConfirmingReplay(false);
        setDismissFeedback(null);
        setLoading(true);
        setReloadToken((prev) => prev + 1);
    }

    function toggleSelect(eventId: string) {
        setConfirmingReplay(false);
        setSelectedIds((prev) =>
            prev.includes(eventId) ? prev.filter((id) => id !== eventId) : [...prev, eventId],
        );
    }

    function toggleSelectAll() {
        setConfirmingReplay(false);
        if (selectedIds.length === visibleIds.length && visibleIds.length > 0) {
            setSelectedIds([]);
        } else {
            setSelectedIds(visibleIds);
        }
    }

    function toggleExpand(eventId: string) {
        setExpandedIds((prev) =>
            prev.includes(eventId) ? prev.filter((id) => id !== eventId) : [...prev, eventId],
        );
    }

    async function runReplay(dryRun: boolean) {
        setErrorMessage(null);
        setDismissFeedback(null);
        setConfirmingReplay(false);
        setSubmittingMode(dryRun ? "dry_run" : "replay");

        const payload: DlqReplayRequest = {
            dry_run: dryRun,
            original_topic: topicFilter || undefined,
        };
        if (selectedIds.length > 0) {
            payload.event_ids = selectedIds;
        } else {
            payload.limit = DEFAULT_BATCH_LIMIT;
        }

        try {
            const res = await vektrynApi.replayDlqMessages(payload);
            setReplaySummary(res);
            if (!dryRun && res.replayed_count > 0) {
                setSelectedIds([]);
                setLoading(true);
                setReloadToken((prev) => prev + 1);
                onReplayed?.();
            }
        } catch (err) {
            setErrorMessage(formatDlqError(err));
        } finally {
            setSubmittingMode(null);
        }
    }

    async function runDismiss(eventIds: string[]) {
        if (eventIds.length === 0) return;
        setErrorMessage(null);
        setReplaySummary(null);
        setConfirmingReplay(false);
        setSubmittingMode("dismiss");

        try {
            const res = await vektrynApi.dismissDlqMessages(eventIds);
            setDismissFeedback(
                `Dismissed ${res.dismissed_count} DLQ ${res.dismissed_count === 1 ? "entry" : "entries"} (audit trail retained in Kafka for 7 days).`,
            );
            setSelectedIds((prev) => prev.filter((id) => !eventIds.includes(id)));
            setLoading(true);
            setReloadToken((prev) => prev + 1);
            onReplayed?.();
        } catch (err) {
            setErrorMessage(formatDlqError(err));
        } finally {
            setSubmittingMode(null);
        }
    }

    const targetLabel =
        selectedIds.length > 0
            ? `${selectedIds.length} selected`
            : `up to ${DEFAULT_BATCH_LIMIT} newest unresolved`;
    const isBusy = submittingMode !== null || loading;
    const hasVisibleItems = visibleItems.length > 0;

    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
            <button
                type="button"
                aria-label="Close DLQ inspector"
                onClick={onClose}
                className="fixed inset-0 cursor-default bg-black/75 backdrop-blur-xs"
            />
            <dialog
                open
                aria-modal="true"
                aria-labelledby="dlq-modal-title"
                className="relative z-10 m-0 flex max-h-[85vh] w-full max-w-3xl flex-col overflow-hidden rounded-2xl border border-zinc-800 bg-zinc-950 p-0 text-zinc-100 shadow-2xl"
            >
                <div className="flex items-start justify-between gap-4 border-b border-zinc-800/90 px-6 py-4">
                    <div className="space-y-1">
                        <div className="flex items-center gap-2">
                            <ShieldAlert className="h-4 w-4 text-red-400" />
                            <h2 id="dlq-modal-title" className="text-base font-semibold">
                                Dead-Letter Queue Inspector
                            </h2>
                            {data && (
                                <span className="rounded-md bg-zinc-800 px-2 py-0.5 font-mono text-[11px] text-zinc-300">
                                    {visibleItems.length} active · {data.total_count} total
                                </span>
                            )}
                        </div>
                        <p className="text-xs text-zinc-400">
                            Non-destructive peek of recent <code className="font-mono">jobs.dlq</code>{" "}
                            failures with dry-run preview, replay, and dismissal markers.
                        </p>
                    </div>
                    <button
                        type="button"
                        onClick={onClose}
                        aria-label="Close modal"
                        className="rounded-lg p-1.5 text-zinc-400 transition hover:bg-zinc-900 hover:text-zinc-100"
                    >
                        <X className="h-4 w-4" />
                    </button>
                </div>

                <DlqModalToolbar
                    topicFilter={topicFilter}
                    visibleCount={visibleIds.length}
                    selectedCount={selectedIds.length}
                    resolvedCount={resolvedCount}
                    showResolved={showResolved}
                    loading={loading}
                    isBusy={isBusy}
                    disabledSelect={submittingMode !== null}
                    onTopicChange={handleTopicChange}
                    onToggleSelectAll={toggleSelectAll}
                    onToggleShowResolved={handleToggleShowResolved}
                    onRefresh={handleRefresh}
                />

                <div className="flex-1 space-y-3 overflow-y-auto px-6 py-4">
                    {errorMessage && (
                        <div
                            role="alert"
                            className="flex items-start gap-2.5 rounded-xl border border-red-500/30 bg-red-950/30 px-3.5 py-2.5 text-xs text-red-200"
                        >
                            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-red-400" />
                            <span>{errorMessage}</span>
                        </div>
                    )}

                    {dismissFeedback && (
                        <div className="flex flex-wrap items-center gap-2 rounded-xl border border-emerald-500/30 bg-emerald-950/25 px-3.5 py-2.5 text-xs text-emerald-100">
                            <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-300" />
                            <span>{dismissFeedback}</span>
                        </div>
                    )}

                    {replaySummary && (
                        <div className="flex flex-wrap items-center gap-2 rounded-xl border border-violet-500/30 bg-violet-950/25 px-3.5 py-2.5 text-xs text-violet-100">
                            <CheckCircle2 className="h-4 w-4 shrink-0 text-violet-300" />
                            <span>
                                {replaySummary.dry_run
                                    ? `Dry run complete: ${replaySummary.matched_count} would replay, ${replaySummary.skipped_count} skipped.`
                                    : `Replay complete: ${replaySummary.replayed_count} replayed, ${replaySummary.skipped_count} skipped, ${replaySummary.failed_count} failed.`}
                            </span>
                        </div>
                    )}

                    {loading && (
                        <div className="flex items-center justify-center gap-2 py-12 text-xs text-zinc-400">
                            <Loader2 className="h-4 w-4 animate-spin text-violet-400" />
                            Peeking recent DLQ messages...
                        </div>
                    )}

                    {!loading && !hasVisibleItems && !errorMessage && (
                        <DlqEmptyState resolvedCount={resolvedCount} />
                    )}

                    {!loading &&
                        hasVisibleItems &&
                        visibleItems.map((item) => (
                            <DlqMessageRow
                                key={`${item.dlq_partition}-${item.dlq_offset}-${item.event_id}`}
                                item={item}
                                selected={selectedIds.includes(item.event_id)}
                                expanded={expandedIds.includes(item.event_id)}
                                replayResult={resultsByEventId.get(item.event_id)}
                                dismissing={submittingMode !== null}
                                onToggleSelect={() => toggleSelect(item.event_id)}
                                onToggleExpand={() => toggleExpand(item.event_id)}
                                onDismissSingle={() => void runDismiss([item.event_id])}
                            />
                        ))}
                </div>

                <DlqModalFooter
                    targetLabel={targetLabel}
                    selectedCount={selectedIds.length}
                    isBusy={isBusy}
                    hasVisibleItems={hasVisibleItems}
                    confirmingReplay={confirmingReplay}
                    submittingMode={submittingMode}
                    onDismissSelected={() => void runDismiss(selectedIds)}
                    onDryRun={() => void runReplay(true)}
                    onStartConfirm={() => setConfirmingReplay(true)}
                    onCancelConfirm={() => setConfirmingReplay(false)}
                    onConfirmReplay={() => void runReplay(false)}
                />
            </dialog>
        </div>
    );
}

export function DlqInspectorModal({
    open,
    onClose,
    onReplayed,
}: Readonly<DlqInspectorModalProps>) {
    useEffect(() => {
        if (!open) return;
        function handleKeyDown(event: KeyboardEvent) {
            if (event.key === "Escape") {
                onClose();
            }
        }
        window.addEventListener("keydown", handleKeyDown);
        return () => window.removeEventListener("keydown", handleKeyDown);
    }, [open, onClose]);

    if (!open || typeof document === "undefined") {
        return null;
    }

    return createPortal(
        <DlqInspectorModalContent onClose={onClose} onReplayed={onReplayed} />,
        document.body,
    );
}
