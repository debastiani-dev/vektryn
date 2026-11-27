import {
    AlertTriangle,
    Banknote,
    Bell,
    Briefcase,
    Building2,
    CalendarClock,
    ChevronDown,
    Clock,
    Download,
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
import { NOTIFICATIONS_REFRESH_EVENT } from "../../hooks/useNotifications";
import type {
    ApplicationLead,
    CopilotTone,
    LeadPriority,
    LeadStatus,
    MatchScore,
} from "../../types/models";
import {
    DEFAULT_MIN_ALERT_SCORE,
    formatApplyLinkTooltip,
    formatContractType,
    formatExactDate,
    formatRelativeTime,
    formatSalaryRange,
    formatScoreLabel,
    formatVectorSimilarity,
    formatWorkMode,
    isAlertMatch,
    isMailtoUrl,
    scoreBadgeStyle,
    workModeBadgeStyle,
} from "../../utils/format";
import {
    formatFollowupDate,
    formatFollowupExact,
    fromDatetimeLocalValue,
    isLeadFollowupOverdue,
    toDatetimeLocalValue,
} from "../../utils/leadReminders";
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
    isEditingFollowup: boolean;
    isDeleting: boolean;
    isUpdatingPriority: boolean;
    notesDraft: string;
    followupDraft: string;
    onNotesDraftChange: (next: string) => void;
    onFollowupDraftChange: (next: string) => void;
    onOpenJob: (lead: ApplicationLead, match: MatchScore | null) => void;
    onOpenGapDetails: (match: MatchScore) => void;
    onCyclePriority: (lead: ApplicationLead) => void;
    onStatusChange: (lead: ApplicationLead, nextStatus: LeadStatus) => void;
    onStartEditingNotes: (lead: ApplicationLead) => void;
    onCancelEditingNotes: () => void;
    onSaveNotes: (lead: ApplicationLead) => void;
    onStartEditingFollowup: (lead: ApplicationLead) => void;
    onCancelEditingFollowup: () => void;
    onSaveFollowup: (lead: ApplicationLead, nextIso: string | null) => void;
    onDeleteLead: (lead: ApplicationLead) => void;
}

