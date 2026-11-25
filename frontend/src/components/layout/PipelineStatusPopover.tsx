import {
    Activity,
    AlertTriangle,
    CheckCircle2,
    Database,
    Play,
    RefreshCw,
    ShieldAlert,
} from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { vektrynApi } from "../../api/client";
import type {
    CollectorSourceLog,
    DlqHealthStatus,
    PipelineOverallStatus,
    PipelineStatusResponse,
} from "../../types/models";
import { formatAtsSource, formatExactDate, formatRelativeTime } from "../../utils/format";
import { Tooltip } from "../ui/Tooltip";

const STATUS_POLL_INTERVAL_MS = 60_000;

function statusTheme(status: PipelineOverallStatus | null): {
    dot: string;
    pill: string;
    badge: string;
    label: string;
} {
    if (status === "healthy") {
        return {
            dot: "bg-emerald-400",
            pill: "bg-zinc-900/80 text-zinc-200 ring-zinc-800 hover:border-zinc-700 hover:bg-zinc-900",
            badge: "bg-emerald-500/15 text-emerald-300 ring-emerald-500/30",
            label: "Healthy",
        };
    }
    if (status === "degraded") {
        return {
            dot: "bg-red-400",
            pill: "bg-red-950/35 text-red-200 ring-red-500/35 hover:bg-red-950/50",
            badge: "bg-red-500/15 text-red-300 ring-red-500/35",
            label: "Degraded",
        };
    }
    if (status === "warning") {
        return {
            dot: "bg-amber-400",
            pill: "bg-amber-950/25 text-amber-200 ring-amber-500/30 hover:bg-amber-950/40",
            badge: "bg-amber-500/15 text-amber-300 ring-amber-500/35",
            label: "Attention",
        };
    }
    return {
        dot: "bg-zinc-500",
        pill: "bg-zinc-900/80 text-zinc-400 ring-zinc-800",
        badge: "bg-zinc-800 text-zinc-400 ring-zinc-700",
        label: "Checking",
    };
}

function formatDurationMs(ms: number): string {
    if (ms < 1000) return `${ms}ms`;
    return `${(ms / 1000).toFixed(1)}s`;
}

function formatCooldown(seconds: number): string {
    if (seconds < 60) return `${seconds}s`;
    const mins = Math.ceil(seconds / 60);
    return `${mins}m`;
}

function getSyncButtonLabel(syncing: boolean, cooldownRemaining: number): string {
    if (syncing) {
        return "Triggering Collectors...";
    }
    if (cooldownRemaining > 0) {
        return `Sync Cooldown (${formatCooldown(cooldownRemaining)})`;
    }
    return "Sync Collectors";
}

function DlqBadge({
    status,
    recent24h,
    total,
}: Readonly<{
    status: DlqHealthStatus;
    recent24h: number | null;
    total: number | null;
}>) {
    if (status === "unavailable") {
        return (
            <span className="inline-flex items-center gap-1.5 rounded-lg bg-amber-500/12 px-2.5 py-1 text-xs font-medium text-amber-300 ring-1 ring-amber-500/30">
                <AlertTriangle className="h-3.5 w-3.5" />
                Broker unavailable
            </span>
        );
    }
    if ((recent24h ?? 0) > 0) {
        return (
            <span className="inline-flex items-center gap-1.5 rounded-lg bg-red-500/15 px-2.5 py-1 text-xs font-medium text-red-300 ring-1 ring-red-500/35">
                <ShieldAlert className="h-3.5 w-3.5" />
                {recent24h} failed (24h)
                {total !== null && total > (recent24h ?? 0) ? ` · ${total} total` : ""}
            </span>
        );
    }
    return (
        <span className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-500/12 px-2.5 py-1 text-xs font-medium text-emerald-300 ring-1 ring-emerald-500/30">
            <CheckCircle2 className="h-3.5 w-3.5" />0 failures (24h)
            {total !== null && total > 0 ? ` · ${total} archived` : ""}
        </span>
    );
}

