import {
    ArrowUpDown,
    Banknote,
    Bell,
    BookmarkCheck,
    BookmarkPlus,
    Building2,
    CheckCircle2,
    ChevronDown,
    Clock,
    ExternalLink,
    Filter,
    Loader2,
    Mail,
    MapPin,
    Plus,
    RefreshCw,
    RotateCcw,
    Search,
    SlidersHorizontal,
    Sparkles,
    X,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { fetchAllPagesWithCount, vektrynApi } from "../../api/client";
import type {
    HybridSearchMode,
    JobPostingSummary,
    ManualJobImportResponse,
    MatchScore,
    ResumeProfile,
} from "../../types/models";
import {
    DEFAULT_MIN_ALERT_SCORE,
    formatApplyLinkLabel,
    formatApplyLinkTooltip,
    formatAtsSource,
    formatContractType,
    formatExactDate,
    formatRelativeTime,
    formatSalaryRange,
    formatSeniority,
    formatVectorSimilarity,
    isAlertMatch,
    isMailtoUrl,
    scoreVisualTheme,
} from "../../utils/format";
import {
    clearPendingImport,
    loadPendingImport,
    PENDING_IMPORT_STORAGE_KEY,
    savePendingImport,
} from "../../utils/pendingImportStorage";
import {
    countActiveMetadataFilters,
    EMPTY_METADATA_FILTERS,
    type RadarMetadataFilters,
} from "../../utils/radarFilters";
import { PaginationBar } from "../ui/PaginationBar";
import { Tooltip } from "../ui/Tooltip";
import { GapAnalysisDrawer } from "./GapAnalysisDrawer";
import { ImportJobModal } from "./ImportJobModal";
import { JobPostingDrawer } from "./JobPostingDrawer";
import { ActiveMetadataFilterChips, MetadataFiltersPanel } from "./RadarMetadataFilters";

function extractJobPostingId(jobPosting: unknown): string | null {
    if (typeof jobPosting === "string" && jobPosting.length > 0) {
        return jobPosting;
    }
    if (typeof jobPosting === "object" && jobPosting !== null && "uuid" in jobPosting) {
        const uuid = (jobPosting as { uuid?: unknown }).uuid;
        return typeof uuid === "string" && uuid.length > 0 ? uuid : null;
    }
    return null;
}

function getSaveActionLabel(isSaved: boolean, isBusy: boolean): string {
    if (isBusy) {
        return isSaved ? "Removing..." : "Saving...";
    }
    return isSaved ? "Saved" : "Save";
}

function RadarSkeleton() {
    return (
        <div className="grid gap-5" aria-label="Loading semantic matches">
            {[0, 1, 2, 3].map((idx) => (
                <div
                    key={idx}
                    className="animate-pulse rounded-2xl border border-zinc-800/80 bg-zinc-900/50 p-6 sm:p-7"
                >
                    <div className="flex flex-col gap-6 lg:flex-row lg:items-center lg:justify-between">
                        <div className="flex flex-1 flex-col gap-5 sm:flex-row sm:items-start">
                            <div className="h-20 w-24 shrink-0 rounded-xl bg-zinc-800/80" />
                            <div className="flex-1 space-y-3">
                                <div className="flex gap-2">
                                    <div className="h-6 w-20 rounded-lg bg-zinc-800/80" />
                                    <div className="h-6 w-24 rounded-lg bg-zinc-800/60" />
                                    <div className="h-6 w-16 rounded-lg bg-zinc-800/60" />
                                </div>
                                <div className="h-6 w-2/3 rounded-lg bg-zinc-800/80" />
                                <div className="h-4 w-1/3 rounded bg-zinc-800/60" />
                                <div className="flex gap-2 pt-1">
                                    <div className="h-6 w-16 rounded-lg bg-zinc-800/60" />
                                    <div className="h-6 w-20 rounded-lg bg-zinc-800/60" />
                                    <div className="h-6 w-14 rounded-lg bg-zinc-800/60" />
                                </div>
                            </div>
                        </div>
                        <div className="flex gap-3">
                            <div className="h-10 w-28 rounded-xl bg-zinc-800/70" />
                            <div className="h-10 w-24 rounded-xl bg-zinc-800/70" />
                            <div className="h-10 w-24 rounded-xl bg-zinc-800/80" />
                        </div>
                    </div>
                </div>
            ))}
        </div>
    );
}

interface RadarMatchCardProps {
    match: MatchScore;
    minAlertScore: number;
    isSaved: boolean;
    isBusy: boolean;
    onOpenJob: (match: MatchScore) => void;
    onOpenGapDetails: (match: MatchScore) => void;
    onToggleSave: (match: MatchScore) => void;
}

function RadarMatchCard({
    match,
    minAlertScore,
    isSaved,
    isBusy,
    onOpenJob,
    onOpenGapDetails,
    onToggleSave,
}: Readonly<RadarMatchCardProps>) {
    const job = match.job_posting;
    const actionLabel = getSaveActionLabel(isSaved, isBusy);
    const rawFit = match.fit_score;
    const hasAiScore = rawFit !== null && rawFit !== undefined;
    const fitPct = hasAiScore ? Math.max(0, Math.min(100, Math.round(rawFit))) : null;
    const scoreTheme = scoreVisualTheme(rawFit, minAlertScore);
    const isAlert = isAlertMatch(rawFit, minAlertScore);
    const vectorPct = Math.max(0, Math.min(100, Math.round(match.cosine_similarity * 100)));
    const tileValue = fitPct !== null ? `${fitPct}%` : "—";
    const scoreProgress = fitPct !== null ? Math.max(4, fitPct) : 0;
    const scoreTooltip = hasAiScore
        ? "Stage 2 Gemini AI fit score (0–100%) evaluating tech stack, seniority, and experience alignment against your active resume."
        : "Stage 1 vector match only. Automated roles below the similarity threshold or outside your resume's targeting filters (seniority, contract, or region) skip automatic Gemini scoring to save tokens.";
    const alertTooltip = `Meets or exceeds your ${minAlertScore}% alert threshold for this resume profile.`;
    const vectorTooltip = `Stage 1 pgvector cosine similarity (${vectorPct}%) between your resume embedding and job description.`;
    const salaryLabel = formatSalaryRange(
        job.salary_min,
        job.salary_max,
        job.salary_currency,
        job.salary_period,
    );
    const seniorityLabel = formatSeniority(job.seniority);
    const postedAge = formatRelativeTime(job.posted_at);
    const postedExact = formatExactDate(job.posted_at);
    const postedTooltip = postedExact ? `Posted on ${postedExact}` : "Posting date";
    const matchedSet = new Set(match.matched_skills.map((skill) => skill.toLowerCase()));
    const visibleStack = job.tech_stack.slice(0, 8);
    const hiddenStack = job.tech_stack.slice(8);
    const saveTooltip = isSaved
        ? "Saved in Pipeline Tracker — click to unsave"
        : "Save this role to your Pipeline Tracker";

    return (
        <article className="group relative rounded-2xl border border-zinc-800/90 bg-zinc-900/55 p-6 ring-1 ring-inset ring-white/[0.03] transition hover:border-violet-500/40 hover:bg-zinc-900/90 sm:p-7">
            <button
                type="button"
                aria-label={`View full job listing for ${job.title} at ${job.company_name}`}
                onClick={() => onOpenJob(match)}
                className="absolute inset-0 z-0 cursor-pointer rounded-2xl focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-500/70"
            />

            <div className="pointer-events-none relative z-10 flex flex-col gap-6 xl:flex-row xl:items-center xl:justify-between">
                <div className="flex min-w-0 flex-1 flex-col gap-5 sm:flex-row sm:items-start">
                    <Tooltip
                        content={scoreTooltip}
                        className="pointer-events-auto inline-flex w-full shrink-0 sm:w-auto"
                    >
                        <button
                            type="button"
                            onClick={() => onOpenJob(match)}
                            className={`flex w-full shrink-0 cursor-pointer flex-row items-center justify-between gap-4 rounded-xl border px-4 py-3 text-left transition hover:brightness-110 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-500/70 sm:w-28 sm:flex-col sm:items-center sm:justify-center sm:gap-2 sm:px-3 sm:py-3.5 sm:text-center ${scoreTheme.tile}`}
                        >
                            <div>
                                <div
                                    className={`font-mono text-2xl font-bold leading-none tabular-nums ${scoreTheme.value}`}
                                >
                                    {tileValue}
                                </div>
                                <div className="mt-1 text-[11px] font-medium uppercase tracking-wider text-zinc-400">
                                    {scoreTheme.caption}
                                </div>
                            </div>
                            <div className="h-1.5 w-20 overflow-hidden rounded-full bg-zinc-950/80 sm:w-full">
                                <div
                                    className={`h-full rounded-full ${scoreTheme.bar}`}
                                    style={{ width: `${scoreProgress}%` }}
                                />
                            </div>
                        </button>
                    </Tooltip>

                    <div className="min-w-0 flex-1 space-y-3.5">
                        <div className="flex flex-wrap items-center gap-2">
                            {isAlert && (
                                <Tooltip
                                    content={alertTooltip}
                                    className="pointer-events-auto inline-flex"
                                >
                                    <span className="inline-flex items-center gap-1 rounded-lg bg-violet-500/15 px-2.5 py-1 text-xs font-semibold text-violet-300 ring-1 ring-violet-500/35">
                                        <Bell className="h-3 w-3" />
                                        Alert
                                    </span>
                                </Tooltip>
                            )}

                            {match.is_stale && (
                                <Tooltip
                                    content="Your resume changed since this match was scored. Background rescoring will refresh this verdict shortly."
                                    className="pointer-events-auto inline-flex"
                                >
                                    <span className="inline-flex items-center gap-1 rounded-lg bg-amber-500/15 px-2.5 py-1 text-xs font-semibold text-amber-300 ring-1 ring-amber-500/35">
                                        <RefreshCw className="h-3 w-3" />
                                        Stale Score
                                    </span>
                                </Tooltip>
                            )}

                            <Tooltip
                                content={vectorTooltip}
                                className="pointer-events-auto inline-flex"
                            >
                                <span className="rounded-lg bg-zinc-800/75 px-2.5 py-1 font-mono text-xs tabular-nums text-zinc-300">
                                    {formatVectorSimilarity(match.cosine_similarity)}
                                </span>
                            </Tooltip>

                            {seniorityLabel && (
                                <Tooltip
                                    content="Detected seniority level"
                                    className="pointer-events-auto inline-flex"
                                >
                                    <span className="rounded-lg bg-zinc-800/75 px-2.5 py-1 text-xs font-medium text-zinc-300">
                                        {seniorityLabel}
                                    </span>
                                </Tooltip>
                            )}

                            <Tooltip
                                content="Employment / contract type"
                                className="pointer-events-auto inline-flex"
                            >
                                <span className="rounded-lg bg-zinc-800/75 px-2.5 py-1 text-xs font-medium text-zinc-300">
                                    {formatContractType(job.contract_type)}
                                </span>
                            </Tooltip>

                            {salaryLabel && (
                                <Tooltip
                                    content={`Reported compensation range (${(job.salary_currency || "USD").toUpperCase()})`}
                                    className="pointer-events-auto inline-flex"
                                >
                                    <span className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-500/10 px-2.5 py-1 font-mono text-xs font-medium tabular-nums text-emerald-300 ring-1 ring-emerald-500/25">
                                        <Banknote className="h-3.5 w-3.5" />
                                        {salaryLabel}
                                    </span>
                                </Tooltip>
                            )}

                            {job.ats_source && (
                                <Tooltip
                                    content={`Collected from ${formatAtsSource(job.ats_source)} ATS`}
                                    className="pointer-events-auto inline-flex"
                                >
                                    <span className="px-1 text-xs font-medium text-zinc-500">
                                        {formatAtsSource(job.ats_source)}
                                    </span>
                                </Tooltip>
                            )}

                            {postedAge && (
                                <Tooltip
                                    content={postedTooltip}
                                    className="pointer-events-auto inline-flex"
                                >
                                    <span className="inline-flex items-center gap-1 text-xs text-zinc-500">
                                        <Clock className="h-3.5 w-3.5" />
                                        {postedAge}
                                    </span>
                                </Tooltip>
                            )}
                        </div>

                        <div className="space-y-1.5">
                            <h3 className="text-lg font-semibold leading-snug text-zinc-100 transition group-hover:text-violet-300">
                                {job.title}
                            </h3>
                            <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-zinc-400">
                                <span className="inline-flex items-center gap-1.5 font-medium text-zinc-300">
                                    <Building2 className="h-3.5 w-3.5 text-zinc-500" />
                                    {job.company_name}
                                </span>
                                <span className="inline-flex items-center gap-1.5">
                                    <MapPin className="h-3.5 w-3.5 text-zinc-500" />
                                    {job.location_raw || "Remote"}
                                </span>
                            </div>
                        </div>

                        {visibleStack.length > 0 && (
                            <div className="flex flex-wrap gap-2 pt-0.5">
                                {visibleStack.map((tag) => {
                                    const isMatched = matchedSet.has(tag.toLowerCase());
                                    const tagTooltip = isMatched
                                        ? `${tag} — matches your resume profile`
                                        : `${tag} — listed in job requirements`;
                                    return (
                                        <Tooltip
                                            key={tag}
                                            content={tagTooltip}
                                            className="pointer-events-auto inline-flex"
                                        >
                                            <span
                                                className={`rounded-lg border px-3 py-1 font-mono text-xs ${isMatched
                                                        ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-200"
                                                        : "border-zinc-800 bg-zinc-800/70 text-zinc-300"
                                                    }`}
                                            >
                                                {tag}
                                            </span>
                                        </Tooltip>
                                    );
                                })}
                                {hiddenStack.length > 0 && (
                                    <Tooltip
                                        content={`More stack tags: ${hiddenStack.join(", ")}`}
                                        className="pointer-events-auto inline-flex"
                                    >
                                        <span className="rounded-lg border border-zinc-800/80 bg-zinc-900/80 px-2.5 py-1 font-mono text-xs tabular-nums text-zinc-400">
                                            +{hiddenStack.length} more
                                        </span>
                                    </Tooltip>
                                )}
                            </div>
                        )}
                    </div>
                </div>

                <div className="pointer-events-auto relative z-20 flex flex-wrap shrink-0 items-center gap-3 xl:justify-end">
                    <Tooltip content="Inspect matched skills, missing keywords, and talking points">
                        <button
                            type="button"
                            onClick={() => onOpenGapDetails(match)}
                            className="inline-flex items-center gap-2 rounded-xl border border-zinc-800 bg-zinc-900 px-4 py-2.5 text-sm font-medium text-zinc-300 transition hover:border-zinc-700 hover:bg-zinc-800/80 hover:text-zinc-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-500/70"
                        >
                            <Sparkles className="h-4 w-4 text-violet-400" />
                            Gap Details
                        </button>
                    </Tooltip>

                    <Tooltip content={saveTooltip}>
                        <button
                            type="button"
                            disabled={isBusy}
                            onClick={() => onToggleSave(match)}
                            className={`inline-flex items-center gap-2 rounded-xl border px-4 py-2.5 text-sm font-medium transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-500/70 disabled:opacity-60 ${isSaved
                                    ? "border-emerald-500/30 bg-emerald-950/30 text-emerald-200 hover:border-red-500/40 hover:bg-red-950/30 hover:text-red-200"
                                    : "border-zinc-700 bg-zinc-800/80 text-zinc-200 hover:bg-zinc-700"
                                }`}
                        >
                            {isSaved ? (
                                <>
                                    <BookmarkCheck className="h-4 w-4 text-emerald-400" />
                                    {actionLabel}
                                </>
                            ) : (
                                <>
                                    <BookmarkPlus className="h-4 w-4 text-violet-400" />
                                    {actionLabel}
                                </>
                            )}
                        </button>
                    </Tooltip>

                    <Tooltip content={formatApplyLinkTooltip(job.apply_url)}>
                        <a
                            href={job.apply_url}
                            target={isMailtoUrl(job.apply_url) ? undefined : "_blank"}
                            rel={isMailtoUrl(job.apply_url) ? undefined : "noreferrer"}
                            className="inline-flex items-center gap-2 rounded-xl bg-violet-600 px-4 py-2.5 text-sm font-medium text-white shadow-sm shadow-violet-600/20 transition hover:bg-violet-500 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-500/70 focus-visible:ring-offset-2 focus-visible:ring-offset-zinc-950"
                        >
                            {formatApplyLinkLabel(job.apply_url, "Apply")}{" "}
                            {isMailtoUrl(job.apply_url) ? (
                                <Mail className="h-4 w-4" />
                            ) : (
                                <ExternalLink className="h-4 w-4" />
                            )}
                        </a>
                    </Tooltip>
                </div>
            </div>
        </article>
    );
}

interface ImportBannerState {
    phase: "queued" | "ready" | "info";
    title: string;
    company: string;
    message: string;
    externalId?: string;
    startedAt?: number;
    job?: JobPostingSummary | null;
    match?: MatchScore | null;
}

function formatElapsedDuration(elapsedSeconds: number): string {
    if (elapsedSeconds < 60) {
        return `${elapsedSeconds}s`;
    }
    const mins = Math.floor(elapsedSeconds / 60);
    const secs = elapsedSeconds % 60;
    return `${mins}m ${secs}s`;
}

function ImportStatusBanner({
    banner,
    onViewJob,
    onRetryWait,
    onDismiss,
}: Readonly<{
    banner: ImportBannerState;
    onViewJob: (job: JobPostingSummary, match?: MatchScore | null) => void;
    onRetryWait: () => void;
    onDismiss: () => void;
}>) {
    const [nowMs, setNowMs] = useState(() => Date.now());

    useEffect(() => {
        if (banner.phase !== "queued" || !banner.startedAt) {
            return;
        }
        const intervalId = window.setInterval(() => {
            setNowMs(Date.now());
        }, 1000);
        return () => window.clearInterval(intervalId);
    }, [banner.phase, banner.startedAt]);

    const isReady = banner.phase === "ready";
    const isQueued = banner.phase === "queued";
    const elapsedSeconds =
        isQueued && banner.startedAt
            ? Math.max(0, Math.floor((nowMs - banner.startedAt) / 1000))
            : 0;
    const canResumeWait = banner.phase === "info" && Boolean(banner.externalId) && !banner.job;

    return (
        <div
            className={`flex flex-wrap items-center justify-between gap-3 rounded-2xl border px-5 py-3.5 text-sm ${
                isReady
                    ? "border-emerald-500/30 bg-emerald-950/20 text-emerald-200"
                    : "border-violet-500/30 bg-violet-950/20 text-violet-200"
            }`}
        >
            <div className="flex items-center gap-3 min-w-0">
                {isQueued ? (
                    <Loader2 className="h-4 w-4 shrink-0 animate-spin text-violet-300" />
                ) : (
                    <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-400" />
                )}
                <p className="truncate">
                    <span className="font-semibold text-zinc-100">{banner.title}</span>{" "}
                    <span className="text-zinc-400">@ {banner.company}</span>
                    <span className="mx-2 text-zinc-600">·</span>
                    <span>{banner.message}</span>
                    {isQueued && elapsedSeconds > 0 && (
                        <span className="ml-2 font-mono text-xs tabular-nums text-violet-300/80">
                            ({formatElapsedDuration(elapsedSeconds)})
                        </span>
                    )}
                </p>
            </div>
            <div className="flex items-center gap-2 shrink-0">
                {banner.job && (
                    <button
                        type="button"
                        onClick={() => {
                            if (banner.job) onViewJob(banner.job, banner.match);
                        }}
                        className="rounded-lg border border-emerald-500/35 bg-emerald-500/15 px-3 py-1.5 text-xs font-medium text-emerald-200 transition hover:bg-emerald-500/25"
                    >
                        View Job
                    </button>
                )}
                {canResumeWait && (
                    <button
                        type="button"
                        onClick={onRetryWait}
                        className="rounded-lg border border-violet-500/35 bg-violet-500/15 px-3 py-1.5 text-xs font-medium text-violet-200 transition hover:bg-violet-500/25"
                    >
                        Keep Waiting
                    </button>
                )}
                <button
                    type="button"
                    onClick={onDismiss}
                    aria-label="Dismiss import status"
                    className="rounded-lg p-1 text-zinc-400 transition hover:bg-zinc-800 hover:text-zinc-200"
                >
                    <X className="h-4 w-4" />
                </button>
            </div>
        </div>
    );
}

const IMPORT_POLL_FAST_ATTEMPTS = 12;
const IMPORT_POLL_FAST_INTERVAL_MS = 2500;
const IMPORT_POLL_STEADY_INTERVAL_MS = 5000;
const IMPORT_POLL_MAX_DURATION_MS = 10 * 60 * 1000; // 10 minutes safety cap

function restorePendingImportBanner(): ImportBannerState | null {
    const pending = loadPendingImport();
    if (!pending) {
        return null;
    }
    return {
        phase: "queued",
        title: pending.title,
        company: pending.company,
        externalId: pending.externalId,
        startedAt: pending.startedAt,
        message: "Importing — waiting for AI enrichment and scoring to finish...",
    };
}

function computeNextPollDelayMs(attempts: number): number {
    return attempts < IMPORT_POLL_FAST_ATTEMPTS
        ? IMPORT_POLL_FAST_INTERVAL_MS
        : IMPORT_POLL_STEADY_INTERVAL_MS;
}

function computeInitialPollDelayMs(startedAt: number): number {
    return Date.now() - startedAt >= IMPORT_POLL_FAST_INTERVAL_MS
        ? 0
        : IMPORT_POLL_FAST_INTERVAL_MS;
}

async function fetchImportedJobByExternalId(
    externalId: string,
): Promise<JobPostingSummary | null> {
    try {
        const res = await vektrynApi.listJobs(
            `?ats_source=manual&external_id=${encodeURIComponent(externalId)}`,
        );
        return res.results[0] ?? null;
    } catch {
        // Ignore transient poll errors and keep waiting
        return null;
    }
}

async function fetchImportedMatchByExternalId(externalId: string): Promise<MatchScore | null> {
    try {
        const res = await vektrynApi.listMatches(
            `?external_id=${encodeURIComponent(externalId)}`,
        );
        return res.results[0] ?? null;
    } catch {
        return null;
    }
}

async function fetchExistingImportedRecords(
    jobUuid: string | null,
    externalId: string,
): Promise<{ job: JobPostingSummary | null; match: MatchScore | null }> {
    const jobPromise = jobUuid
        ? vektrynApi.getJob(jobUuid).catch(() => null)
        : Promise.resolve(null);
    const [job, match] = await Promise.all([
        jobPromise,
        fetchImportedMatchByExternalId(externalId),
    ]);
    return { job: job ?? match?.job_posting ?? null, match };
}

type ImportPersistedHandler = (
    externalId: string,
    persisted: JobPostingSummary,
    match: MatchScore | null,
) => void;

function useCrossTabPendingImportSync(
    onSynced: (banner: ImportBannerState | null, cleared: boolean) => void,
) {
    useEffect(() => {
        function handleStorageSync(event: StorageEvent) {
            if (event.key !== PENDING_IMPORT_STORAGE_KEY) {
                return;
            }
            onSynced(restorePendingImportBanner(), event.newValue === null);
        }
        window.addEventListener("storage", handleStorageSync);
        return () => window.removeEventListener("storage", handleStorageSync);
    }, [onSynced]);
}

class PendingImportPoller {
    private readonly externalId: string;
    private readonly startedAt: number;
    private readonly onPersisted: ImportPersistedHandler;
    private readonly onTimeout: (externalId: string) => void;
    private cancelled = false;
    private inFlight = false;
    private timerId: number | undefined;
    private attempts = 0;

    constructor(
        externalId: string,
        startedAt: number,
        onPersisted: ImportPersistedHandler,
        onTimeout: (externalId: string) => void,
    ) {
        this.externalId = externalId;
        this.startedAt = startedAt;
        this.onPersisted = onPersisted;
        this.onTimeout = onTimeout;
    }

    start(): void {
        document.addEventListener("visibilitychange", this.handleVisibilityChange);
        this.schedule(computeInitialPollDelayMs(this.startedAt));
    }

    stop(): void {
        this.cancelled = true;
        document.removeEventListener("visibilitychange", this.handleVisibilityChange);
        window.clearTimeout(this.timerId);
    }

    private readonly handleVisibilityChange = (): void => {
        if (!document.hidden && !this.inFlight && this.timerId === undefined) {
            this.schedule(0);
        }
    };

    private schedule(delayMs: number): void {
        if (this.cancelled) return;
        window.clearTimeout(this.timerId);
        this.timerId = window.setTimeout(() => void this.poll(), delayMs);
    }

    private async poll(): Promise<void> {
        this.timerId = undefined;
        if (this.cancelled || this.inFlight) return;
        this.inFlight = true;
        this.attempts += 1;
        const persisted = await fetchImportedJobByExternalId(this.externalId);
        if (this.cancelled) {
            this.inFlight = false;
            return;
        }
        if (persisted) {
            const match = await fetchImportedMatchByExternalId(this.externalId);
            this.inFlight = false;
            if (!this.cancelled) {
                this.onPersisted(this.externalId, persisted, match);
            }
            return;
        }
        this.inFlight = false;
        if (Date.now() - this.startedAt >= IMPORT_POLL_MAX_DURATION_MS) {
            this.onTimeout(this.externalId);
            return;
        }
        if (!document.hidden) {
            this.schedule(computeNextPollDelayMs(this.attempts));
        }
    }
}

function useImportJobPolling(
    importBanner: ImportBannerState | null,
    onPersisted: ImportPersistedHandler,
    onTimeout: (externalId: string) => void,
) {
    useEffect(() => {
        if (importBanner?.phase !== "queued" || !importBanner.externalId) {
            return;
        }
        const poller = new PendingImportPoller(
            importBanner.externalId,
            importBanner.startedAt ?? Date.now(),
            onPersisted,
            onTimeout,
        );
        poller.start();
        return () => poller.stop();
    }, [importBanner?.phase, importBanner?.externalId, importBanner?.startedAt, onPersisted, onTimeout]);
}

function RadarKpiGrid({
    loading,
    aiScoredCount,
    totalCount,
    strongCount,
    alertCount,
    savedCount,
}: Readonly<{
    loading: boolean;
    aiScoredCount: number;
    totalCount: number;
    strongCount: number;
    alertCount: number;
    savedCount: number;
}>) {
    return (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <Tooltip
                content="Active job matches evaluated by Stage 2 Gemini AI scoring (out of all active vector matches)"
                className="block"
            >
                <div className="rounded-2xl border border-zinc-800/90 bg-zinc-900/45 px-5 py-4 ring-1 ring-inset ring-white/[0.03]">
                    <p className="text-xs font-medium uppercase tracking-wider text-zinc-400">
                        AI Scored
                    </p>
                    <div className="mt-2 flex items-baseline gap-2">
                        <p className="font-mono text-2xl font-semibold tabular-nums text-zinc-100">
                            {loading ? "—" : aiScoredCount}
                        </p>
                        {!loading && (
                            <span className="font-mono text-xs tabular-nums text-zinc-500">
                                of {totalCount} active
                            </span>
                        )}
                    </div>
                </div>
            </Tooltip>

            <Tooltip
                content="High-confidence matches with an AI fit score of 80% or higher"
                className="block"
            >
                <div className="rounded-2xl border border-emerald-500/20 bg-emerald-950/15 px-5 py-4 ring-1 ring-inset ring-white/[0.03]">
                    <p className="text-xs font-medium uppercase tracking-wider text-emerald-300/80">
                        Strong Fit (80%+)
                    </p>
                    <p className="mt-2 font-mono text-2xl font-semibold tabular-nums text-emerald-300">
                        {loading ? "—" : strongCount}
                    </p>
                </div>
            </Tooltip>

            <Tooltip
                content="Roles meeting the 70%+ threshold used for real-time match alerts"
                className="block"
            >
                <div className="rounded-2xl border border-violet-500/20 bg-violet-950/15 px-5 py-4 ring-1 ring-inset ring-white/[0.03]">
                    <p className="text-xs font-medium uppercase tracking-wider text-violet-300/80">
                        Alert Threshold (70%+)
                    </p>
                    <p className="mt-2 font-mono text-2xl font-semibold tabular-nums text-violet-300">
                        {loading ? "—" : alertCount}
                    </p>
                </div>
            </Tooltip>

            <Tooltip
                content="Matched roles currently tracked in your Pipeline Tracker"
                className="block"
            >
                <div className="rounded-2xl border border-zinc-800/90 bg-zinc-900/45 px-5 py-4 ring-1 ring-inset ring-white/[0.03]">
                    <p className="text-xs font-medium uppercase tracking-wider text-zinc-400">
                        Saved in Pipeline
                    </p>
                    <p className="mt-2 font-mono text-2xl font-semibold tabular-nums text-sky-300">
                        {loading ? "—" : savedCount}
                    </p>
                </div>
            </Tooltip>
        </div>
    );
}

type RadarSortOption = "best_match" | "newest" | "posted_at" | "vector";

const RADAR_SORT_OPTIONS: ReadonlyArray<{
    value: RadarSortOption;
    label: string;
    ordering: string;
}> = [
    {
        value: "best_match",
        label: "Best Match",
        ordering: "-fit_score,-cosine_similarity,-created_at",
    },
    {
        value: "newest",
        label: "Newest Added",
        ordering: "-created_at",
    },
    {
        value: "posted_at",
        label: "Posted Date",
        ordering: "-job_posting__posted_at,-created_at",
    },
    {
        value: "vector",
        label: "Vector Similarity",
        ordering: "-cosine_similarity,-fit_score,-created_at",
    },
];

const SEARCH_DEBOUNCE_MS = 350;

function resolveRadarOrdering(sortBy: RadarSortOption): string | null {
    if (sortBy === "best_match") {
        return null;
    }
    return RADAR_SORT_OPTIONS.find((opt) => opt.value === sortBy)?.ordering ?? null;
}

function buildMatchesQueryParams(opts: {
    page: number;
    minScore: number;
    resumeFilter: string;
    evaluatedOnly: boolean;
    sortBy: RadarSortOption;
    search: string;
    metadataFilters: RadarMetadataFilters;
}): string {
    const params = new URLSearchParams();
    params.set("page", String(opts.page));
    if (opts.minScore > 0) params.set("min_fit_score", String(opts.minScore));
    if (opts.resumeFilter) params.set("resume_profile", opts.resumeFilter);
    if (opts.evaluatedOnly) params.set("evaluated_only", "true");
    if (opts.search) params.set("search", opts.search);
    if (opts.metadataFilters.seniority) params.set("seniority", opts.metadataFilters.seniority);
    if (opts.metadataFilters.contractType) {
        params.set("contract_type", opts.metadataFilters.contractType);
    }
    if (opts.metadataFilters.region) params.set("region", opts.metadataFilters.region);
    if (opts.metadataFilters.atsSource) params.set("ats_source", opts.metadataFilters.atsSource);
    const orderingParam = resolveRadarOrdering(opts.sortBy);
    if (orderingParam) params.set("ordering", orderingParam);
    return `?${params.toString()}`;
}

function SearchModeBadge({ mode }: Readonly<{ mode: HybridSearchMode | null }>) {
    if (!mode) return null;
    const isHybrid = mode === "hybrid";
    const tooltip = isHybrid
        ? "Ranked with Reciprocal Rank Fusion combining PostgreSQL full-text search and pgvector semantic similarity."
        : "Ranked with PostgreSQL full-text search.";
    return (
        <Tooltip content={tooltip} className="inline-flex">
            <span
                className={`rounded-md px-2 py-0.5 text-[11px] font-medium ${
                    isHybrid
                        ? "bg-violet-500/15 text-violet-300 ring-1 ring-violet-500/35"
                        : "bg-zinc-800/90 text-zinc-400 ring-1 ring-zinc-700/70"
                }`}
            >
                {isHybrid ? "Hybrid RRF" : "Keyword"}
            </span>
        </Tooltip>
    );
}

export function JobRadarView() {
    const [matches, setMatches] = useState<MatchScore[]>([]);
    const [totalCount, setTotalCount] = useState(0);
    const [aiScoredCount, setAiScoredCount] = useState(0);
    const [strongFitCount, setStrongFitCount] = useState(0);
    const [alertThresholdCount, setAlertThresholdCount] = useState(0);
    const [hasNext, setHasNext] = useState(false);
    const [hasPrevious, setHasPrevious] = useState(false);
    const [page, setPage] = useState(1);
    const [resumes, setResumes] = useState<ResumeProfile[]>([]);
    const [resumeFilter, setResumeFilter] = useState("");
    const [evaluatedOnly, setEvaluatedOnly] = useState(false);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [searchTerm, setSearchTerm] = useState("");
    const [debouncedSearch, setDebouncedSearch] = useState("");
    const [searchMode, setSearchMode] = useState<HybridSearchMode | null>(null);
    const [metadataFilters, setMetadataFilters] = useState<RadarMetadataFilters>(
        EMPTY_METADATA_FILTERS,
    );
    const [filtersOpen, setFiltersOpen] = useState(false);
    const [minScore, setMinScore] = useState<number>(0);
    const [sortBy, setSortBy] = useState<RadarSortOption>("best_match");
    const [selectedJobMatch, setSelectedJobMatch] = useState<MatchScore | null>(null);
    const [selectedImportedJob, setSelectedImportedJob] = useState<JobPostingSummary | null>(null);
    const [selectedGapMatch, setSelectedGapMatch] = useState<MatchScore | null>(null);
    const [importModalOpen, setImportModalOpen] = useState(false);
    const [reloadTick, setReloadTick] = useState(0);
    const [importBanner, setImportBanner] = useState<ImportBannerState | null>(() =>
        restorePendingImportBanner(),
    );
    const [savedLeadsByJobId, setSavedLeadsByJobId] = useState<Record<string, string>>({});
    const [savedTotalCount, setSavedTotalCount] = useState(0);
    const [savingJobId, setSavingJobId] = useState<string | null>(null);

    function openJobListing(match: MatchScore) {
        setSelectedGapMatch(null);
        setSelectedImportedJob(null);
        setSelectedJobMatch(match);
    }

    function openImportedJobListing(job: JobPostingSummary, match?: MatchScore | null) {
        const resolvedMatch = match ?? matches.find((m) => m.job_posting.uuid === job.uuid) ?? null;
        if (resolvedMatch) {
            openJobListing(resolvedMatch);
            return;
        }
        setSelectedGapMatch(null);
        setSelectedJobMatch(null);
        setSelectedImportedJob(job);
    }

    function openGapDetails(match: MatchScore) {
        setSelectedJobMatch(null);
        setSelectedImportedJob(null);
        setSelectedGapMatch(match);
    }

    async function refreshSavedLeads() {
        const { items: allLeads, totalCount: leadsCount } = await fetchAllPagesWithCount(
            vektrynApi.listLeads,
        );
        const nextMap: Record<string, string> = {};
        for (const lead of allLeads) {
            const jobId = extractJobPostingId(lead.job_posting);
            if (jobId && lead.uuid) {
                nextMap[jobId] = lead.uuid;
            }
        }
        setSavedLeadsByJobId(nextMap);
        setSavedTotalCount(leadsCount);
    }

    useEffect(() => {
        let cancelled = false;
        async function loadMeta() {
            const [leadsResult, resumesResult] = await Promise.allSettled([
                fetchAllPagesWithCount(vektrynApi.listLeads),
                vektrynApi.listResumes(),
            ]);
            if (cancelled) return;
            if (leadsResult.status === "fulfilled") {
                const nextMap: Record<string, string> = {};
                for (const lead of leadsResult.value.items) {
                    const jobId = extractJobPostingId(lead.job_posting);
                    if (jobId && lead.uuid) {
                        nextMap[jobId] = lead.uuid;
                    }
                }
                setSavedLeadsByJobId(nextMap);
                setSavedTotalCount(leadsResult.value.totalCount);
            }
            if (resumesResult.status === "fulfilled") {
                setResumes(resumesResult.value.results);
            }
        }
        void loadMeta();
        return () => {
            cancelled = true;
        };
    }, []);

    useEffect(() => {
        const trimmed = searchTerm.trim();
        if (trimmed === debouncedSearch) {
            return;
        }
        const timerId = window.setTimeout(() => {
            setDebouncedSearch(trimmed);
            setPage(1);
        }, SEARCH_DEBOUNCE_MS);
        return () => window.clearTimeout(timerId);
    }, [searchTerm, debouncedSearch]);

    useEffect(() => {
        let cancelled = false;
        async function loadMatches() {
            setLoading(true);
            setError(null);
            try {
                const query = buildMatchesQueryParams({
                    page,
                    minScore,
                    resumeFilter,
                    evaluatedOnly,
                    sortBy,
                    search: debouncedSearch,
                    metadataFilters,
                });
                const matchRes = await vektrynApi.listMatches(query);
                if (cancelled) return;
                setMatches(matchRes.results);
                setTotalCount(matchRes.count);
                setSearchMode(matchRes.search_mode ?? null);
                setAiScoredCount(
                    matchRes.summary?.ai_scored_count ??
                        matchRes.results.filter(
                            (m) => m.fit_score !== null && m.fit_score !== undefined,
                        ).length,
                );
                setStrongFitCount(
                    matchRes.summary?.strong_fit_count ??
                        matchRes.results.filter((m) => (m.fit_score ?? 0) >= 80).length,
                );
                setAlertThresholdCount(
                    matchRes.summary?.alert_threshold_count ??
                        matchRes.results.filter((m) => (m.fit_score ?? 0) >= 70).length,
                );
                setHasNext(Boolean(matchRes.next));
                setHasPrevious(Boolean(matchRes.previous));
            } catch (err) {
                if (!cancelled) {
                    setError(err instanceof Error ? err.message : "Failed to load matches");
                }
            } finally {
                if (!cancelled) setLoading(false);
            }
        }
        void loadMatches();
        return () => {
            cancelled = true;
        };
    }, [
        page,
        minScore,
        resumeFilter,
        evaluatedOnly,
        sortBy,
        debouncedSearch,
        metadataFilters,
        reloadTick,
    ]);

    const handleImportedPersisted = useCallback(
        (externalId: string, persisted: JobPostingSummary, match: MatchScore | null) => {
            clearPendingImport(externalId);
            setReloadTick((prev) => prev + 1);
            setImportBanner((prev) =>
                prev && prev.externalId === externalId
                    ? {
                          ...prev,
                          phase: "ready",
                          title: persisted.title,
                          company: persisted.company_name,
                          job: persisted,
                          match,
                          message: "Enriched and scored — Job Radar has been refreshed.",
                      }
                    : prev,
            );
        },
        [],
    );

    const handleImportedTimeout = useCallback((externalId: string) => {
        setImportBanner((prev) =>
            prev && prev.externalId === externalId
                ? {
                      ...prev,
                      phase: "info",
                      message: "Taking longer than expected in the worker queue.",
                  }
                : prev,
        );
    }, []);

    const handleResumeImportWait = useCallback(() => {
        setImportBanner((prev) => {
            if (!prev?.externalId) {
                return prev;
            }
            const restartedAt = Date.now();
            savePendingImport({
                externalId: prev.externalId,
                title: prev.title,
                company: prev.company,
                startedAt: restartedAt,
            });
            return {
                ...prev,
                phase: "queued",
                startedAt: restartedAt,
                message: "Waiting for AI enrichment and scoring to finish...",
            };
        });
    }, []);

    const handleDismissImportBanner = useCallback(() => {
        clearPendingImport();
        setImportBanner(null);
    }, []);

    const handleCrossTabSync = useCallback(
        (banner: ImportBannerState | null, cleared: boolean) => {
            setImportBanner(banner);
            if (cleared) {
                setReloadTick((prev) => prev + 1);
            }
        },
        [],
    );

    useCrossTabPendingImportSync(handleCrossTabSync);
    useImportJobPolling(importBanner, handleImportedPersisted, handleImportedTimeout);

    async function handleJobImported(res: ManualJobImportResponse) {
        if (res.status === "queued") {
            const startedAt = Date.now();
            savePendingImport({
                externalId: res.external_id,
                title: res.title,
                company: res.company_name,
                startedAt,
            });
            setImportBanner({
                phase: "queued",
                title: res.title,
                company: res.company_name,
                externalId: res.external_id,
                startedAt,
                message: "Importing — waiting for AI enrichment and scoring to finish...",
            });
            return;
        }

        clearPendingImport(res.external_id);
        setReloadTick((prev) => prev + 1);
        const { job: existingJob, match: existingMatch } = await fetchExistingImportedRecords(
            res.job_posting_uuid,
            res.external_id,
        );
        setImportBanner({
            phase: res.status === "reactivated" ? "ready" : "info",
            title: res.title,
            company: res.company_name,
            externalId: res.external_id,
            job: existingJob,
            match: existingMatch,
            message:
                res.status === "reactivated"
                    ? "Previously closed role reactivated and refreshed in Job Radar."
                    : "This role is already active in Vektryn.",
        });
    }

    async function handleToggleSaveLead(match: MatchScore) {
        const jobId = match.job_posting.uuid;
        const existingLeadUuid = savedLeadsByJobId[jobId];
        setSavingJobId(jobId);
        setError(null);

        try {
            if (existingLeadUuid) {
                await vektrynApi.deleteLead(existingLeadUuid);
                setSavedLeadsByJobId((prev) => {
                    const copy = { ...prev };
                    delete copy[jobId];
                    return copy;
                });
                setSavedTotalCount((prev) => Math.max(0, prev - 1));
            } else {
                const created = await vektrynApi.createLead({
                    job_posting: jobId,
                    resume_profile: match.resume_profile_uuid,
                    status: "saved",
                });
                setSavedLeadsByJobId((prev) => ({
                    ...prev,
                    [jobId]: created.uuid,
                }));
                setSavedTotalCount((prev) => prev + 1);
            }
        } catch (err) {
            const message = err instanceof Error ? err.message : String(err);
            const normalized = message.toLowerCase();

            if (
                !existingLeadUuid &&
                (message.includes("API 400") ||
                    message.includes("API 409") ||
                    normalized.includes("already exists") ||
                    normalized.includes("unique"))
            ) {
                await refreshSavedLeads();
            } else if (existingLeadUuid && message.includes("API 404")) {
                setSavedLeadsByJobId((prev) => {
                    const copy = { ...prev };
                    delete copy[jobId];
                    return copy;
                });
                setSavedTotalCount((prev) => Math.max(0, prev - 1));
            } else {
                setError(message || "Failed to update saved lead");
            }
        } finally {
            setSavingJobId(null);
        }
    }

    const minAlertByResumeId: Record<string, number> = {};
    for (const resume of resumes) {
        minAlertByResumeId[resume.uuid] = resume.min_alert_score;
    }
    const activeResumeMinAlertScore =
        resumes.find((r) => r.is_active)?.min_alert_score ?? DEFAULT_MIN_ALERT_SCORE;

    function resolveMinAlertScore(match: MatchScore | null): number {
        if (!match) return activeResumeMinAlertScore;
        return minAlertByResumeId[match.resume_profile_uuid] ?? activeResumeMinAlertScore;
    }

    const strongCount = strongFitCount;
    const alertCount = alertThresholdCount;
    const savedCount = savedTotalCount;
    const activeMetadataCount = countActiveMetadataFilters(metadataFilters);
    const hasActiveFilters =
        Boolean(searchTerm.trim()) ||
        Boolean(debouncedSearch) ||
        minScore > 0 ||
        Boolean(resumeFilter) ||
        evaluatedOnly ||
        activeMetadataCount > 0;

    function updateMetadataFilters(patch: Partial<RadarMetadataFilters>) {
        setMetadataFilters((prev) => ({ ...prev, ...patch }));
        setPage(1);
    }

    function removeMetadataFilter(key: keyof RadarMetadataFilters) {
        setMetadataFilters((prev) => ({ ...prev, [key]: "" }));
        setPage(1);
    }

    function clearMetadataFilters() {
        setMetadataFilters(EMPTY_METADATA_FILTERS);
        setPage(1);
    }

    function resetFilters() {
        setSearchTerm("");
        setDebouncedSearch("");
        setMinScore(0);
        setResumeFilter("");
        setEvaluatedOnly(false);
        setMetadataFilters(EMPTY_METADATA_FILTERS);
        setPage(1);
    }

    function renderResults() {
        if (loading) {
            return <RadarSkeleton />;
        }
        if (matches.length === 0) {
            return (
                <div className="flex flex-col items-center justify-center gap-4 rounded-2xl border border-zinc-800/90 bg-zinc-900/40 px-6 py-20 text-center ring-1 ring-inset ring-white/[0.03]">
                    <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-zinc-900 ring-1 ring-zinc-800">
                        <Search className="h-5 w-5 text-zinc-500" />
                    </div>
                    <div className="space-y-1">
                        <p className="text-base font-medium text-zinc-200">
                            No matching roles found
                        </p>
                        <p className="text-sm text-zinc-400">
                            {hasActiveFilters
                                ? "Try broadening your keyword search or lowering the minimum fit threshold."
                                : "Incoming semantic matches will appear here as collectors process roles."}
                        </p>
                    </div>
                    {hasActiveFilters && (
                        <Tooltip content="Clear search query and reset minimum fit threshold">
                            <button
                                type="button"
                                onClick={resetFilters}
                                className="inline-flex items-center gap-2 rounded-xl border border-zinc-700 bg-zinc-900 px-4 py-2 text-sm font-medium text-zinc-200 transition hover:border-zinc-600 hover:bg-zinc-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-500/70"
                            >
                                <RotateCcw className="h-4 w-4" />
                                Reset filters
                            </button>
                        </Tooltip>
                    )}
                </div>
            );
        }

        return (
            <div className="grid gap-5">
                {matches.map((match) => (
                    <RadarMatchCard
                        key={match.uuid}
                        match={match}
                        minAlertScore={resolveMinAlertScore(match)}
                        isSaved={Boolean(savedLeadsByJobId[match.job_posting.uuid])}
                        isBusy={savingJobId === match.job_posting.uuid}
                        onOpenJob={openJobListing}
                        onOpenGapDetails={openGapDetails}
                        onToggleSave={(m) => void handleToggleSaveLead(m)}
                    />
                ))}
            </div>
        );
    }

    const activeDrawerJob = selectedJobMatch?.job_posting ?? selectedImportedJob;
    const isActiveDrawerJobSaved = activeDrawerJob
        ? Boolean(savedLeadsByJobId[activeDrawerJob.uuid])
        : false;

    return (
        <div className="space-y-8">
            <header className="space-y-6">
                <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
                    <div className="flex flex-col gap-1">
                        <h1 className="text-2xl font-semibold tracking-tight text-zinc-100">
                            Job Radar
                        </h1>
                        <p className="text-sm text-zinc-400">
                            Semantic vector similarity and AI gap scoring across active engineering roles.
                        </p>
                    </div>
                    <Tooltip content="Import an external job posting by URL or pasted description">
                        <button
                            type="button"
                            onClick={() => setImportModalOpen(true)}
                            className="inline-flex items-center justify-center gap-2 self-start rounded-xl bg-violet-600 px-4 py-2.5 text-sm font-medium text-white shadow-sm shadow-violet-600/20 transition hover:bg-violet-500 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-500/70 focus-visible:ring-offset-2 focus-visible:ring-offset-zinc-950 sm:self-auto"
                        >
                            <Plus className="h-4 w-4" />
                            Import Job
                        </button>
                    </Tooltip>
                </div>

                {importBanner && (
                    <ImportStatusBanner
                        banner={importBanner}
                        onViewJob={openImportedJobListing}
                        onRetryWait={handleResumeImportWait}
                        onDismiss={handleDismissImportBanner}
                    />
                )}

                <RadarKpiGrid
                    loading={loading}
                    aiScoredCount={aiScoredCount}
                    totalCount={totalCount}
                    strongCount={strongCount}
                    alertCount={alertCount}
                    savedCount={savedCount}
                />
            </header>

            <div className="space-y-4 rounded-2xl border border-zinc-800/80 bg-zinc-900/45 p-4 ring-1 ring-inset ring-white/[0.03] sm:px-5 sm:py-4">
                <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
                    <div className="relative flex-1 max-w-xl">
                        <Search className="pointer-events-none absolute top-3 left-3.5 h-4 w-4 text-zinc-500" />
                        <input
                            type="text"
                            value={searchTerm}
                            onChange={(e) => setSearchTerm(e.target.value)}
                            placeholder="Search stack, role, company, or concept (e.g. DRF, KRaft, distributed Python)..."
                            className="w-full rounded-xl border border-zinc-800 bg-zinc-950/70 py-2.5 pr-28 pl-10 text-sm text-zinc-100 placeholder:text-zinc-500 transition focus:border-violet-500 focus:outline-none focus:ring-2 focus:ring-violet-500/25"
                        />
                        <div className="absolute top-2 right-2.5 flex items-center gap-1.5">
                            {Boolean(debouncedSearch) && !loading && (
                                <SearchModeBadge mode={searchMode} />
                            )}
                            {searchTerm && (
                                <Tooltip content="Clear search query" className="inline-flex">
                                    <button
                                        type="button"
                                        onClick={() => {
                                            setSearchTerm("");
                                            setDebouncedSearch("");
                                            setPage(1);
                                        }}
                                        aria-label="Clear search"
                                        className="rounded-lg p-1 text-zinc-500 transition hover:bg-zinc-800 hover:text-zinc-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-500/70"
                                    >
                                        <X className="h-4 w-4" />
                                    </button>
                                </Tooltip>
                            )}
                        </div>
                    </div>

                    <div className="flex flex-wrap items-center gap-3 text-sm">
                        {!loading && (
                            <span className="font-mono text-xs tabular-nums text-zinc-400">
                                {matches.length} shown · {totalCount} total
                            </span>
                        )}

                        <Tooltip content="Filter by seniority, contract type, region, or source">
                            <button
                                type="button"
                                aria-expanded={filtersOpen}
                                onClick={() => setFiltersOpen((prev) => !prev)}
                                className={`inline-flex items-center gap-2 rounded-xl border px-3.5 py-2.5 text-xs font-medium transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-500/70 ${
                                    filtersOpen || activeMetadataCount > 0
                                        ? "border-violet-500/40 bg-violet-500/15 text-violet-200"
                                        : "border-zinc-800 bg-zinc-950/70 text-zinc-300 hover:border-zinc-700 hover:text-zinc-100"
                                }`}
                            >
                                <Filter className="h-3.5 w-3.5" />
                                Filters
                                {activeMetadataCount > 0 && (
                                    <span className="rounded-md bg-violet-500/30 px-1.5 py-0.5 font-mono text-[11px] tabular-nums text-violet-100">
                                        {activeMetadataCount}
                                    </span>
                                )}
                            </button>
                        </Tooltip>

                        {resumes.length > 0 && (
                            <Tooltip content="Filter matches by target resume profile">
                                <div className="relative">
                                    <select
                                        aria-label="Filter by resume profile"
                                        value={resumeFilter}
                                        onChange={(e) => {
                                            setResumeFilter(e.target.value);
                                            setPage(1);
                                        }}
                                        className="appearance-none rounded-xl border border-zinc-800 bg-zinc-950/70 py-2.5 pr-9 pl-3.5 text-sm text-zinc-100 transition focus:border-violet-500 focus:outline-none focus:ring-2 focus:ring-violet-500/25"
                                    >
                                        <option value="">All resumes</option>
                                        {resumes.map((r) => (
                                            <option key={r.uuid} value={r.uuid}>
                                                {r.label}
                                            </option>
                                        ))}
                                    </select>
                                    <ChevronDown className="pointer-events-none absolute top-3 right-3 h-4 w-4 text-zinc-500" />
                                </div>
                            </Tooltip>
                        )}

                        <Tooltip content="Only show roles with a Stage 2 AI fit score">
                            <button
                                type="button"
                                onClick={() => {
                                    setEvaluatedOnly((prev) => !prev);
                                    setPage(1);
                                }}
                                className={`rounded-xl border px-3.5 py-2.5 text-xs font-medium transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-500/70 ${
                                    evaluatedOnly
                                        ? "border-violet-500/40 bg-violet-500/15 text-violet-200"
                                        : "border-zinc-800 bg-zinc-950/70 text-zinc-300 hover:border-zinc-700 hover:text-zinc-100"
                                }`}
                            >
                                AI Scored Only
                            </button>
                        </Tooltip>

                        <div className="flex items-center gap-2.5">
                            <ArrowUpDown className="h-4 w-4 text-zinc-400" />
                            <label htmlFor="radar-sort" className="text-zinc-400">
                                Sort:
                            </label>
                            <Tooltip content="Order matching roles server-side">
                                <div className="relative">
                                    <select
                                        id="radar-sort"
                                        value={sortBy}
                                        onChange={(e) => {
                                            setSortBy(e.target.value as RadarSortOption);
                                            setPage(1);
                                        }}
                                        className="appearance-none rounded-xl border border-zinc-800 bg-zinc-950/70 py-2.5 pr-9 pl-3.5 text-sm text-zinc-100 transition focus:border-violet-500 focus:outline-none focus:ring-2 focus:ring-violet-500/25"
                                    >
                                        {RADAR_SORT_OPTIONS.map((opt) => (
                                            <option key={opt.value} value={opt.value}>
                                                {opt.value === "best_match" && debouncedSearch
                                                    ? "Relevance (Hybrid)"
                                                    : opt.label}
                                            </option>
                                        ))}
                                    </select>
                                    <ChevronDown className="pointer-events-none absolute top-3 right-3 h-4 w-4 text-zinc-500" />
                                </div>
                            </Tooltip>
                        </div>

                        <div className="flex items-center gap-2.5">
                            <SlidersHorizontal className="h-4 w-4 text-zinc-400" />
                            <label htmlFor="min-fit" className="text-zinc-400">
                                Min Fit:
                            </label>
                            <Tooltip content="Filter roles by minimum AI fit score threshold (server-side)">
                                <div className="relative">
                                    <select
                                        id="min-fit"
                                        value={minScore}
                                        onChange={(e) => {
                                            setMinScore(Number(e.target.value));
                                            setPage(1);
                                        }}
                                        className="appearance-none rounded-xl border border-zinc-800 bg-zinc-950/70 py-2.5 pr-9 pl-3.5 text-sm text-zinc-100 transition focus:border-violet-500 focus:outline-none focus:ring-2 focus:ring-violet-500/25"
                                    >
                                        <option value={0}>All scored roles</option>
                                        <option value={70}>70%+ (Alert threshold)</option>
                                        <option value={80}>80%+ (Strong match)</option>
                                    </select>
                                    <ChevronDown className="pointer-events-none absolute top-3 right-3 h-4 w-4 text-zinc-500" />
                                </div>
                            </Tooltip>
                        </div>
                    </div>
                </div>

                {filtersOpen && (
                    <MetadataFiltersPanel
                        filters={metadataFilters}
                        onUpdate={updateMetadataFilters}
                    />
                )}

                <ActiveMetadataFilterChips
                    filters={metadataFilters}
                    onRemove={removeMetadataFilter}
                    onClearAll={clearMetadataFilters}
                />
            </div>

            {error && (
                <div className="rounded-2xl border border-red-500/30 bg-red-950/20 px-5 py-4 text-sm text-red-300">
                    {error}
                </div>
            )}

            {renderResults()}

            <PaginationBar
                page={page}
                totalCount={totalCount}
                hasPrevious={hasPrevious}
                hasNext={hasNext}
                loading={loading}
                itemLabel="matches"
                onPageChange={setPage}
            />

            <JobPostingDrawer
                jobPreview={activeDrawerJob}
                match={selectedJobMatch}
                saving={
                    selectedJobMatch ? savingJobId === selectedJobMatch.job_posting.uuid : false
                }
                saved={isActiveDrawerJobSaved}
                onClose={() => {
                    setSelectedJobMatch(null);
                    setSelectedImportedJob(null);
                }}
                onSaveLead={
                    selectedJobMatch
                        ? () => void handleToggleSaveLead(selectedJobMatch)
                        : undefined
                }
                onOpenGapDetails={
                    selectedJobMatch ? () => openGapDetails(selectedJobMatch) : undefined
                }
            />

            <GapAnalysisDrawer
                match={selectedGapMatch}
                minAlertScore={resolveMinAlertScore(selectedGapMatch)}
                saving={
                    selectedGapMatch ? savingJobId === selectedGapMatch.job_posting.uuid : false
                }
                saved={
                    selectedGapMatch
                        ? Boolean(savedLeadsByJobId[selectedGapMatch.job_posting.uuid])
                        : false
                }
                onClose={() => setSelectedGapMatch(null)}
                onSaveLead={(m) => void handleToggleSaveLead(m)}
            />

            <ImportJobModal
                open={importModalOpen}
                onClose={() => setImportModalOpen(false)}
                onImported={(res) => void handleJobImported(res)}
            />
        </div>
    );
}