function LeadScoreBadges({
    match,
    isClosed,
    lead,
}: Readonly<{
    match: MatchScore | null;
    isClosed: boolean;
    lead: ApplicationLead;
}>) {
    const overdue = isLeadFollowupOverdue(lead);
    const followupDate = formatFollowupDate(lead.next_action_at);
    const followupExact = formatFollowupExact(lead.next_action_at);
    if (!match && !isClosed && !followupDate) {
        return null;
    }

    const hasAiScore = typeof match?.fit_score === "number";
    const minAlertScore = match?.resume_min_alert_score ?? DEFAULT_MIN_ALERT_SCORE;
    const isAlert = isAlertMatch(match?.fit_score, minAlertScore);
    const vectorPct = match ? Math.max(0, Math.min(100, Math.round(match.cosine_similarity * 100))) : 0;

    return (
        <div className="flex flex-wrap items-center gap-1.5">
            {match && (
                <>
                    <Tooltip
                        content={
                            hasAiScore
                                ? "Stage 2 Gemini AI fit score evaluating tech stack, seniority, and experience alignment."
                                : "Stage 1 vector match only — Stage 2 Gemini AI scoring has not run for this role."
                        }
                    >
                        <span
                            className={`rounded-md px-2 py-0.5 font-mono text-[11px] font-semibold tabular-nums ${scoreBadgeStyle(
                                match.fit_score,
                                minAlertScore,
                            )}`}
                        >
                            {hasAiScore ? formatScoreLabel(match.fit_score) : "UNSCORED"}
                        </span>
                    </Tooltip>

                    {isAlert && (
                        <Tooltip
                            content={`Meets or exceeds your ${minAlertScore}% alert fit threshold for this resume`}
                        >
                            <span className="inline-flex items-center gap-1 rounded-md bg-violet-500/15 px-2 py-0.5 text-[11px] font-semibold text-violet-300 ring-1 ring-violet-500/35">
                                <Bell className="h-3 w-3" />
                                Alert
                            </span>
                        </Tooltip>
                    )}

                    <Tooltip
                        content={`Stage 1 pgvector cosine similarity (${vectorPct}%) between your resume embedding and job description.`}
                    >
                        <span className="rounded-md bg-zinc-800/80 px-2 py-0.5 font-mono text-[11px] tabular-nums text-zinc-300">
                            {formatVectorSimilarity(match.cosine_similarity)}
                        </span>
                    </Tooltip>
                </>
            )}

            {followupDate && (
                <Tooltip
                    content={
                        overdue
                            ? `Follow-up overdue since ${followupExact ?? followupDate}`
                            : `Scheduled follow-up on ${followupExact ?? followupDate}`
                    }
                >
                    <span
                        className={`inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-[11px] font-medium ring-1 ${
                            overdue
                                ? "bg-amber-500/20 text-amber-200 ring-amber-500/45"
                                : "bg-sky-500/12 text-sky-300 ring-sky-500/25"
                        }`}
                    >
                        {overdue ? (
                            <AlertTriangle className="h-3 w-3 text-amber-300" />
                        ) : (
                            <CalendarClock className="h-3 w-3 text-sky-300" />
                        )}
                        {overdue ? `Overdue · ${followupDate}` : `Follow up · ${followupDate}`}
                    </span>
                </Tooltip>
            )}

            {isClosed && (
                <Tooltip content="This job posting was marked closed upstream">
                    <span className="rounded-md bg-rose-500/15 px-2 py-0.5 text-[11px] font-medium text-rose-300 ring-1 ring-rose-500/30">
                        Closed
                    </span>
                </Tooltip>
            )}
        </div>
    );
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

function getCardAccentClass(overdue: boolean, priority: LeadPriority): string {
    if (overdue) return "border-amber-500/45 border-l-2 border-l-amber-400";
    if (priority === "high") return "border-zinc-800/90 border-l-2 border-l-rose-500/80";
    return "border-zinc-800/90";
}

function getFollowupButtonClass(overdue: boolean, hasFollowup: boolean): string {
    if (overdue) return "bg-amber-500/20 text-amber-300 hover:bg-amber-500/30";
    if (hasFollowup) return "bg-sky-500/15 text-sky-300 hover:bg-sky-500/25";
    return "text-zinc-400 hover:bg-zinc-800 hover:text-zinc-200";
}

function PipelineLeadCard({
    lead,
    match,
    isEditingNotes,
    isEditingFollowup,
    isDeleting,
    isUpdatingPriority,
    notesDraft,
    followupDraft,
    onNotesDraftChange,
    onFollowupDraftChange,
    onOpenJob,
    onOpenGapDetails,
    onCyclePriority,
    onStatusChange,
    onStartEditingNotes,
    onCancelEditingNotes,
    onSaveNotes,
    onStartEditingFollowup,
    onCancelEditingFollowup,
    onSaveFollowup,
    onDeleteLead,
}: Readonly<PipelineLeadCardProps>) {
    const hasNotes = Boolean(lead.notes.trim());
    const hasFollowup = Boolean(lead.next_action_at);
    const overdue = isLeadFollowupOverdue(lead);
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
    const followupTooltip = hasFollowup
        ? "Edit or clear scheduled follow-up reminder"
        : "Schedule a follow-up reminder date";

    const nextPriority = NEXT_PRIORITY[lead.priority];
    const salaryLabel = job
        ? formatSalaryRange(
            job.salary_min,
            job.salary_max,
            job.salary_currency,
            job.salary_period,
        )
        : null;
    const locationLabel = job ? job.location_raw || "Remote" : null;
    const workMode = job?.work_mode ?? lead.work_mode ?? null;
    const contractLabel =
        job && job.contract_type !== "unknown" ? formatContractType(job.contract_type) : null;
    const isClosed = job ? !job.is_active : false;
    const hasDecisionMeta = Boolean(salaryLabel || locationLabel || workMode || contractLabel);
    const cardAccentClass = getCardAccentClass(overdue, lead.priority);

    return (
        <article
            className={`space-y-3.5 rounded-xl border bg-zinc-950/90 p-4 ring-1 ring-inset ring-white/[0.03] transition hover:border-zinc-700 sm:p-5 ${cardAccentClass}`}
        >
            <LeadScoreBadges match={match} isClosed={isClosed} lead={lead} />

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
                    {workMode && (
                        <Tooltip content="Workplace arrangement">
                            <span
                                className={`rounded-md px-2 py-0.5 text-[11px] font-medium ${workModeBadgeStyle(workMode)}`}
                            >
                                {formatWorkMode(workMode)}
                            </span>
                        </Tooltip>
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

                    <Tooltip content={followupTooltip}>
                        <button
                            type="button"
                            onClick={() => onStartEditingFollowup(lead)}
                            aria-label="Schedule follow-up reminder"
                            className={`rounded-lg p-2 transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-500/70 ${getFollowupButtonClass(overdue, hasFollowup)}`}
                        >
                            <CalendarClock className="h-4 w-4" />
                        </button>
                    </Tooltip>

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

            {isEditingFollowup && (
                <div className="space-y-3 border-t border-zinc-800 pt-3.5">
                    <label
                        htmlFor={`followup-${lead.uuid}`}
                        className="block text-[11px] font-medium uppercase tracking-wider text-zinc-400"
                    >
                        Follow-up reminder
                    </label>
                    <input
                        id={`followup-${lead.uuid}`}
                        type="datetime-local"
                        value={followupDraft}
                        onChange={(e) => onFollowupDraftChange(e.target.value)}
                        className="w-full rounded-lg border border-zinc-700 bg-zinc-900 px-3 py-2 text-xs text-zinc-100 focus:border-violet-500 focus:outline-none focus:ring-2 focus:ring-violet-500/25"
                    />
                    <div className="flex items-center justify-between gap-2">
                        {hasFollowup ? (
                            <button
                                type="button"
                                onClick={() => onSaveFollowup(lead, null)}
                                className="rounded-lg px-2.5 py-1.5 text-xs font-medium text-rose-300 transition hover:bg-rose-950/40"
                            >
                                Clear
                            </button>
                        ) : (
                            <span />
                        )}
                        <div className="flex items-center gap-2">
                            <button
                                type="button"
                                onClick={onCancelEditingFollowup}
                                className="rounded-lg px-3 py-1.5 text-xs font-medium text-zinc-400 transition hover:text-zinc-200"
                            >
                                Cancel
                            </button>
                            <button
                                type="button"
                                disabled={!followupDraft.trim()}
                                onClick={() =>
                                    onSaveFollowup(lead, fromDatetimeLocalValue(followupDraft))
                                }
                                className="rounded-lg bg-violet-600 px-3.5 py-1.5 text-xs font-medium text-white transition hover:bg-violet-500 disabled:opacity-50"
                            >
                                Save
                            </button>
                        </div>
                    </div>
                </div>
            )}

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
    editingFollowupId: string | null;
    deletingId: string | null;
    updatingPriorityId: string | null;
    notesDraft: string;
    followupDraft: string;
    onRegisterRef: (el: HTMLElement | null) => void;
    onNotesDraftChange: (next: string) => void;
    onFollowupDraftChange: (next: string) => void;
    onOpenJob: (lead: ApplicationLead, match: MatchScore | null) => void;
    onOpenGapDetails: (match: MatchScore) => void;
    onCyclePriority: (lead: ApplicationLead) => void;
    onStatusChange: (lead: ApplicationLead, nextStatus: LeadStatus) => void;
    onStartEditingNotes: (lead: ApplicationLead) => void;
    onCancelEditingNotes: () => void;
    onSaveNotes: (lead: ApplicationLead) => void;
    onStartEditingFollowup: (lead: ApplicationLead) => void;
    onCancelEditingFollowup: () => void;
    onSaveFollowup: (lead: ApplicationLead, nextIso: string | null) => void;
    onDeleteLead: (lead: ApplicationLead) => void;
}

function PipelineStageColumn({
    stage,
    stageLeads,
    matchesByJobId,
    editingNotesId,
    editingFollowupId,
    deletingId,
    updatingPriorityId,
    notesDraft,
    followupDraft,
    onRegisterRef,
    onNotesDraftChange,
    onFollowupDraftChange,
    onOpenJob,
    onOpenGapDetails,
    onCyclePriority,
    onStatusChange,
    onStartEditingNotes,
    onCancelEditingNotes,
    onSaveNotes,
    onStartEditingFollowup,
    onCancelEditingFollowup,
    onSaveFollowup,
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
                            isEditingFollowup={editingFollowupId === lead.uuid}
                            isDeleting={deletingId === lead.uuid}
                            isUpdatingPriority={updatingPriorityId === lead.uuid}
                            notesDraft={notesDraft}
                            followupDraft={followupDraft}
                            onNotesDraftChange={onNotesDraftChange}
                            onFollowupDraftChange={onFollowupDraftChange}
                            onOpenJob={onOpenJob}
                            onOpenGapDetails={onOpenGapDetails}
                            onCyclePriority={onCyclePriority}
                            onStatusChange={onStatusChange}
                            onStartEditingNotes={onStartEditingNotes}
                            onCancelEditingNotes={onCancelEditingNotes}
                            onSaveNotes={onSaveNotes}
                            onStartEditingFollowup={onStartEditingFollowup}
                            onCancelEditingFollowup={onCancelEditingFollowup}
                            onSaveFollowup={onSaveFollowup}
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

interface PipelineTrackerViewProps {
    defaultCopilotTone?: CopilotTone;
    hasGeminiApiKey?: boolean;
    onOpenAccountSettings?: () => void;
}

export function PipelineTrackerView({
    defaultCopilotTone,
    hasGeminiApiKey = true,
    onOpenAccountSettings,
}: Readonly<PipelineTrackerViewProps> = {}) {
    const [leads, setLeads] = useState<ApplicationLead[]>([]);
    const [matchesByJobId, setMatchesByJobId] = useState<Record<string, MatchScore>>({});
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [editingNotesId, setEditingNotesId] = useState<string | null>(null);
    const [notesDraft, setNotesDraft] = useState("");
    const [editingFollowupId, setEditingFollowupId] = useState<string | null>(null);
    const [followupDraft, setFollowupDraft] = useState("");
    const [exportingFormat, setExportingFormat] = useState<"csv" | "json" | null>(null);
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
        setEditingFollowupId(null);
        setEditingNotesId(lead.uuid);
        setNotesDraft(lead.notes);
    }

    function startEditingFollowup(lead: ApplicationLead) {
        setEditingNotesId(null);
        setEditingFollowupId(lead.uuid);
        setFollowupDraft(toDatetimeLocalValue(lead.next_action_at));
    }

    async function handleSaveFollowup(lead: ApplicationLead, nextIso: string | null) {
        setError(null);
        try {
            const updated = await vektrynApi.updateLead(lead.uuid, { next_action_at: nextIso });
            setLeads((prev) => prev.map((item) => (item.uuid === lead.uuid ? updated : item)));
            setEditingFollowupId(null);
            window.dispatchEvent(new Event(NOTIFICATIONS_REFRESH_EVENT));
        } catch (err) {
            setError(err instanceof Error ? err.message : "Failed to save follow-up reminder");
        }
    }

    async function handleExportLeads(format: "csv" | "json") {
        setExportingFormat(format);
        setError(null);
        try {
            const { blob, filename } = await vektrynApi.exportLeads(format);
            const url = URL.createObjectURL(blob);
            const anchor = document.createElement("a");
            anchor.href = url;
            anchor.download = filename;
            document.body.appendChild(anchor);
            anchor.click();
            anchor.remove();
            URL.revokeObjectURL(url);
        } catch (err) {
            setError(err instanceof Error ? err.message : `Failed to export leads as ${format.toUpperCase()}`);
        } finally {
            setExportingFormat(null);
        }
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
    const overdueCount = leads.filter((lead) => isLeadFollowupOverdue(lead)).length;
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
                            editingFollowupId={editingFollowupId}
                            deletingId={deletingId}
                            updatingPriorityId={updatingPriorityId}
                            notesDraft={notesDraft}
                            followupDraft={followupDraft}
                            onRegisterRef={(el) => {
                                stageRefs.current[stage.id] = el;
                            }}
                            onNotesDraftChange={setNotesDraft}
                            onFollowupDraftChange={setFollowupDraft}
                            onOpenJob={openJobListing}
                            onOpenGapDetails={openGapDetails}
                            onCyclePriority={(lead) => void handleCyclePriority(lead)}
                            onStatusChange={(lead, nextStatus) =>
                                void handleStatusChange(lead, nextStatus)
                            }
                            onStartEditingNotes={startEditingNotes}
                            onCancelEditingNotes={() => setEditingNotesId(null)}
                            onSaveNotes={(lead) => void handleSaveNotes(lead)}
                            onStartEditingFollowup={startEditingFollowup}
                            onCancelEditingFollowup={() => setEditingFollowupId(null)}
                            onSaveFollowup={(lead, nextIso) => void handleSaveFollowup(lead, nextIso)}
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
                <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
                    <div className="flex flex-col gap-1">
                        <div className="flex flex-wrap items-center gap-2.5">
                            <h1 className="text-2xl font-semibold tracking-tight text-zinc-100">
                                Pipeline Tracker
                            </h1>
                            {!loading && overdueCount > 0 && (
                                <span className="inline-flex items-center gap-1.5 rounded-full bg-amber-500/15 px-3 py-1 text-xs font-semibold text-amber-300 ring-1 ring-amber-500/35">
                                    <AlertTriangle className="h-3.5 w-3.5" />
                                    {overdueCount} overdue follow-up{overdueCount === 1 ? "" : "s"}
                                </span>
                            )}
                        </div>
                        <p className="text-sm text-zinc-400">
                            Manage saved applications, schedule follow-up reminders, and export your pipeline.
                        </p>
                    </div>

                    <div className="flex flex-wrap items-center gap-2 self-start sm:self-auto">
                        <Tooltip content="Download your pipeline leads as CSV">
                            <button
                                type="button"
                                disabled={exportingFormat !== null || loading}
                                onClick={() => void handleExportLeads("csv")}
                                className="inline-flex items-center gap-1.5 rounded-xl border border-zinc-800 bg-zinc-900/80 px-3.5 py-2 text-xs font-medium text-zinc-200 transition hover:border-zinc-700 hover:bg-zinc-800 disabled:opacity-50"
                            >
                                <Download className="h-3.5 w-3.5 text-violet-400" />
                                {exportingFormat === "csv" ? "Exporting..." : "Download CSV"}
                            </button>
                        </Tooltip>
                        <Tooltip content="Download your pipeline leads as JSON">
                            <button
                                type="button"
                                disabled={exportingFormat !== null || loading}
                                onClick={() => void handleExportLeads("json")}
                                className="inline-flex items-center gap-1.5 rounded-xl border border-zinc-800 bg-zinc-900/80 px-3.5 py-2 text-xs font-medium text-zinc-200 transition hover:border-zinc-700 hover:bg-zinc-800 disabled:opacity-50"
                            >
                                <Download className="h-3.5 w-3.5 text-sky-400" />
                                {exportingFormat === "json" ? "Exporting..." : "Download JSON"}
                            </button>
                        </Tooltip>
                    </div>
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
                defaultCopilotTone={defaultCopilotTone}
                hasGeminiApiKey={hasGeminiApiKey}
                onOpenAccountSettings={onOpenAccountSettings}
                saving={false}
                saved
                onClose={() => setSelectedGapMatch(null)}
                onSaveLead={() => undefined}
            />
        </div>
    );
}
