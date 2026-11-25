import {
    AlertCircle,
    Banknote,
    Bell,
    BookmarkCheck,
    BookmarkPlus,
    CheckCircle2,
    Clock,
    ExternalLink,
    Mail,
    MessageSquareQuote,
    RefreshCw,
    Sparkles,
    X,
    XCircle,
} from "lucide-react";
import { useEffect, useState } from "react";
import type { CopilotTone, MatchScore } from "../../types/models";
import {
    DEFAULT_MIN_ALERT_SCORE,
    formatApplyLinkLabel,
    formatApplyLinkTooltip,
    formatAtsSource,
    formatContractType,
    formatExactDate,
    formatRelativeTime,
    formatSalaryRange,
    formatScoreLabel,
    formatSeniority,
    isAlertMatch,
    isMailtoUrl,
    scoreBadgeStyle,
    scoreVisualTheme,
} from "../../utils/format";
import { splitLegacySummaryParagraphs } from "../../utils/fitSummary";
import { Tooltip } from "../ui/Tooltip";
import { CopilotPanel } from "./CopilotPanel";

interface GapAnalysisDrawerProps {
    match: MatchScore | null;
    minAlertScore?: number;
    defaultCopilotTone?: CopilotTone;
    saving: boolean;
    saved: boolean;
    onClose: () => void;
    onSaveLead: (match: MatchScore) => void;
}

interface GapDrawerFooterProps {
    applyUrl: string;
    saving: boolean;
    saved: boolean;
    onSaveLead: () => void;
}

function getSaveButtonLabel(saved: boolean, saving: boolean): string {
    if (saved) return "Saved in Pipeline";
    if (saving) return "Saving...";
    return "Save to Tracker";
}

function GapDrawerFooter({
    applyUrl,
    saving,
    saved,
    onSaveLead,
}: Readonly<GapDrawerFooterProps>) {
    const isEmailApply = isMailtoUrl(applyUrl);
    const saveTooltip = saved
        ? "This role is already saved in your Pipeline Tracker"
        : "Save this role to your Pipeline Tracker";

    return (
        <div className="flex flex-wrap items-center justify-between gap-4 border-t border-zinc-800/90 bg-zinc-900/80 px-6 py-5 sm:px-8">
            <Tooltip content={saveTooltip}>
                <button
                    type="button"
                    disabled={saving || saved}
                    onClick={onSaveLead}
                    className={`inline-flex items-center gap-2 rounded-xl border px-5 py-2.5 text-sm font-medium transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-500/70 disabled:cursor-not-allowed ${
                        saved
                            ? "border-emerald-500/30 bg-emerald-950/30 text-emerald-200"
                            : "border-zinc-700 bg-zinc-800 text-zinc-100 hover:bg-zinc-700 disabled:opacity-50"
                    }`}
                >
                    {saved ? (
                        <BookmarkCheck className="h-4 w-4 text-emerald-400" />
                    ) : (
                        <BookmarkPlus className="h-4 w-4 text-violet-400" />
                    )}
                    {getSaveButtonLabel(saved, saving)}
                </button>
            </Tooltip>

            <Tooltip
                content={formatApplyLinkTooltip(
                    applyUrl,
                    "Open the job application page in a new tab",
                )}
            >
                <a
                    href={applyUrl}
                    target={isEmailApply ? undefined : "_blank"}
                    rel={isEmailApply ? undefined : "noreferrer"}
                    className="inline-flex items-center gap-2 rounded-xl bg-violet-600 px-5 py-2.5 text-sm font-medium text-white shadow-sm shadow-violet-600/20 transition hover:bg-violet-500 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-500/70 focus-visible:ring-offset-2 focus-visible:ring-offset-zinc-900"
                >
                    {formatApplyLinkLabel(applyUrl, "Open Original Posting")}{" "}
                    {isEmailApply ? (
                        <Mail className="h-4 w-4" />
                    ) : (
                        <ExternalLink className="h-4 w-4" />
                    )}
                </a>
            </Tooltip>
        </div>
    );
}

