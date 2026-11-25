import {
    Activity,
    AlertTriangle,
    CheckCircle2,
    Database,
    Loader2,
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

const IDLE_POLL_INTERVAL_MS = 60_000;
const RUNNING_POLL_INTERVAL_MS = 5_000;

function statusTheme(
    status: PipelineOverallStatus | null,
    isRunning: boolean,
): {
    dot: string;
    pill: string;
    badge: string;
    label: string;
} {
    if (isRunning) {
        return {
            dot: "bg-violet-400",
            pill: "bg-violet-950/35 text-violet-200 ring-violet-500/35 hover:bg-violet-950/50",
            badge: "bg-violet-500/15 text-violet-300 ring-violet-500/35",
            label: "Syncing",
        };
    }
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

function formatMinutesSeconds(totalSeconds: number): string {
    const safe = Math.max(0, Math.floor(totalSeconds));
    if (safe < 60) return `${safe}s`;
    const mins = Math.floor(safe / 60);
    const secs = safe % 60;
    return `${mins}m ${String(secs).padStart(2, "0")}s`;
}

function getPillSubtitle(isBusy: boolean, lastSyncRelative: string | null): string {
    if (isBusy) return "· Syncing...";
    if (lastSyncRelative) return `· ${lastSyncRelative}`;
    return "· Idle";
}

function getSyncButtonLabel(
    triggering: boolean,
    isRunning: boolean,
    elapsedRunSeconds: number,
    cooldownRemaining: number,
): string {
    if (triggering) {
        return "Starting Collector Sync...";
    }
    if (isRunning) {
        return elapsedRunSeconds > 0
            ? `Syncing Collectors... (${formatMinutesSeconds(elapsedRunSeconds)})`
            : "Syncing Collectors...";
    }
    if (cooldownRemaining > 0) {
        return `Sync Cooldown (${formatMinutesSeconds(cooldownRemaining)})`;
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
                    <div className="min-w-0 truncate">
                        <span className="font-medium text-zinc-200">
                            {formatAtsSource(src.source)}
                        </span>
                        <span className="ml-2 font-mono text-[11px] text-zinc-500">
                            {formatDurationMs(src.duration_ms)}
                        </span>
                    </div>
                    <div className="flex shrink-0 items-center gap-2 font-mono text-[11px] tabular-nums">
                        <span className="text-zinc-300" title="Raw postings fetched">
                            {src.fetched_count} fetched
                        </span>
                        <span className="text-emerald-300" title="New postings ingested">
                            +{src.ingested_count}
                        </span>
                        <span className="text-zinc-400" title="Deduplicated postings">
                            {src.deduped_count} dup
                        </span>
                        {src.error_count > 0 && (
                            <span className="text-red-300" title="Fetch or ingest errors">
                                {src.error_count} err
                            </span>
                        )}
                    </div>
                </div>
            ))}
        </div>
    );
}

function computeElapsedRunSeconds(startedAtIso: string | null | undefined, nowMs: number): number {
    if (!startedAtIso) return 0;
    const parsed = Date.parse(startedAtIso);
    if (Number.isNaN(parsed)) return 0;
    return Math.max(0, Math.floor((nowMs - parsed) / 1000));
}

function computeLiveCooldown(
    serverSeconds: number,
    fetchedAtMs: number | null,
    nowMs: number,
): number {
    if (serverSeconds <= 0 || fetchedAtMs === null) return 0;
    const elapsedSinceFetch = Math.max(0, Math.floor((nowMs - fetchedAtMs) / 1000));
    return Math.max(0, serverSeconds - elapsedSinceFetch);
}

