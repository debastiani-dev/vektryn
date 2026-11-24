import {
    Banknote,
    BookmarkCheck,
    BookmarkPlus,
    Building2,
    ChevronDown,
    Clock,
    ExternalLink,
    MapPin,
    RotateCcw,
    Search,
    SlidersHorizontal,
    Sparkles,
    X,
} from "lucide-react";
import { useEffect, useState } from "react";
import { vektrynApi } from "../../api/client";
import type { MatchScore } from "../../types/models";
import {
    formatAtsSource,
    formatContractType,
    formatExactDate,
    formatRelativeTime,
    formatSalaryRange,
    formatSeniority,
    scoreVisualTheme,
} from "../../utils/format";
import { Tooltip } from "../ui/Tooltip";
import { GapAnalysisDrawer } from "./GapAnalysisDrawer";
import { JobPostingDrawer } from "./JobPostingDrawer";

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
    isSaved: boolean;
    isBusy: boolean;
    onOpenJob: (match: MatchScore) => void;
    onOpenGapDetails: (match: MatchScore) => void;
    onToggleSave: (match: MatchScore) => void;
}

function RadarMatchCard({
    match,
    isSaved,
    isBusy,
    onOpenJob,
    onOpenGapDetails,
    onToggleSave,
}: Readonly<RadarMatchCardProps>) {
    const job = match.job_posting;
    const actionLabel = getSaveActionLabel(isSaved, isBusy);
    const scoreTheme = scoreVisualTheme(match.fit_score);
    const cosinePct = Math.round(match.cosine_similarity * 100);
    const tileValue = match.fit_score !== null ? `${match.fit_score}%` : `${cosinePct}%`;
    const scoreProgress =
        match.fit_score !== null
            ? Math.max(4, Math.min(100, match.fit_score))
            : Math.max(4, Math.min(100, cosinePct));
    const scoreTooltip =
        match.fit_score !== null
            ? `AI fit score: ${match.fit_score}% — click to view full job listing`
            : `Not AI-scored yet — showing ${cosinePct}% resume-to-job embedding similarity. Click to view full job listing.`;
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
                            {match.fit_score !== null ? (
                                <Tooltip
                                    content={`Vector embedding cosine similarity (${(match.cosine_similarity * 100).toFixed(1)}%)`}
                                    className="pointer-events-auto inline-flex"
                                >
                                    <span className="rounded-lg bg-zinc-800/75 px-2.5 py-1 font-mono text-xs tabular-nums text-zinc-300">
                                        {cosinePct}% sim
                                    </span>
                                </Tooltip>
                            ) : (
                                <Tooltip
                                    content="Matched by embedding similarity only — LLM gap scoring has not run for this role"
                                    className="pointer-events-auto inline-flex"
                                >
                                    <span className="rounded-lg bg-zinc-800/75 px-2.5 py-1 text-xs font-medium text-zinc-400">
                                        No AI Score
                                    </span>
                                </Tooltip>
                            )}

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

                    <Tooltip content="Open original job posting in a new tab">
                        <a
                            href={job.apply_url}
                            target="_blank"
                            rel="noreferrer"
                            className="inline-flex items-center gap-2 rounded-xl bg-violet-600 px-4 py-2.5 text-sm font-medium text-white shadow-sm shadow-violet-600/20 transition hover:bg-violet-500 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-500/70 focus-visible:ring-offset-2 focus-visible:ring-offset-zinc-950"
                        >
                            Apply <ExternalLink className="h-4 w-4" />
                        </a>
                    </Tooltip>
                </div>
            </div>
        </article>
    );
}