function SourceBreakdownList({ sources }: Readonly<{ sources: ReadonlyArray<CollectorSourceLog> }>) {
    if (sources.length === 0) {
        return (
            <p className="rounded-xl border border-zinc-800/80 bg-zinc-950/50 px-3 py-2.5 text-xs text-zinc-500">
                No collector runs recorded yet.
            </p>
        );
    }

    return (
        <div className="max-h-44 space-y-1.5 overflow-y-auto pr-1">
            {sources.map((src) => (
                <div
                    key={src.source}
                    className="flex items-center justify-between gap-2 rounded-lg border border-zinc-800/70 bg-zinc-950/60 px-2.5 py-1.5 text-xs"
                >
                    <div className="min-w-0">
                        <span className="font-medium text-zinc-200">
                            {formatAtsSource(src.source)}
                        </span>
                        <span className="ml-2 font-mono text-[11px] text-zinc-500">
                            {formatDurationMs(src.duration_ms)}
                        </span>
                    </div>
                    <div className="flex shrink-0 items-center gap-2 font-mono text-[11px] tabular-nums">
                        <span className="text-emerald-300">+{src.ingested_count}</span>
                        <span className="text-zinc-400">{src.deduped_count} dup</span>
                        {src.error_count > 0 && (
                            <span className="text-red-300">{src.error_count} err</span>
                        )}
                    </div>
                </div>
            ))}
        </div>
    );
}

