import {
    Banknote,
    Bell,
    BookmarkCheck,
    BookmarkPlus,
    CheckCircle2,
    Clock,
    ExternalLink,
    MessageSquareQuote,
    Sparkles,
    X,
    XCircle,
} from "lucide-react";
import { useEffect } from "react";
import type { MatchScore } from "../../types/models";
import {
    DEFAULT_MIN_ALERT_SCORE,
    formatAtsSource,
    formatContractType,
    formatExactDate,
    formatRelativeTime,
    formatSalaryRange,
    formatScoreLabel,
    formatSeniority,
    isAlertMatch,
    scoreBadgeStyle,
    scoreVisualTheme,
} from "../../utils/format";
import { Tooltip } from "../ui/Tooltip";

interface GapAnalysisDrawerProps {
    match: MatchScore | null;
    minAlertScore?: number;
    saving: boolean;
    saved: boolean;
    onClose: () => void;
    onSaveLead: (match: MatchScore) => void;
}

export function GapAnalysisDrawer({
    match,
    minAlertScore = DEFAULT_MIN_ALERT_SCORE,
    saving,
    saved,
    onClose,
    onSaveLead,
}: Readonly<GapAnalysisDrawerProps>) {
    useEffect(() => {
        if (!match) return;
        function handleKeyDown(event: KeyboardEvent) {
            if (event.key === "Escape") {
                onClose();
            }
        }
        window.addEventListener("keydown", handleKeyDown);
        return () => window.removeEventListener("keydown", handleKeyDown);
    }, [match, onClose]);

    if (!match) {
        return null;
    }

    const job = match.job_posting;
    const rawFit = match.fit_score;
    const hasAiScore = rawFit !== null && rawFit !== undefined;
    const scoreTheme = scoreVisualTheme(rawFit, minAlertScore);
    const isAlert = isAlertMatch(rawFit, minAlertScore);
    const vectorPct = Math.max(0, Math.min(100, Math.round(match.cosine_similarity * 100)));
    const fitPct = hasAiScore ? Math.max(0, Math.min(100, Math.round(rawFit))) : null;
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

    let saveButtonLabel = "Save to Tracker";
    if (saved) {
        saveButtonLabel = "Saved in Pipeline";
    } else if (saving) {
        saveButtonLabel = "Saving...";
    }
    const aiFitTooltip = hasAiScore
        ? "Stage 2 Gemini AI fit score (0–100%) evaluating tech stack, seniority, and experience alignment against your active resume."
        : "Stage 1 vector match only. Roles below the semantic similarity threshold skip automatic Gemini scoring to save tokens.";
    const vectorTooltip = `Stage 1 pgvector cosine similarity (${vectorPct}%) between your resume embedding and job description.`;
    const alertTooltip = `Meets or exceeds your ${minAlertScore}% alert threshold for this resume profile.`;
    const saveTooltip = saved
        ? "This role is already saved in your Pipeline Tracker"
        : "Save this role to your Pipeline Tracker";

    return (
        <div className="fixed inset-0 z-50 flex justify-end">
            <button
                type="button"
                aria-label="Close drawer"
                onClick={onClose}
                className="fixed inset-0 cursor-default bg-black/70 backdrop-blur-xs"
            />
            <dialog
                open
                aria-modal="true"
                aria-labelledby="gap-drawer-title"
                className="animate-drawer-in relative inset-auto z-10 m-0 flex h-full max-h-none w-full max-w-3xl flex-col border-0 border-l border-zinc-800 bg-zinc-950 p-0 text-zinc-100 shadow-2xl"
            >
                <div className="flex items-start justify-between gap-4 border-b border-zinc-800/90 bg-zinc-950/90 px-6 py-5 sm:px-8 sm:py-6">
                    <div className="min-w-0 space-y-2.5">
                        <div className="flex flex-wrap items-center gap-2">
                            {isAlert && (
                                <Tooltip content={alertTooltip} side="bottom">
                                    <span className="inline-flex items-center gap-1.5 rounded-lg bg-violet-500/15 px-2.5 py-1 text-xs font-semibold text-violet-300 ring-1 ring-violet-500/35">
                                        <Bell className="h-3.5 w-3.5" />
                                        Alert Match
                                    </span>
                                </Tooltip>
                            )}

                            <Tooltip content={aiFitTooltip} side="bottom">
                                <span
                                    className={`rounded-lg px-2.5 py-1 font-mono text-xs font-semibold tabular-nums ${scoreBadgeStyle(
                                        match.fit_score,
                                        minAlertScore,
                                    )}`}
                                >
                                    {formatScoreLabel(match.fit_score)}
                                </span>
                            </Tooltip>

                            {seniorityLabel && (
                                <Tooltip content="Detected seniority level" side="bottom">
                                    <span className="rounded-lg bg-zinc-800/80 px-2.5 py-1 text-xs font-medium text-zinc-300">
                                        {seniorityLabel}
                                    </span>
                                </Tooltip>
                            )}

                            <Tooltip content="Employment / contract type" side="bottom">
                                <span className="rounded-lg bg-zinc-800/80 px-2.5 py-1 text-xs font-medium text-zinc-300">
                                    {formatContractType(job.contract_type)}
                                </span>
                            </Tooltip>

                            {salaryLabel && (
                                <Tooltip content="Reported compensation range" side="bottom">
                                    <span className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-500/10 px-2.5 py-1 font-mono text-xs font-medium tabular-nums text-emerald-300 ring-1 ring-emerald-500/25">
                                        <Banknote className="h-3.5 w-3.5" />
                                        {salaryLabel}
                                    </span>
                                </Tooltip>
                            )}

                            {job.ats_source && (
                                <Tooltip
                                    content={`Collected from ${formatAtsSource(job.ats_source)} ATS`}
                                    side="bottom"
                                >
                                    <span className="text-xs font-medium text-zinc-500">
                                        {formatAtsSource(job.ats_source)}
                                    </span>
                                </Tooltip>
                            )}

                            {postedAge && (
                                <Tooltip content={postedTooltip} side="bottom">
                                    <span className="inline-flex items-center gap-1 text-xs text-zinc-500">
                                        <Clock className="h-3.5 w-3.5" />
                                        {postedAge}
                                    </span>
                                </Tooltip>
                            )}
                        </div>

                        <h2
                            id="gap-drawer-title"
                            className="text-xl font-semibold leading-snug text-zinc-100"
                        >
                            {job.title}
                        </h2>
                        <p className="text-sm text-zinc-400">
                            {job.company_name} · {job.location_raw || "Remote"}
                        </p>
                    </div>

                    <Tooltip content="Close gap analysis (Esc)" side="bottom">
                        <button
                            type="button"
                            onClick={onClose}
                            aria-label="Close drawer"
                            className="rounded-xl p-2 text-zinc-400 transition hover:bg-zinc-900 hover:text-zinc-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-500/70"
                        >
                            <X className="h-5 w-5" />
                        </button>
                    </Tooltip>
                </div>

                <div className="flex-1 space-y-6 overflow-y-auto px-6 py-6 sm:px-8 sm:py-7">
                    <section className="grid gap-5 rounded-2xl border border-zinc-800/90 bg-zinc-900/45 p-5 ring-1 ring-inset ring-white/[0.03] sm:grid-cols-2 sm:p-6">
                        <Tooltip content={aiFitTooltip} className="block">
                            <div className="space-y-2">
                                <div className="flex items-center justify-between text-xs">
                                    <span className="font-medium uppercase tracking-wider text-zinc-400">
                                        AI Fit
                                    </span>
                                    <span
                                        className={`font-mono font-semibold tabular-nums ${scoreTheme.value}`}
                                    >
                                        {fitPct !== null ? `${fitPct}%` : "Not Scored"}
                                    </span>
                                </div>
                                <div className="h-2 w-full overflow-hidden rounded-full bg-zinc-800">
                                    <div
                                        className={`h-full rounded-full transition-all ${scoreTheme.bar}`}
                                        style={{ width: `${fitPct ?? 0}%` }}
                                    />
                                </div>
                            </div>
                        </Tooltip>

                        <Tooltip content={vectorTooltip} className="block">
                            <div className="space-y-2">
                                <div className="flex items-center justify-between text-xs">
                                    <span className="font-medium uppercase tracking-wider text-zinc-400">
                                        Vector Similarity
                                    </span>
                                    <span className="font-mono font-semibold tabular-nums text-sky-300">
                                        {vectorPct}%
                                    </span>
                                </div>
                                <div className="h-2 w-full overflow-hidden rounded-full bg-zinc-800">
                                    <div
                                        className="h-full rounded-full bg-sky-400 transition-all"
                                        style={{ width: `${vectorPct}%` }}
                                    />
                                </div>
                            </div>
                        </Tooltip>
                    </section>

                    {match.gap_summary && (
                        <section className="rounded-2xl border border-zinc-800/90 bg-zinc-900/55 p-5 ring-1 ring-inset ring-white/[0.03] sm:p-6">
                            <div className="mb-3 flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-violet-300">
                                <Sparkles className="h-4 w-4" />
                                Fit Summary ({match.scoring_model || "gemini"})
                            </div>
                            <p className="text-sm leading-relaxed text-zinc-300">
                                {match.gap_summary}
                            </p>
                        </section>
                    )}

                    <div className="grid gap-5 sm:grid-cols-2">
                        <section className="rounded-2xl border border-emerald-500/20 bg-emerald-950/15 p-5 ring-1 ring-inset ring-white/[0.03] sm:p-6">
                            <h3 className="mb-4 flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-emerald-300">
                                <CheckCircle2 className="h-4 w-4" />
                                Matched Skills ({match.matched_skills.length})
                            </h3>
                            <div className="flex flex-wrap gap-2">
                                {match.matched_skills.length > 0 ? (
                                    match.matched_skills.map((skill) => (
                                        <Tooltip
                                            key={skill}
                                            content="Skill matched between your resume and this role"
                                        >
                                            <span className="rounded-lg border border-emerald-500/25 bg-emerald-500/15 px-3 py-1.5 font-mono text-xs text-emerald-200">
                                                {skill}
                                            </span>
                                        </Tooltip>
                                    ))
                                ) : (
                                    <span className="text-xs text-zinc-500">
                                        No matched skills recorded
                                    </span>
                                )}
                            </div>
                        </section>

                        <section className="rounded-2xl border border-amber-500/20 bg-amber-950/15 p-5 ring-1 ring-inset ring-white/[0.03] sm:p-6">
                            <h3 className="mb-4 flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-amber-300">
                                <XCircle className="h-4 w-4" />
                                Missing Keywords ({match.missing_keywords.length})
                            </h3>
                            <div className="flex flex-wrap gap-2">
                                {match.missing_keywords.length > 0 ? (
                                    match.missing_keywords.map((kw) => (
                                        <Tooltip
                                            key={kw}
                                            content="Keyword requested in posting but absent from your resume"
                                        >
                                            <span className="rounded-lg border border-amber-500/25 bg-amber-500/15 px-3 py-1.5 font-mono text-xs text-amber-200">
                                                {kw}
                                            </span>
                                        </Tooltip>
                                    ))
                                ) : (
                                    <span className="text-xs text-zinc-500">
                                        No critical gaps flagged
                                    </span>
                                )}
                            </div>
                        </section>
                    </div>

                    <section className="rounded-2xl border border-zinc-800/90 bg-zinc-900/45 p-5 ring-1 ring-inset ring-white/[0.03] sm:p-6">
                        <h3 className="mb-4 flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-zinc-300">
                            <MessageSquareQuote className="h-4 w-4 text-violet-400" />
                            Interview Talking Points
                        </h3>
                        {match.talking_points.length > 0 ? (
                            <ul className="space-y-3 text-sm leading-relaxed text-zinc-300">
                                {match.talking_points.map((point) => (
                                    <li key={point} className="flex gap-3">
                                        <span className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-violet-400" />
                                        <span>{point}</span>
                                    </li>
                                ))}
                            </ul>
                        ) : (
                            <p className="text-xs text-zinc-500">
                                No talking points generated for this match.
                            </p>
                        )}
                    </section>
                </div>

                <div className="flex flex-wrap items-center justify-between gap-4 border-t border-zinc-800/90 bg-zinc-900/80 px-6 py-5 sm:px-8">
                    <Tooltip content={saveTooltip}>
                        <button
                            type="button"
                            disabled={saving || saved}
                            onClick={() => onSaveLead(match)}
                            className={`inline-flex items-center gap-2 rounded-xl border px-5 py-2.5 text-sm font-medium transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-500/70 disabled:cursor-not-allowed ${saved
                                    ? "border-emerald-500/30 bg-emerald-950/30 text-emerald-200"
                                    : "border-zinc-700 bg-zinc-800 text-zinc-100 hover:bg-zinc-700 disabled:opacity-50"
                                }`}
                        >
                            {saved ? (
                                <BookmarkCheck className="h-4 w-4 text-emerald-400" />
                            ) : (
                                <BookmarkPlus className="h-4 w-4 text-violet-400" />
                            )}
                            {saveButtonLabel}
                        </button>
                    </Tooltip>

                    <Tooltip content="Open the job application page in a new tab">
                        <a
                            href={job.apply_url}
                            target="_blank"
                            rel="noreferrer"
                            className="inline-flex items-center gap-2 rounded-xl bg-violet-600 px-5 py-2.5 text-sm font-medium text-white shadow-sm shadow-violet-600/20 transition hover:bg-violet-500 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-500/70 focus-visible:ring-offset-2 focus-visible:ring-offset-zinc-900"
                        >
                            Open Original Posting <ExternalLink className="h-4 w-4" />
                        </a>
                    </Tooltip>
                </div>
            </dialog>
        </div>
    );
}