export function JobRadarView() {
    const [matches, setMatches] = useState<MatchScore[]>([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [searchTerm, setSearchTerm] = useState("");
    const [minScore, setMinScore] = useState<number>(0);
    const [selectedJobMatch, setSelectedJobMatch] = useState<MatchScore | null>(null);
    const [selectedGapMatch, setSelectedGapMatch] = useState<MatchScore | null>(null);
    const [savedLeadsByJobId, setSavedLeadsByJobId] = useState<Record<string, string>>({});
    const [savingJobId, setSavingJobId] = useState<string | null>(null);

    function openJobListing(match: MatchScore) {
        setSelectedGapMatch(null);
        setSelectedJobMatch(match);
    }

    function openGapDetails(match: MatchScore) {
        setSelectedJobMatch(null);
        setSelectedGapMatch(match);
    }

    async function refreshSavedLeads() {
        const leadRes = await vektrynApi.listLeads();
        const nextMap: Record<string, string> = {};
        for (const lead of leadRes.results) {
            const jobId = extractJobPostingId(lead.job_posting);
            if (jobId && lead.uuid) {
                nextMap[jobId] = lead.uuid;
            }
        }
        setSavedLeadsByJobId(nextMap);
    }

    useEffect(() => {
        let cancelled = false;
        async function load() {
            setLoading(true);
            setError(null);
            try {
                const [matchRes, leadRes] = await Promise.all([
                    vektrynApi.listMatches(),
                    vektrynApi.listLeads(),
                ]);
                if (cancelled) return;
                setMatches(matchRes.results);
                const nextMap: Record<string, string> = {};
                for (const lead of leadRes.results) {
                    const jobId = extractJobPostingId(lead.job_posting);
                    if (jobId && lead.uuid) {
                        nextMap[jobId] = lead.uuid;
                    }
                }
                setSavedLeadsByJobId(nextMap);
            } catch (err) {
                if (!cancelled) {
                    setError(err instanceof Error ? err.message : "Failed to load matches");
                }
            } finally {
                if (!cancelled) setLoading(false);
            }
        }
        void load();
        return () => {
            cancelled = true;
        };
    }, []);

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
            } else {
                setError(message || "Failed to update saved lead");
            }
        } finally {
            setSavingJobId(null);
        }
    }

    const filtered = matches.filter((m) => {
        if (minScore > 0 && (m.fit_score ?? 0) < minScore) return false;
        if (!searchTerm.trim()) return true;
        const q = searchTerm.toLowerCase();
        return (
            m.job_posting.title.toLowerCase().includes(q) ||
            m.job_posting.company_name.toLowerCase().includes(q) ||
            m.job_posting.tech_stack.some((t) => t.toLowerCase().includes(q))
        );
    });

    const strongCount = matches.filter((m) => (m.fit_score ?? 0) >= 80).length;
    const alertCount = matches.filter((m) => (m.fit_score ?? 0) >= 70).length;
    const savedCount = Object.keys(savedLeadsByJobId).length;
    const hasActiveFilters = Boolean(searchTerm.trim()) || minScore > 0;

    function resetFilters() {
        setSearchTerm("");
        setMinScore(0);
    }

    function renderResults() {
        if (loading) {
            return <RadarSkeleton />;
        }
        if (filtered.length === 0) {
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
                {filtered.map((match) => (
                    <RadarMatchCard
                        key={match.uuid}
                        match={match}
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

    return (
        <div className="space-y-8">
            <header className="space-y-6">
                <div className="flex flex-col gap-1">
                    <h1 className="text-2xl font-semibold tracking-tight text-zinc-100">Job Radar</h1>
                    <p className="text-sm text-zinc-400">
                        Semantic vector similarity and AI gap scoring across active engineering roles.
                    </p>
                </div>

                <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
                    <Tooltip
                        content="Total active job postings matched against your resume profile"
                        className="block"
                    >
                        <div className="rounded-2xl border border-zinc-800/90 bg-zinc-900/45 px-5 py-4 ring-1 ring-inset ring-white/[0.03]">
                            <p className="text-xs font-medium uppercase tracking-wider text-zinc-400">
                                Scored Matches
                            </p>
                            <p className="mt-2 font-mono text-2xl font-semibold tabular-nums text-zinc-100">
                                {loading ? "—" : matches.length}
                            </p>
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
            </header>

            <div className="flex flex-col gap-4 rounded-2xl border border-zinc-800/80 bg-zinc-900/45 p-4 ring-1 ring-inset ring-white/[0.03] sm:flex-row sm:items-center sm:justify-between sm:px-5 sm:py-4">
                <div className="relative flex-1 max-w-xl">
                    <Search className="pointer-events-none absolute top-3 left-3.5 h-4 w-4 text-zinc-500" />
                    <input
                        type="text"
                        value={searchTerm}
                        onChange={(e) => setSearchTerm(e.target.value)}
                        placeholder="Filter by role, company, or stack (e.g. django, kafka)..."
                        className="w-full rounded-xl border border-zinc-800 bg-zinc-950/70 py-2.5 pr-10 pl-10 text-sm text-zinc-100 placeholder:text-zinc-500 transition focus:border-violet-500 focus:outline-none focus:ring-2 focus:ring-violet-500/25"
                    />
                    {searchTerm && (
                        <Tooltip content="Clear search query" className="absolute top-2 right-2.5 inline-flex">
                            <button
                                type="button"
                                onClick={() => setSearchTerm("")}
                                aria-label="Clear search"
                                className="rounded-lg p-1 text-zinc-500 transition hover:bg-zinc-800 hover:text-zinc-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-500/70"
                            >
                                <X className="h-4 w-4" />
                            </button>
                        </Tooltip>
                    )}
                </div>

                <div className="flex flex-wrap items-center gap-4 text-sm">
                    {!loading && (
                        <span className="font-mono text-xs tabular-nums text-zinc-400">
                            {filtered.length} of {matches.length} roles
                        </span>
                    )}

                    <div className="flex items-center gap-2.5">
                        <SlidersHorizontal className="h-4 w-4 text-zinc-400" />
                        <label htmlFor="min-fit" className="text-zinc-400">
                            Min Fit:
                        </label>
                        <Tooltip content="Filter roles by minimum AI fit score threshold">
                            <div className="relative">
                                <select
                                    id="min-fit"
                                    value={minScore}
                                    onChange={(e) => setMinScore(Number(e.target.value))}
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

            {error && (
                <div className="rounded-2xl border border-red-500/30 bg-red-950/20 px-5 py-4 text-sm text-red-300">
                    {error}
                </div>
            )}

            {renderResults()}

            <JobPostingDrawer
                jobPreview={selectedJobMatch?.job_posting ?? null}
                match={selectedJobMatch}
                saving={
                    selectedJobMatch ? savingJobId === selectedJobMatch.job_posting.uuid : false
                }
                saved={
                    selectedJobMatch
                        ? Boolean(savedLeadsByJobId[selectedJobMatch.job_posting.uuid])
                        : false
                }
                onClose={() => setSelectedJobMatch(null)}
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
        </div>
    );
}