export function PipelineStatusPopover({ isStaff }: Readonly<{ isStaff: boolean }>) {
    const [open, setOpen] = useState(false);
    const [data, setData] = useState<PipelineStatusResponse | null>(null);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [syncing, setSyncing] = useState(false);
    const [syncFeedback, setSyncFeedback] = useState<string | null>(null);
    const containerRef = useRef<HTMLDivElement | null>(null);

    const fetchStatus = useCallback(async () => {
        setLoading(true);
        try {
            const res = await vektrynApi.getSystemStatus();
            setData(res);
            setError(null);
        } catch (err) {
            setError(err instanceof Error ? err.message : "Failed to load pipeline telemetry");
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => {
        let cancelled = false;
        async function loadStatus() {
            try {
                const res = await vektrynApi.getSystemStatus();
                if (!cancelled) {
                    setData(res);
                    setError(null);
                }
            } catch (err) {
                if (!cancelled) {
                    setError(
                        err instanceof Error ? err.message : "Failed to load pipeline telemetry",
                    );
                }
            }
        }
        void loadStatus();
        const intervalId = window.setInterval(() => {
            if (!document.hidden) {
                void loadStatus();
            }
        }, STATUS_POLL_INTERVAL_MS);
        return () => {
            cancelled = true;
            window.clearInterval(intervalId);
        };
    }, []);

    useEffect(() => {
        if (!open) return;
        const handleClickOutside = (event: MouseEvent) => {
            if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
                setOpen(false);
            }
        };
        const handleKeyDown = (event: KeyboardEvent) => {
            if (event.key === "Escape") setOpen(false);
        };
        document.addEventListener("mousedown", handleClickOutside);
        window.addEventListener("keydown", handleKeyDown);
        return () => {
            document.removeEventListener("mousedown", handleClickOutside);
            window.removeEventListener("keydown", handleKeyDown);
        };
    }, [open]);

    async function handleTriggerSync() {
        setSyncing(true);
        setSyncFeedback(null);
        try {
            const res = await vektrynApi.triggerCollectorSync();
            setSyncFeedback(`Collector sync queued (${res.job_name}).`);
            void fetchStatus();
        } catch (err) {
            setSyncFeedback(
                err instanceof Error ? err.message : "Failed to trigger collector sync",
            );
        } finally {
            setSyncing(false);
        }
    }

    const theme = statusTheme(data?.overall_status ?? null);
    const lastSyncRelative = formatRelativeTime(data?.last_collect_at ?? null);
    const lastSyncExact = formatExactDate(data?.last_collect_at ?? null);
    const pillSubtitle = lastSyncRelative ? `· ${lastSyncRelative}` : "· Idle";
    const cooldownRemaining = data?.collect_trigger.cooldown_remaining_seconds ?? 0;
    const canTrigger = isStaff || Boolean(data?.collect_trigger.can_trigger);

    return (
        <div ref={containerRef} className="relative">
            <Tooltip content="Inspect collector sync telemetry, job backlog, and DLQ health" side="bottom">
                <button
                    type="button"
                    aria-expanded={open}
                    aria-haspopup="dialog"
                    onClick={() => {
                        const nextOpen = !open;
                        setOpen(nextOpen);
                        if (nextOpen) void fetchStatus();
                    }}
                    className={`inline-flex items-center gap-2 rounded-full px-3.5 py-1.5 text-xs font-medium ring-1 ring-inset transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-500/70 ${theme.pill}`}
                >
                    <span className={`h-2 w-2 rounded-full ${theme.dot}`} />
                    <Activity className="h-3.5 w-3.5 opacity-80" />
                    <span>Pipeline {data ? pillSubtitle : ""}</span>
                </button>
            </Tooltip>

            {open && (
                <dialog
                    open
                    aria-label="Pipeline telemetry"
                    className="absolute right-0 left-auto z-40 m-0 mt-2.5 w-[340px] rounded-2xl border border-zinc-800 bg-zinc-950/95 p-4 text-left text-zinc-100 shadow-2xl shadow-black/70 backdrop-blur-md sm:w-[400px]"
                >
                    <div className="flex items-center justify-between gap-2 border-b border-zinc-800/80 pb-3">
                        <div className="flex items-center gap-2">
                            <Database className="h-4 w-4 text-violet-400" />
                            <h2 className="text-sm font-semibold text-zinc-100">
                                Pipeline Status
                            </h2>
                            <span
                                className={`rounded-md px-2 py-0.5 text-[11px] font-medium ring-1 ring-inset ${theme.badge}`}
                            >
                                {theme.label}
                            </span>
                        </div>
                        <button
                            type="button"
                            onClick={() => void fetchStatus()}
                            disabled={loading}
                            aria-label="Refresh pipeline status"
                            className="rounded-lg p-1.5 text-zinc-400 transition hover:bg-zinc-800 hover:text-zinc-100 disabled:opacity-50"
                        >
                            <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
                        </button>
                    </div>

                    {error && (
                        <div className="mt-3 rounded-xl border border-red-500/30 bg-red-950/25 px-3 py-2 text-xs text-red-300">
                            {error}
                        </div>
                    )}

                    {data && (
                        <div className="mt-3.5 space-y-4">
                            <div className="space-y-2">
                                <div className="flex items-center justify-between text-xs">
                                    <span className="font-medium text-zinc-400">
                                        Last Collector Sync
                                    </span>
                                    <Tooltip content={lastSyncExact ?? "No sync recorded yet"}>
                                        <span className="font-mono text-zinc-200">
                                            {lastSyncRelative ?? "Never"}
                                        </span>
                                    </Tooltip>
                                </div>
                                <div className="grid grid-cols-4 gap-2 text-center">
                                    <div className="rounded-xl border border-zinc-800/80 bg-zinc-900/60 px-2 py-2">
                                        <div className="font-mono text-sm font-semibold tabular-nums text-zinc-100">
                                            {data.latest_run_totals.fetched_count}
                                        </div>
                                        <div className="text-[10px] uppercase tracking-wider text-zinc-500">
                                            Fetched
                                        </div>
                                    </div>
                                    <div className="rounded-xl border border-zinc-800/80 bg-zinc-900/60 px-2 py-2">
                                        <div className="font-mono text-sm font-semibold tabular-nums text-emerald-300">
                                            {data.latest_run_totals.ingested_count}
                                        </div>
                                        <div className="text-[10px] uppercase tracking-wider text-zinc-500">
                                            Ingested
                                        </div>
                                    </div>
                                    <div className="rounded-xl border border-zinc-800/80 bg-zinc-900/60 px-2 py-2">
                                        <div className="font-mono text-sm font-semibold tabular-nums text-zinc-300">
                                            {data.latest_run_totals.deduped_count}
                                        </div>
                                        <div className="text-[10px] uppercase tracking-wider text-zinc-500">
                                            Deduped
                                        </div>
                                    </div>
                                    <div className="rounded-xl border border-zinc-800/80 bg-zinc-900/60 px-2 py-2">
                                        <div
                                            className={`font-mono text-sm font-semibold tabular-nums ${
                                                data.latest_run_totals.error_count > 0
                                                    ? "text-red-300"
                                                    : "text-zinc-400"
                                            }`}
                                        >
                                            {data.latest_run_totals.error_count}
                                        </div>
                                        <div className="text-[10px] uppercase tracking-wider text-zinc-500">
                                            Errors
                                        </div>
                                    </div>
                                </div>
                            </div>

                            <div className="grid grid-cols-2 gap-2 text-xs">
                                <div className="rounded-xl border border-zinc-800/80 bg-zinc-900/50 px-3 py-2">
                                    <div className="text-[11px] text-zinc-400">AI Scored / Active</div>
                                    <div className="mt-0.5 font-mono text-sm font-semibold tabular-nums text-zinc-100">
                                        {data.jobs.ai_scored_count} / {data.jobs.active_count}
                                    </div>
                                    <div className="text-[11px] text-zinc-500">
                                        {data.jobs.unscored_active_count} unscored
                                        {data.jobs.pending_match_count > 0
                                            ? ` · ${data.jobs.pending_match_count} unmatched`
                                            : ""}
                                    </div>
                                </div>
                                <div className="rounded-xl border border-zinc-800/80 bg-zinc-900/50 px-3 py-2">
                                    <div className="text-[11px] text-zinc-400">Stack Rollup</div>
                                    <div className="mt-0.5 font-mono text-sm font-semibold tabular-nums text-zinc-100">
                                        {data.rollup.latest_bucket_date ?? "—"}
                                    </div>
                                    <div className="text-[11px] text-zinc-500">
                                        {formatRelativeTime(data.rollup.latest_updated_at) ??
                                            "No rollup yet"}
                                    </div>
                                </div>
                            </div>

                            <div className="flex items-center justify-between gap-2 rounded-xl border border-zinc-800/80 bg-zinc-900/50 px-3 py-2">
                                <span className="text-xs font-medium text-zinc-300">
                                    Dead-Letter Queue
                                </span>
                                <DlqBadge
                                    status={data.dlq.status}
                                    recent24h={data.dlq.recent_24h_count}
                                    total={data.dlq.total_count}
                                />
                            </div>

                            <div className="space-y-1.5">
                                <div className="text-[11px] font-medium uppercase tracking-wider text-zinc-400">
                                    Latest Per-Source Runs ({data.sources.length})
                                </div>
                                <SourceBreakdownList sources={data.sources} />
                            </div>

                            {canTrigger && (
                                <div className="space-y-2 border-t border-zinc-800/80 pt-3">
                                    <button
                                        type="button"
                                        disabled={syncing || cooldownRemaining > 0}
                                        onClick={() => void handleTriggerSync()}
                                        className="inline-flex w-full items-center justify-center gap-2 rounded-xl bg-violet-600 px-3.5 py-2 text-xs font-medium text-white transition hover:bg-violet-500 disabled:cursor-not-allowed disabled:opacity-50"
                                    >
                                        <Play className="h-3.5 w-3.5" />
                                        {getSyncButtonLabel(syncing, cooldownRemaining)}
                                    </button>
                                    {syncFeedback && (
                                        <p className="text-center text-xs text-zinc-300">
                                            {syncFeedback}
                                        </p>
                                    )}
                                </div>
                            )}
                        </div>
                    )}
                </dialog>
            )}
        </div>
    );
}