export function PipelineStatusPopover({ isStaff }: Readonly<{ isStaff: boolean }>) {
    const [open, setOpen] = useState(false);
    const [data, setData] = useState<PipelineStatusResponse | null>(null);
    const [fetchedAtMs, setFetchedAtMs] = useState<number | null>(null);
    const [nowMs, setNowMs] = useState(() => Date.now());
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [triggering, setTriggering] = useState(false);
    const [syncFeedback, setSyncFeedback] = useState<string | null>(null);
    const containerRef = useRef<HTMLDivElement | null>(null);
    const wasRunningRef = useRef(false);

    const applyStatusResponse = useCallback((res: PipelineStatusResponse) => {
        const now = Date.now();
        const nextRunning = Boolean(res.collect_trigger.is_running);
        if (wasRunningRef.current && !nextRunning) {
            setSyncFeedback("Collector sync complete — telemetry updated.");
        }
        wasRunningRef.current = nextRunning;
        setData(res);
        setFetchedAtMs(now);
        setNowMs(now);
        setError(null);
    }, []);

    const fetchStatus = useCallback(async () => {
        setLoading(true);
        try {
            const res = await vektrynApi.getSystemStatus();
            applyStatusResponse(res);
        } catch (err) {
            setError(err instanceof Error ? err.message : "Failed to load pipeline telemetry");
        } finally {
            setLoading(false);
        }
    }, [applyStatusResponse]);

    const isRunning = Boolean(data?.collect_trigger.is_running);
    const serverCooldown = data?.collect_trigger.cooldown_remaining_seconds ?? 0;
    const pollIntervalMs = isRunning ? RUNNING_POLL_INTERVAL_MS : IDLE_POLL_INTERVAL_MS;

    useEffect(() => {
        let cancelled = false;
        async function loadStatus() {
            try {
                const res = await vektrynApi.getSystemStatus();
                if (!cancelled) {
                    applyStatusResponse(res);
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
        }, pollIntervalMs);
        return () => {
            cancelled = true;
            window.clearInterval(intervalId);
        };
    }, [applyStatusResponse, pollIntervalMs]);

    const shouldTickClock = isRunning || serverCooldown > 0;
    useEffect(() => {
        if (!shouldTickClock) return;
        const tickId = window.setInterval(() => {
            setNowMs(Date.now());
        }, 1000);
        return () => window.clearInterval(tickId);
    }, [shouldTickClock]);

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
        setTriggering(true);
        setSyncFeedback(null);
        try {
            await vektrynApi.triggerCollectorSync();
            wasRunningRef.current = true;
            await fetchStatus();
        } catch (err) {
            setSyncFeedback(
                err instanceof Error ? err.message : "Failed to trigger collector sync",
            );
        } finally {
            setTriggering(false);
        }
    }

    const isSyncBusy = triggering || isRunning;
    const theme = statusTheme(data?.overall_status ?? null, isSyncBusy);
    const lastSyncRelative = formatRelativeTime(data?.last_collect_at ?? null);
    const lastSyncExact = formatExactDate(data?.last_collect_at ?? null);
    const pillSubtitle = getPillSubtitle(isSyncBusy, lastSyncRelative);
    const elapsedRunSeconds = computeElapsedRunSeconds(
        data?.collect_trigger.running_started_at,
        nowMs,
    );
    const cooldownRemaining = computeLiveCooldown(serverCooldown, fetchedAtMs, nowMs);
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
                    {isSyncBusy ? (
                        <Loader2 className="h-3.5 w-3.5 animate-spin text-violet-300" />
                    ) : (
                        <>
                            <span className={`h-2 w-2 rounded-full ${theme.dot}`} />
                            <Activity className="h-3.5 w-3.5 opacity-80" />
                        </>
                    )}
                    <span>Pipeline {data || isSyncBusy ? pillSubtitle : ""}</span>
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
                                    <div className="text-[11px] text-zinc-400">
                                        AI Scored / Active
                                    </div>
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
                                        disabled={isSyncBusy || cooldownRemaining > 0}
                                        onClick={() => void handleTriggerSync()}
                                        className="inline-flex w-full items-center justify-center gap-2 rounded-xl bg-violet-600 px-3.5 py-2 text-xs font-medium text-white transition hover:bg-violet-500 disabled:cursor-not-allowed disabled:opacity-50"
                                    >
                                        {isSyncBusy ? (
                                            <Loader2 className="h-3.5 w-3.5 animate-spin" />
                                        ) : (
                                            <Play className="h-3.5 w-3.5" />
                                        )}
                                        {getSyncButtonLabel(
                                            triggering,
                                            isRunning,
                                            elapsedRunSeconds,
                                            cooldownRemaining,
                                        )}
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