function FitSummarySection({
    summary,
    highlights,
    watchoutNote,
    scoringModel,
}: Readonly<{
    summary: string;
    highlights: string[];
    watchoutNote: string;
    scoringModel: string;
}>) {
    const cleanSummary = summary.trim();
    const cleanHighlights = highlights.map((item) => item.trim()).filter(Boolean);
    const cleanWatchout = watchoutNote.trim();
    const hasStructuredFields = cleanHighlights.length > 0 || Boolean(cleanWatchout);

    if (!cleanSummary && !hasStructuredFields) {
        return null;
    }

    const legacyParagraphs = hasStructuredFields
        ? []
        : splitLegacySummaryParagraphs(cleanSummary);

    return (
        <section className="rounded-2xl border border-zinc-800/90 bg-zinc-900/55 p-5 ring-1 ring-inset ring-white/[0.03] sm:p-6">
            <div className="mb-3.5 flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-violet-300">
                <Sparkles className="h-4 w-4" />
                Fit Summary ({scoringModel || "gemini"})
            </div>

            {hasStructuredFields ? (
                <div className="space-y-3.5">
                    {cleanSummary && (
                        <p className="text-[14.5px] font-medium leading-relaxed text-zinc-100">
                            {cleanSummary}
                        </p>
                    )}

                    {cleanHighlights.length > 0 && (
                        <ul className="space-y-2.5 border-t border-zinc-800/80 pt-3.5 text-sm leading-relaxed text-zinc-300">
                            {cleanHighlights.map((point) => (
                                <li key={point} className="flex gap-3">
                                    <span className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-emerald-400/90" />
                                    <span>{point}</span>
                                </li>
                            ))}
                        </ul>
                    )}

                    {cleanWatchout && (
                        <div className="flex items-start gap-2.5 rounded-xl border border-amber-500/20 bg-amber-950/20 px-3.5 py-2.5 text-xs leading-relaxed text-amber-200/90">
                            <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-300" />
                            <p>
                                <span className="font-semibold uppercase tracking-wider text-amber-300">
                                    Note:{" "}
                                </span>
                                {cleanWatchout}
                            </p>
                        </div>
                    )}
                </div>
            ) : (
                <div className="space-y-3">
                    {legacyParagraphs.map((paragraph, index) => (
                        <p
                            key={paragraph}
                            className={
                                index === 0
                                    ? "text-[14.5px] font-medium leading-relaxed text-zinc-100"
                                    : "text-sm leading-relaxed text-zinc-300"
                            }
                        >
                            {paragraph}
                        </p>
                    ))}
                </div>
            )}
        </section>
    );
}

type DrawerTab = "analysis" | "copilot";

interface GapAnalysisTabContentProps {
    match: MatchScore;
    fitPct: number | null;
    vectorPct: number;
    scoreTheme: ReturnType<typeof scoreVisualTheme>;
    aiFitTooltip: string;
    vectorTooltip: string;
}

