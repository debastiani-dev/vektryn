import {
    Banknote,
    Briefcase,
    Building2,
    ChevronDown,
    Clock,
    ExternalLink,
    Eye,
    EyeOff,
    Mail,
    MapPin,
    Sparkles,
    StickyNote,
    Trash2,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { fetchAllPages, vektrynApi } from "../../api/client";
import type { ApplicationLead, LeadPriority, LeadStatus, MatchScore } from "../../types/models";
import {
    formatApplyLinkTooltip,
    formatContractType,
    formatExactDate,
    formatRelativeTime,
    formatSalaryRange,
    formatScoreLabel,
    isMailtoUrl,
    scoreBadgeStyle,
} from "../../utils/format";
import { GapAnalysisDrawer } from "../radar/GapAnalysisDrawer";
import { type JobListingPreview, JobPostingDrawer } from "../radar/JobPostingDrawer";
import { Tooltip } from "../ui/Tooltip";

interface StageMeta {
    id: LeadStatus;
    label: string;
    dot: string;
    topBorder: string;
}

const PIPELINE_STAGES: StageMeta[] = [
    { id: "discovered", label: "Discovered", dot: "bg-zinc-400", topBorder: "border-t-zinc-500/70" },
    { id: "saved", label: "Saved", dot: "bg-violet-400", topBorder: "border-t-violet-500/80" },
    { id: "applied", label: "Applied", dot: "bg-sky-400", topBorder: "border-t-sky-500/80" },
    { id: "screening", label: "Screening", dot: "bg-amber-400", topBorder: "border-t-amber-500/80" },
    {
        id: "interviewing",
        label: "Interviewing",
        dot: "bg-indigo-400",
        topBorder: "border-t-indigo-500/80",
    },
    { id: "offer", label: "Offer", dot: "bg-emerald-400", topBorder: "border-t-emerald-500/80" },
    { id: "rejected", label: "Rejected", dot: "bg-rose-400", topBorder: "border-t-rose-500/70" },
    { id: "withdrawn", label: "Withdrawn", dot: "bg-zinc-500", topBorder: "border-t-zinc-600/70" },
];

const PRIORITY_STYLES: Record<LeadPriority, string> = {
    low: "bg-zinc-800/90 text-zinc-400 ring-1 ring-zinc-700/60 hover:bg-zinc-800 hover:text-zinc-200",
    medium: "bg-sky-500/15 text-sky-300 ring-1 ring-sky-500/30 hover:bg-sky-500/25",
    high: "bg-rose-500/15 text-rose-300 ring-1 ring-rose-500/35 hover:bg-rose-500/25",
};

const NEXT_PRIORITY: Record<LeadPriority, LeadPriority> = {
    low: "medium",
    medium: "high",
    high: "low",
};

function getNestedField(
    source: unknown,
    field: "title" | "company_name" | "apply_url" | "ats_source",
): string {
    if (typeof source === "object" && source !== null && field in source) {
        const val = (source as Record<string, unknown>)[field];
        if (typeof val === "string") return val;
    }
    return "";
}

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

function formatLeadCountLabel(count: number): string {
    return count === 1 ? "1 lead" : `${count} leads`;
}

function buildLeadJobPreview(
    lead: ApplicationLead,
    match: MatchScore | null,
): JobListingPreview | null {
    if (match) {
        return match.job_posting;
    }
    const jobId = extractJobPostingId(lead.job_posting);
    if (!jobId) {
        return null;
    }
    return {
        uuid: jobId,
        title: lead.job_title || getNestedField(lead.job_posting, "title") || "Untitled Role",
        company_name:
            lead.company_name ||
            getNestedField(lead.job_posting, "company_name") ||
            "Unknown Company",
        apply_url: lead.apply_url || getNestedField(lead.job_posting, "apply_url") || "#",
        ats_source: lead.ats_source || getNestedField(lead.job_posting, "ats_source"),
    };
}

interface PipelineLeadCardProps {
    lead: ApplicationLead;
    match: MatchScore | null;
    isEditingNotes: boolean;
    isDeleting: boolean;
    isUpdatingPriority: boolean;
    notesDraft: string;
    onNotesDraftChange: (next: string) => void;
    onOpenJob: (lead: ApplicationLead, match: MatchScore | null) => void;
    onOpenGapDetails: (match: MatchScore) => void;
    onCyclePriority: (lead: ApplicationLead) => void;
    onStatusChange: (lead: ApplicationLead, nextStatus: LeadStatus) => void;
    onStartEditingNotes: (lead: ApplicationLead) => void;
    onCancelEditingNotes: () => void;
    onSaveNotes: (lead: ApplicationLead) => void;
    onDeleteLead: (lead: ApplicationLead) => void;
}

function LeadApplyLink({ applyUrl }: Readonly<{ applyUrl: string }>) {
    const isEmailApply = isMailtoUrl(applyUrl);
    return (
        <Tooltip content={formatApplyLinkTooltip(applyUrl)}>
            <a
                href={applyUrl}
                target={isEmailApply ? undefined : "_blank"}
                rel={isEmailApply ? undefined : "noreferrer"}
                aria-label={isEmailApply ? "Apply via email" : "Open job posting"}
                className="rounded-lg p-2 text-zinc-400 transition hover:bg-zinc-800 hover:text-zinc-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-500/70"
            >
                {isEmailApply ? (
                    <Mail className="h-4 w-4" />
                ) : (
                    <ExternalLink className="h-4 w-4" />
                )}
            </a>
        </Tooltip>
    );
}

function PipelineLeadCard({
    lead,
    match,
    isEditingNotes,
    isDeleting,
    isUpdatingPriority,
    notesDraft,
    onNotesDraftChange,
    onOpenJob,
    onOpenGapDetails,
    onCyclePriority,
    onStatusChange,
    onStartEditingNotes,
    onCancelEditingNotes,
    onSaveNotes,
    onDeleteLead,
}: Readonly<PipelineLeadCardProps>) {
    const hasNotes = Boolean(lead.notes.trim());
    const job = match?.job_posting ?? null;
    const jobId = extractJobPostingId(lead.job_posting);
    const title =
        job?.title ||
        lead.job_title ||
        getNestedField(lead.job_posting, "title") ||
        "Untitled Role";
    const companyName =
        job?.company_name ||
        lead.company_name ||
        getNestedField(lead.job_posting, "company_name") ||
        "Unknown Company";
    const applyUrl =
        job?.apply_url ||
        lead.apply_url ||
        getNestedField(lead.job_posting, "apply_url") ||
        "#";

    const activityIso = lead.last_activity_at || lead.applied_at || lead.modified_at;
    const activityAge = formatRelativeTime(activityIso);
    const activityExact = formatExactDate(activityIso);
    const activityTooltip = activityExact ? `Last updated ${activityExact}` : "Last updated";
    const notesTooltip = hasNotes
        ? "Edit notes attached to this lead"
        : "Add recruiter, salary, or interview prep notes";

    const nextPriority = NEXT_PRIORITY[lead.priority];
    const cosinePct = match ? Math.round(match.cosine_similarity * 100) : null;
    const salaryLabel = job
        ? formatSalaryRange(
            job.salary_min,
            job.salary_max,
            job.salary_currency,
            job.salary_period,
        )
        : null;
    const locationLabel = job ? job.location_raw || "Remote" : null;
    const contractLabel =
        job && job.contract_type !== "unknown" ? formatContractType(job.contract_type) : null;
    const isClosed = job ? !job.is_active : false;
    const hasDecisionMeta = Boolean(salaryLabel || locationLabel || contractLabel);

    return (
        <article
            className={`space-y-3.5 rounded-xl border border-zinc-800/90 bg-zinc-950/90 p-4 ring-1 ring-inset ring-white/[0.03] transition hover:border-zinc-700 sm:p-5 ${lead.priority === "high" ? "border-l-2 border-l-rose-500/80" : ""
                }`}
        >
            {(match || isClosed) && (
                <div className="flex flex-wrap items-center gap-1.5">
                    {match && match.fit_score !== null && (
                        <>
                            <Tooltip content={`AI fit score: ${match.fit_score}%`}>
                                <span
                                    className={`rounded-md px-2 py-0.5 font-mono text-[11px] font-semibold tabular-nums ${scoreBadgeStyle(
                                        match.fit_score,
                                    )}`}
                                >
                                    {formatScoreLabel(match.fit_score)}
                                </span>
                            </Tooltip>
                            <Tooltip
                                content={`Vector embedding cosine similarity (${(match.cosine_similarity * 100).toFixed(1)}%)`}
                            >
                                <span className="rounded-md bg-zinc-800/80 px-2 py-0.5 font-mono text-[11px] tabular-nums text-zinc-300">
                                    {cosinePct}% sim
                                </span>
                            </Tooltip>
                        </>
                    )}

                    {match && match.fit_score === null && cosinePct !== null && (
                        <>
                            <Tooltip
                                content={`Not AI-scored yet — ${cosinePct}% resume-to-job embedding similarity`}
                            >
                                <span className="rounded-md bg-sky-500/12 px-2 py-0.5 font-mono text-[11px] font-semibold tabular-nums text-sky-300 ring-1 ring-sky-500/25">
                                    {cosinePct}% Cosine Sim
                                </span>
                            </Tooltip>
                            <Tooltip content="Matched by embedding similarity only — LLM gap scoring has not run">
                                <span className="rounded-md bg-zinc-800/80 px-2 py-0.5 text-[11px] font-medium text-zinc-400">
                                    No AI Score
                                </span>
                            </Tooltip>
                        </>
                    )}

                    {isClosed && (
                        <Tooltip content="This job posting was marked closed upstream">
                            <span className="rounded-md bg-rose-500/15 px-2 py-0.5 text-[11px] font-medium text-rose-300 ring-1 ring-rose-500/30">
                                Closed
                            </span>
                        </Tooltip>
                    )}
                </div>
            )}

            <div className="flex items-start justify-between gap-3">
                <div className="min-w-0 space-y-1.5">
                    <h3>
                        {jobId ? (
                            <Tooltip content="View complete job listing">
                                <button
                                    type="button"
                                    onClick={() => onOpenJob(lead, match)}
                                    className="cursor-pointer text-left text-sm font-semibold leading-snug text-zinc-100 transition hover:text-violet-300 focus-visible:rounded focus-visible:text-violet-300 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-500/70"
                                >
                                    {title}
                                </button>
                            </Tooltip>
                        ) : (
                            <span className="text-sm font-semibold leading-snug text-zinc-100">
                                {title}
                            </span>
                        )}
                    </h3>
                    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-zinc-400">
                        <span className="inline-flex items-center gap-1.5 font-medium text-zinc-300">
                            <Building2 className="h-3.5 w-3.5 text-zinc-500" />
                            {companyName}
                        </span>
                        {activityAge && (
                            <Tooltip content={activityTooltip}>
                                <span className="inline-flex items-center gap-1 text-zinc-500">
                                    <Clock className="h-3 w-3" />
                                    {activityAge}
                                </span>
                            </Tooltip>
                        )}
                    </div>
                </div>

                <Tooltip content={`Priority: ${lead.priority} — click to cycle to ${nextPriority}`}>
                    <button
                        type="button"
                        disabled={isUpdatingPriority}
                        onClick={() => onCyclePriority(lead)}
                        aria-label={`Priority ${lead.priority}, click to change to ${nextPriority}`}
                        className={`shrink-0 cursor-pointer rounded-md px-2.5 py-1 font-mono text-[11px] font-medium uppercase tracking-wide transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-500/70 disabled:opacity-50 ${PRIORITY_STYLES[lead.priority]}`}
                    >
                        {lead.priority}
                    </button>
                </Tooltip>
            </div>

            {hasDecisionMeta && (
                <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 border-t border-zinc-800/60 pt-2.5 text-xs text-zinc-400">
                    {salaryLabel && (
                        <Tooltip content="Reported compensation range">
                            <span className="inline-flex items-center gap-1 font-mono font-medium tabular-nums text-emerald-300">
                                <Banknote className="h-3.5 w-3.5 text-emerald-400" />
                                {salaryLabel}
                            </span>
                        </Tooltip>
                    )}
                    {locationLabel && (
                        <span className="inline-flex min-w-0 items-center gap-1 truncate">
                            <MapPin className="h-3.5 w-3.5 shrink-0 text-zinc-500" />
                            <span className="truncate">{locationLabel}</span>
                        </span>
                    )}
                    {contractLabel && (
                        <Tooltip content="Employment / contract type">
                            <span className="inline-flex items-center gap-1 text-zinc-400">
                                <Briefcase className="h-3.5 w-3.5 text-zinc-500" />
                                {contractLabel}
                            </span>
                        </Tooltip>
                    )}
                </div>
            )}

            <div className="flex items-center justify-between gap-2.5 pt-0.5">
                <label htmlFor={`status-${lead.uuid}`} className="sr-only">
                    Move stage
                </label>
                <Tooltip content="Move lead to another pipeline stage" className="min-w-0 flex-1">
                    <div className="relative w-full">
                        <select
                            id={`status-${lead.uuid}`}
                            value={lead.status}
                            onChange={(e) => onStatusChange(lead, e.target.value as LeadStatus)}
                            className="w-full appearance-none rounded-lg border border-zinc-800 bg-zinc-900 py-2 pr-8 pl-3 text-xs font-medium text-zinc-200 transition hover:border-zinc-700 focus:border-violet-500 focus:outline-none focus:ring-2 focus:ring-violet-500/25"
                        >
                            {PIPELINE_STAGES.map((opt) => (
                                <option key={opt.id} value={opt.id}>
                                    {opt.label}
                                </option>
                            ))}
                        </select>
                        <ChevronDown className="pointer-events-none absolute top-2.5 right-2.5 h-3.5 w-3.5 text-zinc-500" />
                    </div>
                </Tooltip>

                <div className="flex shrink-0 items-center gap-1">
                    {match && (
                        <Tooltip content="Open AI skill gap analysis and talking points">
                            <button
                                type="button"
                                onClick={() => onOpenGapDetails(match)}
                                aria-label="Open gap analysis"
                                className="rounded-lg p-2 text-zinc-400 transition hover:bg-violet-500/15 hover:text-violet-300 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-500/70"
                            >
                                <Sparkles className="h-4 w-4" />
                            </button>
                        </Tooltip>
                    )}

                    <Tooltip content={notesTooltip}>
                        <button
                            type="button"
                            onClick={() => onStartEditingNotes(lead)}
                            aria-label="Edit notes"
                            className={`rounded-lg p-2 transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-500/70 ${hasNotes
                                    ? "bg-violet-500/15 text-violet-300 hover:bg-violet-500/25"
                                    : "text-zinc-400 hover:bg-zinc-800 hover:text-zinc-200"
                                }`}
                        >
                            <StickyNote className="h-4 w-4" />
                        </button>
                    </Tooltip>

                    <LeadApplyLink applyUrl={applyUrl} />

                    <Tooltip content="Unsave and remove lead from tracker">
                        <button
                            type="button"
                            disabled={isDeleting}
                            onClick={() => onDeleteLead(lead)}
                            aria-label="Unsave lead"
                            className="rounded-lg p-2 text-zinc-400 transition hover:bg-red-950/50 hover:text-red-300 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-red-500/60 disabled:opacity-50"
                        >
                            <Trash2 className="h-4 w-4" />
                        </button>
                    </Tooltip>
                </div>
            </div>

            {isEditingNotes && (
                <div className="space-y-3 border-t border-zinc-800 pt-3.5">
                    <textarea
                        rows={3}
                        value={notesDraft}
                        onChange={(e) => onNotesDraftChange(e.target.value)}
                        placeholder="Recruiter contact, salary notes, prep..."
                        className="w-full rounded-lg border border-zinc-700 bg-zinc-900 p-3 text-xs leading-relaxed text-zinc-100 placeholder:text-zinc-500 focus:border-violet-500 focus:outline-none focus:ring-2 focus:ring-violet-500/25"
                    />
                    <div className="flex justify-end gap-2">
                        <Tooltip content="Discard unsaved note changes">
                            <button
                                type="button"
                                onClick={onCancelEditingNotes}
                                className="rounded-lg px-3 py-1.5 text-xs font-medium text-zinc-400 transition hover:text-zinc-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-500/70"
                            >
                                Cancel
                            </button>
                        </Tooltip>
                        <Tooltip content="Save notes to this lead">
                            <button
                                type="button"
                                onClick={() => onSaveNotes(lead)}
                                className="rounded-lg bg-violet-600 px-3.5 py-1.5 text-xs font-medium text-white transition hover:bg-violet-500 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-500/70"
                            >
                                Save
                            </button>
                        </Tooltip>
                    </div>
                </div>
            )}

            {!isEditingNotes && lead.notes && (
                <p className="whitespace-pre-wrap rounded-lg border border-zinc-800/70 bg-zinc-900/50 p-3 text-xs leading-relaxed text-zinc-300">
                    {lead.notes}
                </p>
            )}
        </article>
    );
}

interface PipelineStageColumnProps {
    stage: StageMeta;
    stageLeads: ApplicationLead[];
    matchesByJobId: Record<string, MatchScore>;
    editingNotesId: string | null;
    deletingId: string | null;
    updatingPriorityId: string | null;
    notesDraft: string;
    onRegisterRef: (el: HTMLElement | null) => void;
    onNotesDraftChange: (next: string) => void;
    onOpenJob: (lead: ApplicationLead, match: MatchScore | null) => void;
    onOpenGapDetails: (match: MatchScore) => void;
    onCyclePriority: (lead: ApplicationLead) => void;
    onStatusChange: (lead: ApplicationLead, nextStatus: LeadStatus) => void;
    onStartEditingNotes: (lead: ApplicationLead) => void;
    onCancelEditingNotes: () => void;
    onSaveNotes: (lead: ApplicationLead) => void;
    onDeleteLead: (lead: ApplicationLead) => void;
}

function PipelineStageColumn({
    stage,
    stageLeads,
    matchesByJobId,
    editingNotesId,
    deletingId,
    updatingPriorityId,
    notesDraft,
    onRegisterRef,
    onNotesDraftChange,
    onOpenJob,
    onOpenGapDetails,
    onCyclePriority,
    onStatusChange,
    onStartEditingNotes,
    onCancelEditingNotes,
    onSaveNotes,
    onDeleteLead,
}: Readonly<PipelineStageColumnProps>) {
    return (
        <section
            ref={onRegisterRef}
            className={`flex min-h-[480px] w-[320px] shrink-0 snap-start flex-col rounded-2xl border border-zinc-800/90 border-t-2 bg-zinc-900/40 p-5 ring-1 ring-inset ring-white/[0.03] sm:w-[344px] ${stage.topBorder}`}
        >
            <div className="mb-4 flex items-center justify-between border-b border-zinc-800/80 pb-3.5">
                <div className="flex items-center gap-2.5">
                    <span className={`h-2 w-2 rounded-full ${stage.dot}`} />
                    <h2 className="text-xs font-semibold uppercase tracking-wider text-zinc-200">
                        {stage.label}
                    </h2>
                </div>
                <Tooltip content={`${formatLeadCountLabel(stageLeads.length)} in ${stage.label}`}>
                    <span className="rounded-full bg-zinc-800/90 px-2.5 py-0.5 font-mono text-xs font-medium tabular-nums text-zinc-300">
                        {stageLeads.length}
                    </span>
                </Tooltip>
            </div>

            <div className="flex flex-1 flex-col gap-4">
                {stageLeads.length === 0 && (
                    <p className="flex flex-1 items-center justify-center rounded-xl border border-dashed border-zinc-800/70 px-4 py-12 text-center text-xs text-zinc-500">
                        No leads in {stage.label}
                    </p>
                )}

                {stageLeads.map((lead) => {
                    const jobId = extractJobPostingId(lead.job_posting);
                    const match = jobId ? (matchesByJobId[jobId] ?? null) : null;
                    return (
                        <PipelineLeadCard
                            key={lead.uuid}
                            lead={lead}
                            match={match}
                            isEditingNotes={editingNotesId === lead.uuid}
                            isDeleting={deletingId === lead.uuid}
                            isUpdatingPriority={updatingPriorityId === lead.uuid}
                            notesDraft={notesDraft}
                            onNotesDraftChange={onNotesDraftChange}
                            onOpenJob={onOpenJob}
                            onOpenGapDetails={onOpenGapDetails}
                            onCyclePriority={onCyclePriority}
                            onStatusChange={onStatusChange}
                            onStartEditingNotes={onStartEditingNotes}
                            onCancelEditingNotes={onCancelEditingNotes}
                            onSaveNotes={onSaveNotes}
                            onDeleteLead={onDeleteLead}
                        />
                    );
                })}
            </div>
        </section>
    );
}

function PipelineSkeleton() {
    return (
        <div className="flex gap-5 overflow-hidden pt-1 pb-6" aria-label="Loading application pipeline">
            {[0, 1, 2, 3].map((col) => (
                <div
                    key={col}
                    className="flex min-h-[460px] w-[340px] shrink-0 animate-pulse flex-col rounded-2xl border border-zinc-800/80 bg-zinc-900/40 p-5"
                >
                    <div className="mb-4 flex items-center justify-between border-b border-zinc-800/80 pb-3.5">
                        <div className="h-4 w-24 rounded bg-zinc-800" />
                        <div className="h-5 w-7 rounded-full bg-zinc-800" />
                    </div>
                    <div className="space-y-4">
                        {[0, 1].map((card) => (
                            <div
                                key={card}
                                className="space-y-3 rounded-xl border border-zinc-800/80 bg-zinc-950/80 p-5"
                            >
                                <div className="h-4 w-3/4 rounded bg-zinc-800" />
                                <div className="h-3 w-1/2 rounded bg-zinc-800/70" />
                                <div className="flex items-center justify-between gap-3 pt-2">
                                    <div className="h-8 flex-1 rounded-lg bg-zinc-800/70" />
                                    <div className="h-8 w-20 rounded-lg bg-zinc-800/60" />
                                </div>
                            </div>
                        ))}
                    </div>
                </div>
            ))}
        </div>
    );
}

export function PipelineTrackerView() {
    const [leads, setLeads] = useState<ApplicationLead[]>([]);
    const [matchesByJobId, setMatchesByJobId] = useState<Record<string, MatchScore>>({});
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [editingNotesId, setEditingNotesId] = useState<string | null>(null);
    const [notesDraft, setNotesDraft] = useState("");
    const [deletingId, setDeletingId] = useState<string | null>(null);
    const [updatingPriorityId, setUpdatingPriorityId] = useState<string | null>(null);
    const [hideEmptyStages, setHideEmptyStages] = useState(false);
    const [selectedJobContext, setSelectedJobContext] = useState<{
        preview: JobListingPreview;
        match: MatchScore | null;
    } | null>(null);
    const [selectedGapMatch, setSelectedGapMatch] = useState<MatchScore | null>(null);
    const stageRefs = useRef<Partial<Record<LeadStatus, HTMLElement | null>>>({});

    useEffect(() => {
        let cancelled = false;
        async function load() {
            setLoading(true);
            setError(null);
            try {
                const [leadsResult, matchesResult] = await Promise.allSettled([
                    fetchAllPages(vektrynApi.listLeads),
                    fetchAllPages(vektrynApi.listMatches),
                ]);
                if (cancelled) return;

                if (leadsResult.status === "rejected") {
                    throw leadsResult.reason;
                }
                setLeads(leadsResult.value);

                if (matchesResult.status === "fulfilled") {
                    const nextMatchMap: Record<string, MatchScore> = {};
                    for (const match of matchesResult.value) {
                        nextMatchMap[match.job_posting.uuid] = match;
                    }
                    setMatchesByJobId(nextMatchMap);
                }
            } catch (err) {
                if (!cancelled) {
                    setError(err instanceof Error ? err.message : "Failed to load application leads");
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

    function openJobListing(lead: ApplicationLead, match: MatchScore | null) {
        const preview = buildLeadJobPreview(lead, match);
        if (!preview) return;
        setSelectedGapMatch(null);
        setSelectedJobContext({ preview, match });
    }

    function openGapDetails(match: MatchScore) {
        setSelectedJobContext(null);
        setSelectedGapMatch(match);
    }

    async function handleStatusChange(lead: ApplicationLead, nextStatus: LeadStatus) {
        if (lead.status === nextStatus) return;
        setError(null);
        try {
            const updated = await vektrynApi.updateLead(lead.uuid, { status: nextStatus });
            setLeads((prev) => prev.map((item) => (item.uuid === lead.uuid ? updated : item)));
        } catch (err) {
            setError(err instanceof Error ? err.message : "Failed to update lead status");
        }
    }

    async function handleCyclePriority(lead: ApplicationLead) {
        const nextPriority = NEXT_PRIORITY[lead.priority];
        setUpdatingPriorityId(lead.uuid);
        setError(null);
        try {
            const updated = await vektrynApi.updateLead(lead.uuid, { priority: nextPriority });
            setLeads((prev) => prev.map((item) => (item.uuid === lead.uuid ? updated : item)));
        } catch (err) {
            setError(err instanceof Error ? err.message : "Failed to update lead priority");
        } finally {
            setUpdatingPriorityId(null);
        }
    }

    async function handleSaveNotes(lead: ApplicationLead) {
        setError(null);
        try {
            const updated = await vektrynApi.updateLead(lead.uuid, { notes: notesDraft });
            setLeads((prev) => prev.map((item) => (item.uuid === lead.uuid ? updated : item)));
            setEditingNotesId(null);
        } catch (err) {
            setError(err instanceof Error ? err.message : "Failed to save notes");
        }
    }

    async function handleDeleteLead(lead: ApplicationLead) {
        setDeletingId(lead.uuid);
        setError(null);
        try {
            await vektrynApi.deleteLead(lead.uuid);
            setLeads((prev) => prev.filter((item) => item.uuid !== lead.uuid));
            if (editingNotesId === lead.uuid) {
                setEditingNotesId(null);
            }
        } catch (err) {
            const message = err instanceof Error ? err.message : String(err);
            if (message.includes("API 404")) {
                setLeads((prev) => prev.filter((item) => item.uuid !== lead.uuid));
            } else {
                setError(message || "Failed to remove lead");
            }
        } finally {
            setDeletingId(null);
        }
    }

    function startEditingNotes(lead: ApplicationLead) {
        setEditingNotesId(lead.uuid);
        setNotesDraft(lead.notes);
    }

    function scrollToStage(stageId: LeadStatus) {
        const target = stageRefs.current[stageId];
        if (target) {
            target.scrollIntoView({ behavior: "smooth", inline: "start", block: "nearest" });
        }
    }

    const activeCount = leads.filter(
        (lead) => lead.status !== "rejected" && lead.status !== "withdrawn",
    ).length;
    const interviewingCount = leads.filter(
        (lead) => lead.status === "screening" || lead.status === "interviewing",
    ).length;
    const offerCount = leads.filter((lead) => lead.status === "offer").length;
    const toggleEmptyTooltip = hideEmptyStages
        ? "Show all 8 pipeline stage columns"
        : "Hide stage columns with zero leads";

    const visibleStages = hideEmptyStages
        ? PIPELINE_STAGES.filter((stage) => leads.some((lead) => lead.status === stage.id))
        : PIPELINE_STAGES;

    function renderBoard() {
        if (loading) {
            return <PipelineSkeleton />;
        }
        if (visibleStages.length === 0) {
            return (
                <div className="flex flex-col items-center justify-center gap-4 rounded-2xl border border-zinc-800/90 bg-zinc-900/40 px-6 py-20 text-center ring-1 ring-inset ring-white/[0.03]">
                    <p className="text-base font-medium text-zinc-200">No leads in your pipeline yet</p>
                    <p className="text-sm text-zinc-400">
                        Save roles from Job Radar to begin tracking applications across stages.
                    </p>
                    <Tooltip content="Display all 8 pipeline stage columns">
                        <button
                            type="button"
                            onClick={() => setHideEmptyStages(false)}
                            className="inline-flex items-center gap-2 rounded-xl border border-zinc-700 bg-zinc-900 px-4 py-2 text-sm font-medium text-zinc-200 transition hover:bg-zinc-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-500/70"
                        >
                            <Eye className="h-4 w-4" />
                            Show all stages
                        </button>
                    </Tooltip>
                </div>
            );
        }

        return (
            <div className="pipeline-scroll flex gap-5 overflow-x-auto pt-1 pb-6 snap-x snap-proximity">
                {visibleStages.map((stage) => {
                    const stageLeads = leads.filter((item) => item.status === stage.id);

                    return (
                        <PipelineStageColumn
                            key={stage.id}
                            stage={stage}
                            stageLeads={stageLeads}
                            matchesByJobId={matchesByJobId}
                            editingNotesId={editingNotesId}
                            deletingId={deletingId}
                            updatingPriorityId={updatingPriorityId}
                            notesDraft={notesDraft}
                            onRegisterRef={(el) => {
                                stageRefs.current[stage.id] = el;
                            }}
                            onNotesDraftChange={setNotesDraft}
                            onOpenJob={openJobListing}
                            onOpenGapDetails={openGapDetails}
                            onCyclePriority={(lead) => void handleCyclePriority(lead)}
                            onStatusChange={(lead, nextStatus) =>
                                void handleStatusChange(lead, nextStatus)
                            }
                            onStartEditingNotes={startEditingNotes}
                            onCancelEditingNotes={() => setEditingNotesId(null)}
                            onSaveNotes={(lead) => void handleSaveNotes(lead)}
                            onDeleteLead={(lead) => void handleDeleteLead(lead)}
                        />
                    );
                })}
            </div>
        );
    }

    const activeJobMatch = selectedJobContext?.match ?? null;

    return (
        <div className="space-y-8">
            <header className="space-y-6">
                <div className="flex flex-col gap-1">
                    <h1 className="text-2xl font-semibold tracking-tight text-zinc-100">
                        Pipeline Tracker
                    </h1>
                    <p className="text-sm text-zinc-400">
                        Manage saved applications, track interview stages, and keep recruiter prep notes.
                    </p>
                </div>

                <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
                    <Tooltip content="All saved and tracked application leads" className="block">
                        <div className="rounded-2xl border border-zinc-800/90 bg-zinc-900/45 px-5 py-4 ring-1 ring-inset ring-white/[0.03]">
                            <p className="text-xs font-medium uppercase tracking-wider text-zinc-400">
                                Total Tracked
                            </p>
                            <p className="mt-2 font-mono text-2xl font-semibold tabular-nums text-zinc-100">
                                {loading ? "—" : leads.length}
                            </p>
                        </div>
                    </Tooltip>

                    <Tooltip
                        content="Leads excluding rejected and withdrawn opportunities"
                        className="block"
                    >
                        <div className="rounded-2xl border border-violet-500/20 bg-violet-950/15 px-5 py-4 ring-1 ring-inset ring-white/[0.03]">
                            <p className="text-xs font-medium uppercase tracking-wider text-violet-300/80">
                                Active Pipeline
                            </p>
                            <p className="mt-2 font-mono text-2xl font-semibold tabular-nums text-violet-300">
                                {loading ? "—" : activeCount}
                            </p>
                        </div>
                    </Tooltip>

                    <Tooltip
                        content="Roles currently in recruiter screening or technical interviews"
                        className="block"
                    >
                        <div className="rounded-2xl border border-amber-500/20 bg-amber-950/15 px-5 py-4 ring-1 ring-inset ring-white/[0.03]">
                            <p className="text-xs font-medium uppercase tracking-wider text-amber-300/80">
                                Screening &amp; Interviews
                            </p>
                            <p className="mt-2 font-mono text-2xl font-semibold tabular-nums text-amber-300">
                                {loading ? "—" : interviewingCount}
                            </p>
                        </div>
                    </Tooltip>

                    <Tooltip content="Roles that have reached the offer stage" className="block">
                        <div className="rounded-2xl border border-emerald-500/20 bg-emerald-950/15 px-5 py-4 ring-1 ring-inset ring-white/[0.03]">
                            <p className="text-xs font-medium uppercase tracking-wider text-emerald-300/80">
                                Offers
                            </p>
                            <p className="mt-2 font-mono text-2xl font-semibold tabular-nums text-emerald-300">
                                {loading ? "—" : offerCount}
                            </p>
                        </div>
                    </Tooltip>
                </div>
            </header>

            <div className="flex flex-col gap-3 rounded-2xl border border-zinc-800/80 bg-zinc-900/45 p-4 ring-1 ring-inset ring-white/[0.03] lg:flex-row lg:items-center lg:justify-between">
                <div className="flex flex-wrap items-center gap-2">
                    {PIPELINE_STAGES.map((stage) => {
                        const count = leads.filter((item) => item.status === stage.id).length;
                        const isHidden = hideEmptyStages && count === 0;
                        const stageTooltip = isHidden
                            ? `${stage.label} is hidden (0 leads)`
                            : `Jump to ${stage.label} column (${formatLeadCountLabel(count)})`;
                        return (
                            <Tooltip key={stage.id} content={stageTooltip}>
                                <button
                                    type="button"
                                    disabled={isHidden}
                                    onClick={() => scrollToStage(stage.id)}
                                    className="inline-flex items-center gap-2 rounded-xl border border-zinc-800/90 bg-zinc-950/60 px-3 py-1.5 text-xs font-medium text-zinc-300 transition hover:border-zinc-700 hover:bg-zinc-900 hover:text-zinc-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-500/70 disabled:cursor-not-allowed disabled:opacity-40"
                                >
                                    <span className={`h-2 w-2 rounded-full ${stage.dot}`} />
                                    <span>{stage.label}</span>
                                    <span className="font-mono tabular-nums text-zinc-500">
                                        {count}
                                    </span>
                                </button>
                            </Tooltip>
                        );
                    })}
                </div>

                <Tooltip content={toggleEmptyTooltip} className="inline-flex self-start lg:self-auto">
                    <button
                        type="button"
                        onClick={() => setHideEmptyStages((prev) => !prev)}
                        className={`inline-flex shrink-0 items-center gap-2 rounded-xl border px-3.5 py-2 text-xs font-medium transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-500/70 ${hideEmptyStages
                                ? "border-violet-500/40 bg-violet-500/15 text-violet-200"
                                : "border-zinc-800 bg-zinc-950/60 text-zinc-300 hover:border-zinc-700 hover:text-zinc-100"
                            }`}
                    >
                        {hideEmptyStages ? (
                            <Eye className="h-3.5 w-3.5" />
                        ) : (
                            <EyeOff className="h-3.5 w-3.5" />
                        )}
                        {hideEmptyStages ? "Show all stages" : "Hide empty stages"}
                    </button>
                </Tooltip>
            </div>

            {error && (
                <div className="rounded-2xl border border-red-500/30 bg-red-950/20 px-5 py-4 text-sm text-red-300">
                    {error}
                </div>
            )}

            {renderBoard()}

            <JobPostingDrawer
                jobPreview={selectedJobContext?.preview ?? null}
                match={activeJobMatch}
                saved
                onClose={() => setSelectedJobContext(null)}
                onOpenGapDetails={activeJobMatch ? () => openGapDetails(activeJobMatch) : undefined}
            />

            <GapAnalysisDrawer
                match={selectedGapMatch}
                saving={false}
                saved
                onClose={() => setSelectedGapMatch(null)}
                onSaveLead={() => undefined}
            />
        </div>
    );
}