function GapAnalysisTabContent({
    match,
    fitPct,
    vectorPct,
    scoreTheme,
    aiFitTooltip,
    vectorTooltip,
}: Readonly<GapAnalysisTabContentProps>) {
    const hasFitSummary =
        Boolean(match.gap_summary) ||
        Boolean(match.fit_highlights?.length) ||
        Boolean(match.watchout_note);

    return (
        <>
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

            {hasFitSummary && (
                <FitSummarySection
                    summary={match.gap_summary}
                    highlights={match.fit_highlights ?? []}
                    watchoutNote={match.watchout_note ?? ""}
                    scoringModel={match.scoring_model}
                />
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
        </>
    );
}

function GapAnalysisDrawerContent({
    match,
    minAlertScore,
    defaultCopilotTone,
    saving,
    saved,
    onClose,
    onSaveLead,
}: Readonly<{
    match: MatchScore;
    minAlertScore?: number;
    defaultCopilotTone?: CopilotTone;
    saving: boolean;
    saved: boolean;
    onClose: () => void;
    onSaveLead: (match: MatchScore) => void;
}>) {
    const [activeTab, setActiveTab] = useState<DrawerTab>("analysis");

    const job = match.job_posting;
    const rawFit = match.fit_score;
    const hasAiScore = rawFit !== null && rawFit !== undefined;
    const effectiveMinAlertScore =
        minAlertScore ?? match.resume_min_alert_score ?? DEFAULT_MIN_ALERT_SCORE;
    const scoreTheme = scoreVisualTheme(rawFit, effectiveMinAlertScore);
    const isAlert = isAlertMatch(rawFit, effectiveMinAlertScore);
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

    const aiFitTooltip = hasAiScore
        ? "Stage 2 Gemini AI fit score (0–100%) evaluating tech stack, seniority, and experience alignment against your active resume."
        : "Stage 1 vector match only. Automated roles below the similarity threshold or outside your resume's targeting filters (seniority, contract, or region) skip automatic Gemini scoring to save tokens.";
    const vectorTooltip = `Stage 1 pgvector cosine similarity (${vectorPct}%) between your resume embedding and job description.`;
    const alertTooltip = `Meets or exceeds your ${effectiveMinAlertScore}% alert threshold for this resume profile.`;

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

                            {match.is_stale && (
                                <Tooltip
                                    content="Your resume changed since this match was scored. Background rescoring will refresh this verdict shortly."
                                    side="bottom"
                                >
                                    <span className="inline-flex items-center gap-1.5 rounded-lg bg-amber-500/15 px-2.5 py-1 text-xs font-semibold text-amber-300 ring-1 ring-amber-500/35">
                                        <RefreshCw className="h-3.5 w-3.5" />
                                        Stale Score
                                    </span>
                                </Tooltip>
                            )}

                            <Tooltip content={aiFitTooltip} side="bottom">
                                <span
                                    className={`rounded-lg px-2.5 py-1 font-mono text-xs font-semibold tabular-nums ${scoreBadgeStyle(
                                        match.fit_score,
                                        effectiveMinAlertScore,
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

                <div
                    role="tablist"
                    aria-label="Match analysis views"
                    className="flex items-center gap-1 border-b border-zinc-800/90 bg-zinc-950/80 px-6 sm:px-8"
                >
                    <button
                        type="button"
                        role="tab"
                        aria-selected={activeTab === "analysis"}
                        onClick={() => setActiveTab("analysis")}
                        className={`relative px-3 py-3 text-xs font-semibold transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-500/70 ${
                            activeTab === "analysis"
                                ? "text-zinc-100"
                                : "text-zinc-400 hover:text-zinc-200"
                        }`}
                    >
                        Gap Analysis
                        {activeTab === "analysis" && (
                            <span className="absolute inset-x-0 bottom-0 h-0.5 rounded-full bg-violet-500" />
                        )}
                    </button>
                    <button
                        type="button"
                        role="tab"
                        aria-selected={activeTab === "copilot"}
                        onClick={() => setActiveTab("copilot")}
                        className={`relative inline-flex items-center gap-1.5 px-3 py-3 text-xs font-semibold transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-500/70 ${
                            activeTab === "copilot"
                                ? "text-violet-200"
                                : "text-zinc-400 hover:text-zinc-200"
                        }`}
                    >
                        <Sparkles className="h-3.5 w-3.5 text-violet-400" />
                        AI Copilot
                        {activeTab === "copilot" && (
                            <span className="absolute inset-x-0 bottom-0 h-0.5 rounded-full bg-violet-500" />
                        )}
                    </button>
                </div>

                <div className="flex-1 space-y-6 overflow-y-auto px-6 py-6 sm:px-8 sm:py-7">
                    {activeTab === "copilot" ? (
                        <CopilotPanel
                            key={match.uuid}
                            match={match}
                            defaultTone={defaultCopilotTone}
                        />
                    ) : (
                        <GapAnalysisTabContent
                            match={match}
                            fitPct={fitPct}
                            vectorPct={vectorPct}
                            scoreTheme={scoreTheme}
                            aiFitTooltip={aiFitTooltip}
                            vectorTooltip={vectorTooltip}
                        />
                    )}
                </div>

                <GapDrawerFooter
                    applyUrl={job.apply_url}
                    saving={saving}
                    saved={saved}
                    onSaveLead={() => onSaveLead(match)}
                />
            </dialog>
        </div>
    );
}

export function GapAnalysisDrawer({
    match,
    minAlertScore,
    defaultCopilotTone,
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

    return (
        <GapAnalysisDrawerContent
            key={match.uuid}
            match={match}
            minAlertScore={minAlertScore}
            defaultCopilotTone={defaultCopilotTone}
            saving={saving}
            saved={saved}
            onClose={onClose}
            onSaveLead={onSaveLead}
        />
    );
}
