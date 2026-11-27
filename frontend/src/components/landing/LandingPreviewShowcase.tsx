import {
    Activity,
    AlertCircle,
    AlertTriangle,
    ArrowDown,
    ArrowLeft,
    ArrowUpRight,
    Banknote,
    BarChart3,
    Bell,
    BookmarkCheck,
    BookmarkPlus,
    Building2,
    CalendarClock,
    Check,
    CheckCircle2,
    Clock,
    Download,
    ExternalLink,
    EyeOff,
    FileText,
    Kanban,
    Layers,
    MapPin,
    Radar,
    RotateCcw,
    Search,
    Sparkles,
    Target,
    TrendingUp,
    User,
    X,
    XCircle,
} from "lucide-react";
import { type KeyboardEvent, useRef, useState } from "react";
import type { WorkMode } from "../../types/models";
import { formatWorkMode, workModeBadgeStyle } from "../../utils/format";
import { VektrynLogo } from "../ui/VektrynLogo";
import {
    type AnalyticsPreviewSubTab,
    CHANNEL_PERFORMANCE_PREVIEW,
    COPILOT_DRAFTS_PREVIEW,
    type CopilotArtifactKind,
    type CopilotPreviewMode,
    GAP_ANALYSIS_PREVIEW,
    INGESTED_SOURCES_STRIP,
    KANBAN_PREVIEW_COLUMNS,
    type KanbanPriority,
    MATCHED_STRENGTHS_PREVIEW,
    PERSONAL_WINDOW_SNAPSHOTS,
    PIPELINE_WORKERS_PREVIEW,
    PREVIEW_TABS,
    PREVIEW_WORK_MODE_OPTIONS,
    type PersonalWindowOption,
    type PreviewTabId,
    RADAR_PREVIEW_FILTERS,
    RADAR_PREVIEW_ROLES,
    RESUME_PROFILES_PREVIEW,
    type RadarPreviewFilter,
    type RadarPreviewRole,
    SKILL_GAP_BARS_PREVIEW,
    STACK_CATEGORY_FILTERS,
    STACK_DEMAND_PREVIEW,
    STACK_VELOCITY_DATES,
    STACK_VELOCITY_SERIES,
    type StackCategoryFilter,
    type StackSortField,
    cyclePreviewPriority,
    filterRadarPreviewRoles,
    getCopilotPreviewDraft,
    getNextPreviewTabId,
} from "./landingPreviewData";

const TAB_ICONS: Record<PreviewTabId, typeof Radar> = {
    radar: Radar,
    tracker: Kanban,
    analytics: BarChart3,
    resumes: FileText,
};

const PRIORITY_BADGE_STYLES: Record<KanbanPriority, string> = {
    high: "bg-rose-500/15 text-rose-300 ring-1 ring-rose-500/35 hover:bg-rose-500/25",
    medium: "bg-sky-500/15 text-sky-300 ring-1 ring-sky-500/30 hover:bg-sky-500/25",
    low: "bg-zinc-800/90 text-zinc-400 ring-1 ring-zinc-700/60 hover:bg-zinc-800 hover:text-zinc-200",
};

interface RadarPreviewCardProps {
    role: RadarPreviewRole;
    isSaved: boolean;
    isApplied: boolean;
    onToggleSave: (roleId: string) => void;
    onToggleApplied: (roleId: string) => void;
    onHide: (roleId: string) => void;
    onOpenGapDetails: () => void;
}

function RadarPreviewCard({
    role,
    isSaved,
    isApplied,
    onToggleSave,
    onToggleApplied,
    onHide,
    onOpenGapDetails,
}: Readonly<RadarPreviewCardProps>) {
    const matchedSet = new Set(role.matchedSkills.map((skill) => skill.toLowerCase()));
    const isHighScore = role.fitScore >= 85;
    const tileClass = isHighScore
        ? "border-violet-500/35 bg-violet-950/25"
        : "border-emerald-500/30 bg-emerald-950/20";
    const scoreValueClass = isHighScore ? "text-violet-300" : "text-emerald-300";
    const barClass = isHighScore ? "bg-violet-400" : "bg-emerald-400";

    return (
        <article className="rounded-2xl border border-zinc-800/90 bg-zinc-900/55 p-4 ring-1 ring-inset ring-white/[0.03] transition hover:border-violet-500/40 hover:bg-zinc-900/85 sm:p-5">
            <div className="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
                <div className="flex min-w-0 flex-1 flex-col gap-4 sm:flex-row sm:items-start">
                    <div
                        className={`flex w-full shrink-0 flex-row items-center justify-between gap-4 rounded-xl border px-4 py-2.5 sm:w-24 sm:flex-col sm:items-center sm:justify-center sm:gap-2 sm:px-3 sm:py-3 sm:text-center ${tileClass}`}
                    >
                        <div>
                            <div
                                className={`font-mono text-xl font-bold leading-none tabular-nums ${scoreValueClass}`}
                            >
                                {role.fitScore}%
                            </div>
                            <div className="mt-1 text-[10px] font-medium uppercase tracking-wider text-zinc-400">
                                AI FIT
                            </div>
                        </div>
                        <div className="h-1.5 w-20 overflow-hidden rounded-full bg-zinc-950/80 sm:w-full">
                            <div
                                className={`h-full rounded-full ${barClass}`}
                                style={{ width: `${role.fitScore}%` }}
                            />
                        </div>
                    </div>

                    <div className="min-w-0 flex-1 space-y-2.5">
                        <div className="flex flex-wrap items-center gap-1.5">
                            {role.alertTriggered && (
                                <span className="inline-flex items-center gap-1 rounded-lg bg-violet-500/15 px-2 py-0.5 text-[11px] font-semibold text-violet-300 ring-1 ring-violet-500/35">
                                    <Bell className="h-3 w-3" aria-hidden="true" />
                                    <span>Alert</span>
                                </span>
                            )}
                            <span className="rounded-lg bg-zinc-800/75 px-2 py-0.5 font-mono text-[11px] tabular-nums text-zinc-300">
                                {role.vectorPercent}% vector
                            </span>
                            <span
                                className={`rounded-lg px-2 py-0.5 text-[11px] font-medium ${workModeBadgeStyle(role.workMode)}`}
                            >
                                {formatWorkMode(role.workMode)}
                            </span>
                            <span className="rounded-lg bg-zinc-800/75 px-2 py-0.5 text-[11px] font-medium text-zinc-300">
                                {role.seniority}
                            </span>
                            <span className="rounded-lg bg-zinc-800/75 px-2 py-0.5 text-[11px] font-medium text-zinc-300">
                                {role.contract}
                            </span>
                            <span className="inline-flex items-center gap-1 rounded-lg bg-emerald-500/10 px-2 py-0.5 font-mono text-[11px] font-medium tabular-nums text-emerald-300 ring-1 ring-emerald-500/25">
                                <Banknote className="h-3 w-3" aria-hidden="true" />
                                {role.salary}
                            </span>
                            <span className="px-1 text-[11px] font-medium text-zinc-500">
                                {role.source}
                            </span>
                            <span className="inline-flex items-center gap-1 text-[11px] text-zinc-500">
                                <Clock className="h-3 w-3" aria-hidden="true" />
                                {role.postedAge}
                            </span>
                        </div>

                        <div>
                            <h3 className="text-base font-semibold leading-snug text-zinc-100">
                                {role.title}
                            </h3>
                            <div className="mt-1 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-zinc-400">
                                <span className="inline-flex items-center gap-1.5 font-medium text-zinc-300">
                                    <Building2 className="h-3.5 w-3.5 text-zinc-500" />
                                    {role.company}
                                </span>
                                <span className="inline-flex items-center gap-1.5">
                                    <MapPin className="h-3.5 w-3.5 text-zinc-500" />
                                    {role.location}
                                </span>
                            </div>
                        </div>

                        <div className="flex flex-wrap gap-1.5">
                            {role.stack.map((tag) => {
                                const isMatched = matchedSet.has(tag.toLowerCase());
                                return (
                                    <span
                                        key={tag}
                                        className={`rounded-lg border px-2.5 py-0.5 font-mono text-[11px] ${isMatched
                                                ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-200"
                                                : "border-zinc-800 bg-zinc-800/70 text-zinc-300"
                                            }`}
                                    >
                                        {tag}
                                    </span>
                                );
                            })}
                        </div>
                    </div>
                </div>

                <div className="flex flex-wrap shrink-0 items-center gap-2 xl:justify-end">
                    <button
                        type="button"
                        aria-label={`Hide role ${role.title}`}
                        onClick={() => onHide(role.id)}
                        className="inline-flex h-9 w-9 items-center justify-center rounded-xl border border-zinc-800 bg-zinc-900/80 text-zinc-400 transition hover:border-zinc-700 hover:bg-zinc-800 hover:text-zinc-100"
                    >
                        <EyeOff className="h-4 w-4" aria-hidden="true" />
                    </button>

                    <button
                        type="button"
                        onClick={onOpenGapDetails}
                        className="inline-flex h-9 items-center gap-1.5 rounded-xl border border-zinc-800 bg-zinc-900 px-3 text-xs font-medium text-zinc-300 transition hover:border-violet-500/40 hover:bg-zinc-800 hover:text-zinc-100"
                    >
                        <Sparkles className="h-3.5 w-3.5 text-violet-400" aria-hidden="true" />
                        <span>Gap Details</span>
                    </button>

                    <button
                        type="button"
                        onClick={() => onToggleSave(role.id)}
                        className={`inline-flex h-9 items-center gap-1.5 rounded-xl border px-3 text-xs font-medium transition ${isSaved
                                ? "border-emerald-500/30 bg-emerald-950/30 text-emerald-200"
                                : "border-zinc-700 bg-zinc-800/80 text-zinc-200 hover:bg-zinc-700"
                            }`}
                    >
                        {isSaved ? (
                            <BookmarkCheck
                                className="h-3.5 w-3.5 text-emerald-400"
                                aria-hidden="true"
                            />
                        ) : (
                            <BookmarkPlus
                                className="h-3.5 w-3.5 text-violet-400"
                                aria-hidden="true"
                            />
                        )}
                        <span>{isSaved ? "Saved" : "Save"}</span>
                    </button>

                    <button
                        type="button"
                        aria-pressed={isApplied}
                        onClick={() => onToggleApplied(role.id)}
                        className={`inline-flex h-9 items-center gap-1.5 rounded-xl px-3.5 text-xs font-medium transition ${isApplied
                                ? "border border-emerald-500/35 bg-emerald-500/15 text-emerald-200"
                                : "bg-violet-600 text-white shadow-sm shadow-violet-600/20 hover:bg-violet-500"
                            }`}
                    >
                        {isApplied ? (
                            <>
                                <Check className="h-3.5 w-3.5 text-emerald-400" aria-hidden="true" />
                                <span>Applied</span>
                            </>
                        ) : (
                            <>
                                <span>Apply</span>
                                <ExternalLink className="h-3.5 w-3.5" aria-hidden="true" />
                            </>
                        )}
                    </button>
                </div>
            </div>
        </article>
    );
}

export function CopilotPreviewPanel({
    onClose,
    backLabel = "Back",
}: Readonly<{ onClose?: () => void; backLabel?: string }> = {}) {
    const [mode, setMode] = useState<CopilotPreviewMode>("gap");
    const [artifactKind, setArtifactKind] = useState<CopilotArtifactKind>("tailored_bullets");
    const activeDraft = getCopilotPreviewDraft(artifactKind);

    return (
        <div className="overflow-hidden rounded-2xl border border-zinc-800/90 bg-zinc-950/90 ring-1 ring-inset ring-white/[0.03]">
            <div className="flex flex-col gap-3 border-b border-zinc-800/90 bg-zinc-900/60 px-5 py-4 sm:flex-row sm:items-center sm:justify-between">
                <div>
                    {onClose && (
                        <button
                            type="button"
                            onClick={onClose}
                            className="mb-2 inline-flex items-center gap-1.5 rounded-lg text-xs font-medium text-zinc-400 transition hover:text-zinc-100"
                        >
                            <ArrowLeft className="h-3.5 w-3.5" aria-hidden="true" />
                            <span>{backLabel}</span>
                        </button>
                    )}
                    <div className="flex flex-wrap items-center gap-2">
                        <span className="rounded-lg bg-violet-500/15 px-2.5 py-0.5 font-mono text-xs font-semibold text-violet-300 ring-1 ring-violet-500/35">
                            {GAP_ANALYSIS_PREVIEW.fitScore}% AI FIT
                        </span>
                        <span className="rounded-lg bg-zinc-800/80 px-2 py-0.5 font-mono text-xs text-zinc-300">
                            {GAP_ANALYSIS_PREVIEW.vectorPercent}% vector
                        </span>
                        <span
                            className={`rounded-lg px-2 py-0.5 text-xs font-medium ${workModeBadgeStyle(GAP_ANALYSIS_PREVIEW.workMode)}`}
                        >
                            {formatWorkMode(GAP_ANALYSIS_PREVIEW.workMode)}
                        </span>
                        <span className="rounded-lg bg-emerald-500/10 px-2 py-0.5 font-mono text-xs text-emerald-300 ring-1 ring-emerald-500/25">
                            {GAP_ANALYSIS_PREVIEW.salary}
                        </span>
                    </div>
                    <h3 className="mt-2 text-base font-semibold text-zinc-100">
                        {GAP_ANALYSIS_PREVIEW.roleTitle}
                    </h3>
                    <p className="mt-0.5 text-xs text-zinc-400">
                        {GAP_ANALYSIS_PREVIEW.company} · {GAP_ANALYSIS_PREVIEW.location} ·{" "}
                        {GAP_ANALYSIS_PREVIEW.source}
                    </p>
                </div>

                <div className="inline-flex self-start rounded-xl border border-zinc-800 bg-zinc-950 p-1 sm:self-center">
                    <button
                        type="button"
                        aria-pressed={mode === "gap"}
                        onClick={() => setMode("gap")}
                        className={`min-h-9 rounded-lg px-3.5 text-xs font-medium transition ${mode === "gap"
                                ? "bg-zinc-800 text-zinc-100 ring-1 ring-violet-500/40"
                                : "text-zinc-400 hover:text-zinc-100"
                            }`}
                    >
                        Gap Analysis
                    </button>
                    <button
                        type="button"
                        aria-pressed={mode === "copilot"}
                        onClick={() => setMode("copilot")}
                        className={`inline-flex min-h-9 items-center gap-1.5 rounded-lg px-3.5 text-xs font-medium transition ${mode === "copilot"
                                ? "bg-zinc-800 text-zinc-100 ring-1 ring-violet-500/40"
                                : "text-zinc-400 hover:text-zinc-100"
                            }`}
                    >
                        <Sparkles className="h-3.5 w-3.5 text-violet-400" aria-hidden="true" />
                        <span>AI Copilot</span>
                    </button>
                </div>
            </div>

            <div className="p-5">
                {mode === "gap" ? (
                    <div className="space-y-4">
                        <section className="rounded-2xl border border-zinc-800/90 bg-zinc-900/55 p-5 ring-1 ring-inset ring-white/[0.03]">
                            <div className="mb-3 flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-violet-300">
                                <Sparkles className="h-4 w-4" aria-hidden="true" />
                                <span>Fit Summary ({GAP_ANALYSIS_PREVIEW.scoringModel})</span>
                            </div>
                            <p className="text-sm font-medium leading-relaxed text-zinc-100">
                                {GAP_ANALYSIS_PREVIEW.summary}
                            </p>
                            <ul className="mt-3.5 space-y-2 border-t border-zinc-800/80 pt-3.5 text-xs leading-relaxed text-zinc-300">
                                {GAP_ANALYSIS_PREVIEW.highlights.map((point) => (
                                    <li key={point} className="flex items-start gap-2.5">
                                        <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-emerald-400" />
                                        <span>{point}</span>
                                    </li>
                                ))}
                            </ul>
                            <div className="mt-3.5 flex items-start gap-2 rounded-xl border border-amber-500/25 bg-amber-950/20 px-3.5 py-2.5 text-xs leading-relaxed text-amber-200/90">
                                <AlertCircle
                                    className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-400"
                                    aria-hidden="true"
                                />
                                <span>
                                    <strong className="font-semibold text-amber-200">Note:</strong>{" "}
                                    {GAP_ANALYSIS_PREVIEW.watchoutNote}
                                </span>
                            </div>
                        </section>

                        <div className="grid gap-4 md:grid-cols-2">
                            <div className="rounded-2xl border border-zinc-800/90 bg-zinc-900/50 p-4">
                                <div className="flex items-center gap-2 text-xs font-semibold text-emerald-300">
                                    <CheckCircle2 className="h-4 w-4" aria-hidden="true" />
                                    <span>Matched Skills</span>
                                </div>
                                <div className="mt-3 flex flex-wrap gap-1.5">
                                    {GAP_ANALYSIS_PREVIEW.matchedSkills.map((skill) => (
                                        <span
                                            key={skill}
                                            className="rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-2.5 py-1 font-mono text-xs text-emerald-200"
                                        >
                                            {skill}
                                        </span>
                                    ))}
                                </div>
                            </div>

                            <div className="rounded-2xl border border-zinc-800/90 bg-zinc-900/50 p-4">
                                <div className="flex items-center gap-2 text-xs font-semibold text-amber-300">
                                    <XCircle className="h-4 w-4" aria-hidden="true" />
                                    <span>Missing Keywords</span>
                                </div>
                                <div className="mt-3 flex flex-wrap gap-1.5">
                                    {GAP_ANALYSIS_PREVIEW.missingKeywords.map((keyword) => (
                                        <span
                                            key={keyword}
                                            className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-2.5 py-1 font-mono text-xs text-amber-200"
                                        >
                                            {keyword}
                                        </span>
                                    ))}
                                </div>
                            </div>
                        </div>
                    </div>
                ) : (
                    <div className="space-y-4">
                        <div className="flex flex-wrap items-center justify-between gap-2">
                            <div className="flex flex-wrap gap-1.5">
                                {COPILOT_DRAFTS_PREVIEW.map((draft) => {
                                    const active = draft.kind === artifactKind;
                                    return (
                                        <button
                                            key={draft.kind}
                                            type="button"
                                            aria-pressed={active}
                                            onClick={() => setArtifactKind(draft.kind)}
                                            className={`min-h-9 rounded-xl border px-3 text-xs font-medium transition ${active
                                                    ? "border-violet-500/45 bg-violet-500/15 text-violet-100"
                                                    : "border-zinc-800 bg-zinc-900 text-zinc-400 hover:border-zinc-700 hover:text-zinc-200"
                                                }`}
                                        >
                                            {draft.label}
                                        </button>
                                    );
                                })}
                            </div>
                            <span className="rounded-lg border border-zinc-800 bg-zinc-900 px-2.5 py-1 font-mono text-[11px] text-zinc-400">
                                Tone: {activeDraft.tone}
                            </span>
                        </div>

                        <div className="rounded-2xl border border-zinc-800/90 bg-zinc-900/55 p-5">
                            <p className="font-mono text-xs font-semibold text-violet-300">
                                {activeDraft.heading}
                            </p>
                            <ul className="mt-3 space-y-2.5 text-xs leading-relaxed text-zinc-200">
                                {activeDraft.lines.map((line) => (
                                    <li key={line} className="flex items-start gap-2.5">
                                        <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-violet-400" />
                                        <span>{line}</span>
                                    </li>
                                ))}
                            </ul>
                        </div>
                    </div>
                )}
            </div>
        </div>
    );
}

export function RadarPreviewPanel({
    initialQuery = "distributed python kafka pgvector",
}: Readonly<{ initialQuery?: string }> = {}) {
    const [filter, setFilter] = useState<RadarPreviewFilter>("all");
    const [hiddenIds, setHiddenIds] = useState<Set<string>>(() => new Set());
    const [savedIds, setSavedIds] = useState<Set<string>>(() => new Set(["role-2"]));
    const [appliedIds, setAppliedIds] = useState<Set<string>>(() => new Set());
    const [showingGapDrawer, setShowingGapDrawer] = useState(false);

    if (showingGapDrawer) {
        return (
            <CopilotPreviewPanel
                onClose={() => setShowingGapDrawer(false)}
                backLabel="Back to Job Radar"
            />
        );
    }

    const visibleRoles = filterRadarPreviewRoles(RADAR_PREVIEW_ROLES, filter, hiddenIds);

    function toggleSaved(roleId: string) {
        setSavedIds((prev) => {
            const next = new Set(prev);
            if (next.has(roleId)) {
                next.delete(roleId);
            } else {
                next.add(roleId);
            }
            return next;
        });
    }

    function toggleApplied(roleId: string) {
        setAppliedIds((prev) => {
            const next = new Set(prev);
            if (next.has(roleId)) {
                next.delete(roleId);
            } else {
                next.add(roleId);
            }
            return next;
        });
    }

    function hideRole(roleId: string) {
        setHiddenIds((prev) => new Set(prev).add(roleId));
    }

    return (
        <div className="space-y-4">
            <div className="flex flex-col gap-3 rounded-2xl border border-zinc-800/90 bg-zinc-900/50 p-3.5 lg:flex-row lg:items-center lg:justify-between">
                <div className="flex flex-1 items-center gap-2.5 rounded-xl border border-zinc-800 bg-zinc-950/90 px-3.5 py-2 text-xs text-zinc-300">
                    <Search className="h-4 w-4 shrink-0 text-zinc-500" aria-hidden="true" />
                    <span className="truncate font-mono text-zinc-200">{initialQuery}</span>
                    <span className="ml-auto shrink-0 rounded-md bg-violet-500/15 px-2 py-0.5 font-mono text-[10px] font-medium text-violet-300 ring-1 ring-violet-500/30">
                        Hybrid RRF
                    </span>
                </div>

                <div className="flex flex-wrap items-center gap-1.5">
                    <span className="inline-flex min-h-9 items-center gap-1.5 rounded-xl border border-zinc-800 bg-zinc-950/80 px-2.5 text-xs text-zinc-300">
                        <FileText className="h-3.5 w-3.5 text-violet-400" aria-hidden="true" />
                        <span>Senior Backend</span>
                    </span>
                    {RADAR_PREVIEW_FILTERS.map((item) => {
                        const active = filter === item.id;
                        return (
                            <button
                                key={item.id}
                                type="button"
                                aria-pressed={active}
                                onClick={() => setFilter(item.id)}
                                className={`min-h-9 rounded-xl border px-3 text-xs font-medium transition ${active
                                        ? "border-violet-500/45 bg-violet-500/15 text-violet-200"
                                        : "border-zinc-800 bg-zinc-950/60 text-zinc-400 hover:border-zinc-700 hover:text-zinc-200"
                                    }`}
                            >
                                {item.label}
                            </button>
                        );
                    })}
                    {hiddenIds.size > 0 && (
                        <button
                            type="button"
                            onClick={() => setHiddenIds(new Set())}
                            className="inline-flex min-h-9 items-center gap-1 rounded-xl border border-zinc-700 bg-zinc-900 px-3 text-xs text-zinc-300 transition hover:text-zinc-100"
                        >
                            <RotateCcw className="h-3 w-3" aria-hidden="true" />
                            <span>Restore ({hiddenIds.size})</span>
                        </button>
                    )}
                </div>
            </div>

            {visibleRoles.length === 0 ? (
                <div className="rounded-2xl border border-dashed border-zinc-800 bg-zinc-950/40 px-4 py-8 text-center text-sm text-zinc-400">
                    All sample roles are filtered or hidden. Switch filters or restore hidden roles
                    above.
                </div>
            ) : (
                <div className="space-y-3">
                    {visibleRoles.map((role) => (
                        <RadarPreviewCard
                            key={role.id}
                            role={role}
                            isSaved={savedIds.has(role.id)}
                            isApplied={appliedIds.has(role.id)}
                            onToggleSave={toggleSaved}
                            onToggleApplied={toggleApplied}
                            onHide={hideRole}
                            onOpenGapDetails={() => setShowingGapDrawer(true)}
                        />
                    ))}
                </div>
            )}
        </div>
    );
}

export function TrackerPreviewPanel() {
    const [priorities, setPriorities] = useState<Record<string, KanbanPriority>>({});
    const [showingGapDrawer, setShowingGapDrawer] = useState(false);

    if (showingGapDrawer) {
        return (
            <CopilotPreviewPanel
                onClose={() => setShowingGapDrawer(false)}
                backLabel="Back to Pipeline Tracker"
            />
        );
    }

    function handleCyclePriority(cardId: string, fallback: KanbanPriority) {
        setPriorities((prev) => ({
            ...prev,
            [cardId]: cyclePreviewPriority(prev[cardId] ?? fallback),
        }));
    }

    return (
        <div className="space-y-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="flex items-center gap-2.5">
                    <span className="text-sm font-semibold text-zinc-100">Pipeline Tracker</span>
                    <span className="rounded-lg border border-zinc-800 bg-zinc-900 px-2 py-0.5 font-mono text-[11px] text-zinc-400">
                        5 active leads
                    </span>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                    <span className="inline-flex items-center gap-1 rounded-lg border border-zinc-800 bg-zinc-900/70 px-2 py-1 text-[11px] text-zinc-400">
                        <Download className="h-3 w-3 text-violet-400" aria-hidden="true" />
                        <span>CSV / JSON</span>
                    </span>
                    <span className="text-[11px] text-zinc-500">
                        Click priorities or Sparkles for Gap &amp; Copilot
                    </span>
                </div>
            </div>

            <div className="pipeline-scroll overflow-x-auto pb-2">
                <div className="grid min-w-[960px] grid-cols-5 gap-3">
                    {KANBAN_PREVIEW_COLUMNS.map((column) => (
                        <div
                            key={column.id}
                            className={`min-w-0 rounded-2xl border border-zinc-800/90 border-t-2 bg-zinc-900/45 p-3 ${column.topBorderClass}`}
                        >
                            <div className="flex items-center justify-between pb-2.5">
                                <div className="flex items-center gap-2">
                                    <span
                                        className={`h-2 w-2 rounded-full ${column.dotClass}`}
                                        aria-hidden="true"
                                    />
                                    <span className="text-xs font-semibold text-zinc-200">
                                        {column.label}
                                    </span>
                                </div>
                                <span className="rounded-md bg-zinc-800/90 px-1.5 py-0.5 font-mono text-[11px] text-zinc-400">
                                    {column.cards.length}
                                </span>
                            </div>

                            <div className="space-y-2.5">
                                {column.cards.map((card) => {
                                    const priority = priorities[card.id] ?? card.priority;
                                    return (
                                        <div
                                            key={card.id}
                                            className={`min-w-0 overflow-hidden rounded-xl border p-3 ${card.overdue
                                                    ? "border-amber-500/45 bg-amber-950/20"
                                                    : "border-zinc-800/90 bg-zinc-950/80"
                                                }`}
                                        >
                                            <div className="flex flex-wrap items-center justify-between gap-1.5">
                                                <div className="flex flex-wrap items-center gap-1">
                                                    <span className="rounded-md bg-violet-500/15 px-1.5 py-0.5 font-mono text-[11px] font-semibold text-violet-300 ring-1 ring-violet-500/35">
                                                        {card.fitScore}%
                                                    </span>
                                                    <span
                                                        className={`rounded-md px-1.5 py-0.5 text-[10px] font-medium ${workModeBadgeStyle(card.workMode)}`}
                                                    >
                                                        {formatWorkMode(card.workMode)}
                                                    </span>
                                                </div>
                                                <button
                                                    type="button"
                                                    onClick={() =>
                                                        handleCyclePriority(card.id, card.priority)
                                                    }
                                                    title="Click to cycle priority"
                                                    className={`shrink-0 cursor-pointer rounded-md px-1.5 py-0.5 text-[10px] font-medium capitalize transition ${PRIORITY_BADGE_STYLES[priority]}`}
                                                >
                                                    {priority}
                                                </button>
                                            </div>
                                            <p className="mt-2.5 text-xs font-semibold leading-snug text-zinc-100">
                                                {card.title}
                                            </p>
                                            <p className="mt-0.5 truncate text-[11px] text-zinc-400">
                                                {card.company}
                                            </p>
                                            <div className="mt-1.5 flex items-center justify-between gap-2">
                                                <p className="min-w-0 truncate font-mono text-[11px] text-emerald-300/90">
                                                    {card.salary}
                                                </p>
                                                <button
                                                    type="button"
                                                    onClick={() => setShowingGapDrawer(true)}
                                                    aria-label={`Open gap analysis for ${card.title}`}
                                                    className="inline-flex shrink-0 rounded-md p-1 text-zinc-400 transition hover:bg-violet-500/15 hover:text-violet-300"
                                                >
                                                    <Sparkles
                                                        className="h-3.5 w-3.5"
                                                        aria-hidden="true"
                                                    />
                                                </button>
                                            </div>
                                            {card.followupLabel && (
                                                <p
                                                    className={`mt-2 inline-flex max-w-full items-center gap-1 rounded-lg px-2 py-1 text-[10px] font-medium ${card.overdue
                                                            ? "bg-amber-500/15 text-amber-200 ring-1 ring-amber-500/30"
                                                            : "bg-zinc-900 text-zinc-300 ring-1 ring-zinc-800"
                                                        }`}
                                                >
                                                    {card.overdue ? (
                                                        <AlertTriangle
                                                            className="h-3 w-3 shrink-0 text-amber-400"
                                                            aria-hidden="true"
                                                        />
                                                    ) : (
                                                        <CalendarClock
                                                            className="h-3 w-3 shrink-0 text-violet-400"
                                                            aria-hidden="true"
                                                        />
                                                    )}
                                                    <span className="truncate">
                                                        {card.followupLabel}
                                                    </span>
                                                </p>
                                            )}
                                        </div>
                                    );
                                })}
                            </div>
                        </div>
                    ))}
                </div>
            </div>
        </div>
    );
}

function StackVelocityPreviewChart() {
    const [pinnedTech, setPinnedTech] = useState<string | null>(null);
    const chartWidth = 560;
    const chartHeight = 148;
    const padLeft = 34;
    const padRight = 16;
    const padTop = 14;
    const padBottom = 26;
    const innerWidth = chartWidth - padLeft - padRight;
    const innerHeight = chartHeight - padTop - padBottom;
    const maxVal = 160;

    const xFor = (idx: number) =>
        padLeft + (idx / Math.max(1, STACK_VELOCITY_DATES.length - 1)) * innerWidth;
    const yFor = (val: number) => padTop + innerHeight - (val / maxVal) * innerHeight;

    return (
        <section className="space-y-3 rounded-2xl border border-zinc-800/90 bg-zinc-900/50 p-4 ring-1 ring-inset ring-white/[0.03] sm:p-5">
            <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex items-center gap-2">
                    <TrendingUp className="h-4 w-4 text-violet-400" aria-hidden="true" />
                    <h4 className="text-xs font-semibold text-zinc-100">
                        Daily Mention Velocity (Top 4 Stacks)
                    </h4>
                </div>
                <div className="flex flex-wrap items-center gap-1.5">
                    {STACK_VELOCITY_SERIES.map((series) => {
                        const active = pinnedTech === series.tech;
                        return (
                            <button
                                key={series.tech}
                                type="button"
                                aria-pressed={active}
                                onClick={() =>
                                    setPinnedTech((prev) =>
                                        prev === series.tech ? null : series.tech,
                                    )
                                }
                                className={`inline-flex items-center gap-1.5 rounded-lg border px-2 py-0.5 font-mono text-[11px] transition ${
                                    active
                                        ? "border-violet-500/45 bg-violet-500/15 text-zinc-100"
                                        : "border-zinc-800 bg-zinc-950/75 text-zinc-400 hover:text-zinc-200"
                                }`}
                            >
                                <span
                                    className={`h-2 w-2 rounded-full ${series.dotClass}`}
                                    aria-hidden="true"
                                />
                                <span>{series.tech}</span>
                            </button>
                        );
                    })}
                </div>
            </div>

            <div className="w-full overflow-x-auto">
                <svg
                    viewBox={`0 0 ${chartWidth} ${chartHeight}`}
                    className="h-36 w-full min-w-[340px]"
                    aria-label="Daily stack mention velocity over 5 days"
                >
                    <title>Daily stack mention velocity over 5 days</title>
                    {[0, 40, 80, 120, 160].map((tick) => {
                        const y = yFor(tick);
                        return (
                            <g key={tick}>
                                <line
                                    x1={padLeft}
                                    y1={y}
                                    x2={chartWidth - padRight}
                                    y2={y}
                                    stroke="#27272a"
                                    strokeDasharray="3 3"
                                />
                                <text
                                    x={padLeft - 6}
                                    y={y + 3}
                                    textAnchor="end"
                                    fill="#71717a"
                                    fontSize="9"
                                    fontFamily="monospace"
                                >
                                    {tick}
                                </text>
                            </g>
                        );
                    })}
                    {STACK_VELOCITY_DATES.map((label, idx) => (
                        <text
                            key={label}
                            x={xFor(idx)}
                            y={chartHeight - 6}
                            textAnchor="middle"
                            fill="#71717a"
                            fontSize="9"
                            fontFamily="monospace"
                        >
                            {label}
                        </text>
                    ))}
                    {STACK_VELOCITY_SERIES.map((series) => {
                        const dimmed = pinnedTech !== null && pinnedTech !== series.tech;
                        const d = series.points
                            .map((val, idx) => `${idx === 0 ? "M" : "L"}${xFor(idx)} ${yFor(val)}`)
                            .join(" ");
                        return (
                            <g key={series.tech} opacity={dimmed ? 0.2 : 0.95}>
                                <path
                                    d={d}
                                    fill="none"
                                    stroke={series.color}
                                    strokeWidth={pinnedTech === series.tech ? 2.6 : 2}
                                    strokeLinecap="round"
                                    strokeLinejoin="round"
                                />
                                {series.points.map((val, idx) => (
                                    <circle
                                        key={`${series.tech}-${STACK_VELOCITY_DATES[idx]}`}
                                        cx={xFor(idx)}
                                        cy={yFor(val)}
                                        r={2.8}
                                        fill={series.color}
                                    />
                                ))}
                            </g>
                        );
                    })}
                </svg>
            </div>
        </section>
    );
}

function MarketTrendsSubPanel() {
    const [category, setCategory] = useState<StackCategoryFilter>("all");
    const [sortField, setSortField] = useState<StackSortField>("mentions");

    const filteredRows = STACK_DEMAND_PREVIEW.filter(
        (row) => category === "all" || row.category === category,
    ).sort((a, b) => b[sortField] - a[sortField]);

    const totalMentions = filteredRows.reduce((sum, row) => sum + row.mentions, 0);
    const topTag = filteredRows[0]?.tech ?? "—";
    const avgComp =
        filteredRows.length > 0
            ? `$${Math.round(
                  filteredRows.reduce((sum, row) => sum + row.medianUsdValue, 0) /
                      filteredRows.length /
                      1000,
              )}k`
            : "—";

    return (
        <div className="space-y-4">
            <div className="grid grid-cols-3 gap-2.5 sm:gap-3">
                <div className="rounded-xl border border-zinc-800/90 bg-zinc-900/50 px-3.5 py-2.5">
                    <p className="text-[10px] font-medium uppercase tracking-wider text-zinc-400">
                        Top Demand
                    </p>
                    <p className="mt-1 font-mono text-sm font-semibold text-violet-300">{topTag}</p>
                </div>
                <div className="rounded-xl border border-zinc-800/90 bg-zinc-900/50 px-3.5 py-2.5">
                    <p className="text-[10px] font-medium uppercase tracking-wider text-zinc-400">
                        Total Mentions
                    </p>
                    <p className="mt-1 font-mono text-sm font-semibold tabular-nums text-zinc-100">
                        {totalMentions}
                    </p>
                </div>
                <div className="rounded-xl border border-zinc-800/90 bg-zinc-900/50 px-3.5 py-2.5">
                    <p className="text-[10px] font-medium uppercase tracking-wider text-zinc-400">
                        Avg Median USD
                    </p>
                    <p className="mt-1 font-mono text-sm font-semibold tabular-nums text-emerald-300">
                        {avgComp}
                    </p>
                </div>
            </div>

            <StackVelocityPreviewChart />

            <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex flex-wrap items-center gap-1.5">
                    {STACK_CATEGORY_FILTERS.map((item) => {
                        const active = category === item.id;
                        return (
                            <button
                                key={item.id}
                                type="button"
                                aria-pressed={active}
                                onClick={() => setCategory(item.id)}
                                className={`rounded-lg border px-2.5 py-1 text-xs font-medium transition ${
                                    active
                                        ? "border-violet-500/45 bg-violet-500/15 text-violet-200"
                                        : "border-zinc-800 bg-zinc-950/70 text-zinc-400 hover:border-zinc-700 hover:text-zinc-200"
                                }`}
                            >
                                {item.label}
                            </button>
                        );
                    })}
                </div>
                <div className="inline-flex items-center gap-1 rounded-lg border border-zinc-800 bg-zinc-950/80 p-0.5 text-[11px]">
                    <button
                        type="button"
                        aria-pressed={sortField === "mentions"}
                        onClick={() => setSortField("mentions")}
                        className={`inline-flex items-center gap-1 rounded-md px-2 py-1 font-medium transition ${
                            sortField === "mentions"
                                ? "bg-zinc-800 text-zinc-100"
                                : "text-zinc-400 hover:text-zinc-200"
                        }`}
                    >
                        <ArrowDown className="h-3 w-3 text-violet-400" aria-hidden="true" />
                        <span>Mentions</span>
                    </button>
                    <button
                        type="button"
                        aria-pressed={sortField === "medianUsdValue"}
                        onClick={() => setSortField("medianUsdValue")}
                        className={`inline-flex items-center gap-1 rounded-md px-2 py-1 font-medium transition ${
                            sortField === "medianUsdValue"
                                ? "bg-zinc-800 text-zinc-100"
                                : "text-zinc-400 hover:text-zinc-200"
                        }`}
                    >
                        <ArrowDown className="h-3 w-3 text-emerald-400" aria-hidden="true" />
                        <span>Median Comp</span>
                    </button>
                </div>
            </div>

            <section className="overflow-hidden rounded-2xl border border-zinc-800/90 bg-zinc-900/50 ring-1 ring-inset ring-white/[0.03]">
                <div className="divide-y divide-zinc-800/70">
                    {filteredRows.map((row, idx) => (
                        <div
                            key={row.tech}
                            className="flex flex-col gap-2 px-4 py-3 text-xs sm:flex-row sm:items-center sm:justify-between sm:gap-3 sm:px-5"
                        >
                            <div className="flex min-w-0 items-center gap-2.5 sm:gap-3">
                                <span className="w-5 font-mono text-[11px] font-semibold text-zinc-500">
                                    #{idx + 1}
                                </span>
                                <span className="font-mono font-semibold text-zinc-100">
                                    {row.tech}
                                </span>
                                <span
                                    className={`rounded-md px-2 py-0.5 text-[10px] font-medium ring-1 ring-inset ${row.categoryClass}`}
                                >
                                    {row.category}
                                </span>
                            </div>

                            <div className="flex flex-wrap items-center gap-3 sm:gap-4">
                                <div className="flex w-24 items-center sm:w-28 md:w-32">
                                    <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-zinc-800">
                                        <div
                                            className="h-full rounded-full bg-gradient-to-r from-violet-500 to-sky-400"
                                            style={{ width: `${row.barPct}%` }}
                                        />
                                    </div>
                                </div>
                                <span className="font-mono tabular-nums text-zinc-300">
                                    {row.mentions} roles
                                </span>
                                <span className="font-mono tabular-nums text-zinc-500">
                                    {row.companies} cos
                                </span>
                                <span className="ml-auto font-mono font-medium tabular-nums text-emerald-300 sm:ml-0 sm:w-20 sm:text-right">
                                    {row.medianUsd}
                                </span>
                            </div>
                        </div>
                    ))}
                </div>
            </section>
        </div>
    );
}

function PersonalPipelineSubPanel({
    onSearchSkillInRadar,
}: Readonly<{ onSearchSkillInRadar?: (skill: string) => void }>) {
    const [windowOpt, setWindowOpt] = useState<PersonalWindowOption>("30d");
    const snapshot = PERSONAL_WINDOW_SNAPSHOTS[windowOpt];

    return (
        <div className="space-y-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="inline-flex items-center gap-1.5 rounded-xl border border-zinc-800 bg-zinc-950/80 px-2.5 py-1.5 text-xs text-zinc-300">
                    <FileText className="h-3.5 w-3.5 text-violet-400" aria-hidden="true" />
                    <span>Senior Backend</span>
                </div>
                <div className="inline-flex rounded-xl border border-zinc-800 bg-zinc-950 p-0.5 text-xs">
                    {(["7d", "30d", "90d"] as const).map((opt) => (
                        <button
                            key={opt}
                            type="button"
                            aria-pressed={windowOpt === opt}
                            onClick={() => setWindowOpt(opt)}
                            className={`rounded-lg px-2.5 py-1 font-mono text-[11px] font-medium transition ${
                                windowOpt === opt
                                    ? "bg-zinc-800 text-zinc-100"
                                    : "text-zinc-400 hover:text-zinc-200"
                            }`}
                        >
                            {opt}
                        </button>
                    ))}
                </div>
            </div>

            <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-4 sm:gap-3">
                <div className="rounded-xl border border-zinc-800/90 bg-zinc-900/50 px-3.5 py-2.5">
                    <p className="text-[10px] font-medium uppercase tracking-wider text-zinc-400">
                        Tracked
                    </p>
                    <p className="mt-1 font-mono text-base font-semibold tabular-nums text-zinc-100">
                        {snapshot.tracked}
                    </p>
                </div>
                <div className="rounded-xl border border-sky-500/20 bg-sky-950/15 px-3.5 py-2.5">
                    <p className="text-[10px] font-medium uppercase tracking-wider text-sky-300/80">
                        Response Rate
                    </p>
                    <p className="mt-1 font-mono text-base font-semibold tabular-nums text-sky-300">
                        {snapshot.responseRate}
                    </p>
                </div>
                <div className="rounded-xl border border-violet-500/20 bg-violet-950/15 px-3.5 py-2.5">
                    <p className="text-[10px] font-medium uppercase tracking-wider text-violet-300/80">
                        Interview Rate
                    </p>
                    <p className="mt-1 font-mono text-base font-semibold tabular-nums text-violet-300">
                        {snapshot.interviewRate}
                    </p>
                </div>
                <div className="rounded-xl border border-emerald-500/20 bg-emerald-950/15 px-3.5 py-2.5">
                    <p className="text-[10px] font-medium uppercase tracking-wider text-emerald-300/80">
                        Offers
                    </p>
                    <p className="mt-1 font-mono text-base font-semibold tabular-nums text-emerald-300">
                        {snapshot.offers}
                    </p>
                </div>
            </div>

            <div className="grid gap-4 lg:grid-cols-12">
                <section className="space-y-4 rounded-2xl border border-zinc-800/90 bg-zinc-900/50 p-4 ring-1 ring-inset ring-white/[0.03] sm:p-5 lg:col-span-7">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                        <div className="flex items-center gap-2">
                            <TrendingUp className="h-4 w-4 text-violet-400" aria-hidden="true" />
                            <h4 className="text-sm font-semibold text-zinc-100">
                                Application Funnel
                            </h4>
                        </div>
                        <div className="flex flex-wrap items-center gap-1.5 font-mono text-[11px]">
                            <span className="rounded-lg border border-red-500/20 bg-red-950/20 px-2 py-0.5 text-red-300">
                                Rejected: {snapshot.rejected}
                            </span>
                            <span className="rounded-lg border border-zinc-800 bg-zinc-950/70 px-2 py-0.5 text-zinc-400">
                                Withdrawn: {snapshot.withdrawn}
                            </span>
                            <span className="rounded-lg border border-zinc-800 bg-zinc-950/70 px-2 py-0.5 text-zinc-400">
                                {snapshot.label}
                            </span>
                        </div>
                    </div>

                    <div className="space-y-3">
                        {snapshot.funnel.map((stage) => (
                            <div key={stage.key} className="space-y-1">
                                <div className="flex items-center justify-between text-xs">
                                    <span className="font-medium text-zinc-200">{stage.label}</span>
                                    <div className="flex items-center gap-3 font-mono tabular-nums">
                                        {stage.conversionPct && (
                                            <span className="text-[11px] text-zinc-400">
                                                {stage.conversionPct} from prev
                                            </span>
                                        )}
                                        <span className="w-6 text-right font-semibold text-zinc-100">
                                            {stage.count}
                                        </span>
                                    </div>
                                </div>
                                <div className="h-2 w-full overflow-hidden rounded-full bg-zinc-800/90">
                                    <div
                                        className={`h-full rounded-full bg-gradient-to-r ${stage.barGradient}`}
                                        style={{ width: `${stage.widthPct}%` }}
                                    />
                                </div>
                            </div>
                        ))}
                    </div>
                </section>

                <section className="space-y-3 rounded-2xl border border-zinc-800/90 bg-zinc-900/50 p-4 ring-1 ring-inset ring-white/[0.03] sm:p-5 lg:col-span-5">
                    <div className="flex items-center gap-2">
                        <Layers className="h-4 w-4 text-sky-400" aria-hidden="true" />
                        <h4 className="text-sm font-semibold text-zinc-100">
                            Performance by ATS Source
                        </h4>
                    </div>
                    <div className="overflow-x-auto">
                        <table className="w-full border-collapse text-left text-xs">
                            <thead>
                                <tr className="border-b border-zinc-800 text-[10px] uppercase tracking-wider text-zinc-400">
                                    <th className="pb-2 pr-2">Channel</th>
                                    <th className="pb-2 px-1.5 text-right">Applied</th>
                                    <th className="pb-2 px-1.5 text-right">Resp</th>
                                    <th className="pb-2 pl-1.5 text-right">Intv</th>
                                </tr>
                            </thead>
                            <tbody className="divide-y divide-zinc-800/70">
                                {CHANNEL_PERFORMANCE_PREVIEW.map((row) => (
                                    <tr key={row.source}>
                                        <td className="py-2 pr-2 font-medium text-zinc-200">
                                            {row.source}
                                        </td>
                                        <td className="py-2 px-1.5 text-right font-mono tabular-nums text-zinc-300">
                                            {row.applied}
                                        </td>
                                        <td className="py-2 px-1.5 text-right font-mono tabular-nums text-sky-300">
                                            {row.responsePct}
                                        </td>
                                        <td className="py-2 pl-1.5 text-right font-mono tabular-nums text-emerald-300">
                                            {row.interviewPct}
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                </section>
            </div>

            <div className="grid gap-4 lg:grid-cols-2">
                <section className="space-y-3 rounded-2xl border border-zinc-800/90 bg-zinc-900/50 p-4 ring-1 ring-inset ring-white/[0.03] sm:p-5">
                    <div className="flex items-center gap-2">
                        <AlertCircle className="h-4 w-4 text-amber-400" aria-hidden="true" />
                        <h4 className="text-sm font-semibold text-zinc-100">
                            Top Missing Keywords
                        </h4>
                    </div>
                    <div className="space-y-2">
                        {SKILL_GAP_BARS_PREVIEW.map((item) => (
                            <button
                                key={item.skill}
                                type="button"
                                onClick={() => onSearchSkillInRadar?.(item.skill)}
                                className="group block w-full rounded-xl border border-zinc-800/80 bg-zinc-950/65 px-3 py-2 text-left transition hover:border-violet-500/45 hover:bg-zinc-900/80"
                            >
                                <div className="flex items-center justify-between gap-2 text-xs">
                                    <span className="rounded-md border border-amber-500/25 bg-amber-500/10 px-2 py-0.5 font-mono text-[11px] font-medium text-amber-200">
                                        {item.skill}
                                    </span>
                                    <span className="inline-flex items-center gap-1.5 font-mono text-[11px] text-zinc-400">
                                        <span>
                                            {item.mentions} roles · {item.sharePct}%
                                        </span>
                                        <ArrowUpRight
                                            className="h-3.5 w-3.5 text-zinc-500 transition group-hover:text-violet-300"
                                            aria-hidden="true"
                                        />
                                    </span>
                                </div>
                                <div className="mt-1.5 h-1.5 w-full overflow-hidden rounded-full bg-zinc-800">
                                    <div
                                        className="h-full rounded-full bg-gradient-to-r from-amber-500 to-orange-400"
                                        style={{ width: `${item.sharePct}%` }}
                                    />
                                </div>
                            </button>
                        ))}
                    </div>
                </section>

                <section className="space-y-3 rounded-2xl border border-zinc-800/90 bg-zinc-900/50 p-4 ring-1 ring-inset ring-white/[0.03] sm:p-5">
                    <div className="flex items-center gap-2">
                        <CheckCircle2 className="h-4 w-4 text-emerald-400" aria-hidden="true" />
                        <h4 className="text-sm font-semibold text-zinc-100">
                            Top Matched Strengths
                        </h4>
                    </div>
                    <div className="space-y-2">
                        {MATCHED_STRENGTHS_PREVIEW.map((item) => (
                            <button
                                key={item.skill}
                                type="button"
                                onClick={() => onSearchSkillInRadar?.(item.skill)}
                                className="group block w-full rounded-xl border border-zinc-800/80 bg-zinc-950/65 px-3 py-2 text-left transition hover:border-violet-500/45 hover:bg-zinc-900/80"
                            >
                                <div className="flex items-center justify-between gap-2 text-xs">
                                    <span className="rounded-md border border-emerald-500/25 bg-emerald-500/10 px-2 py-0.5 font-mono text-[11px] font-medium text-emerald-200">
                                        {item.skill}
                                    </span>
                                    <span className="inline-flex items-center gap-1.5 font-mono text-[11px] text-zinc-400">
                                        <span>
                                            {item.mentions} roles · {item.sharePct}%
                                        </span>
                                        <ArrowUpRight
                                            className="h-3.5 w-3.5 text-zinc-500 transition group-hover:text-violet-300"
                                            aria-hidden="true"
                                        />
                                    </span>
                                </div>
                                <div className="mt-1.5 h-1.5 w-full overflow-hidden rounded-full bg-zinc-800">
                                    <div
                                        className="h-full rounded-full bg-gradient-to-r from-emerald-500 to-teal-400"
                                        style={{ width: `${item.sharePct}%` }}
                                    />
                                </div>
                            </button>
                        ))}
                    </div>
                </section>
            </div>
        </div>
    );
}

export function AnalyticsPreviewPanel({
    initialSubTab = "market",
    onSearchSkillInRadar,
}: Readonly<{
    initialSubTab?: AnalyticsPreviewSubTab;
    onSearchSkillInRadar?: (skill: string) => void;
}> = {}) {
    const [subTab, setSubTab] = useState<AnalyticsPreviewSubTab>(initialSubTab);

    return (
        <div className="space-y-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                    <h3 className="text-sm font-semibold text-zinc-100">
                        {subTab === "market" ? "Stack Trends" : "My Pipeline & Skill Gaps"}
                    </h3>
                    <p className="text-xs text-zinc-400">
                        {subTab === "market"
                            ? "Daily market demand, company adoption, and median annual compensation."
                            : "Personal application funnel, ATS channel conversion, and click-to-search skill gaps."}
                    </p>
                </div>

                <div className="inline-flex rounded-xl border border-zinc-800 bg-zinc-950 p-1">
                    <button
                        type="button"
                        aria-pressed={subTab === "market"}
                        onClick={() => setSubTab("market")}
                        className={`inline-flex min-h-8 items-center gap-1.5 rounded-lg px-3 text-xs font-medium transition ${
                            subTab === "market"
                                ? "bg-zinc-800 text-zinc-100 ring-1 ring-violet-500/40"
                                : "text-zinc-400 hover:text-zinc-100"
                        }`}
                    >
                        <BarChart3 className="h-3.5 w-3.5 text-violet-400" aria-hidden="true" />
                        <span>Market Trends</span>
                    </button>
                    <button
                        type="button"
                        aria-pressed={subTab === "personal"}
                        onClick={() => setSubTab("personal")}
                        className={`inline-flex min-h-8 items-center gap-1.5 rounded-lg px-3 text-xs font-medium transition ${
                            subTab === "personal"
                                ? "bg-zinc-800 text-zinc-100 ring-1 ring-violet-500/40"
                                : "text-zinc-400 hover:text-zinc-100"
                        }`}
                    >
                        <Target className="h-3.5 w-3.5 text-violet-400" aria-hidden="true" />
                        <span>My Pipeline</span>
                    </button>
                </div>
            </div>

            {subTab === "market" ? (
                <MarketTrendsSubPanel />
            ) : (
                <PersonalPipelineSubPanel onSearchSkillInRadar={onSearchSkillInRadar} />
            )}
        </div>
    );
}

export function ResumesPreviewPanel() {
    const [workModesById, setWorkModesById] = useState<Record<string, WorkMode[]>>(() =>
        Object.fromEntries(
            RESUME_PROFILES_PREVIEW.map((profile) => [profile.id, profile.targetWorkModes]),
        ),
    );
    const [rescoreNoticeId, setRescoreNoticeId] = useState<string | null>(null);

    function toggleWorkMode(profileId: string, mode: WorkMode) {
        setWorkModesById((prev) => {
            const current = prev[profileId] ?? [];
            const next = current.includes(mode)
                ? current.filter((item) => item !== mode)
                : [...current, mode];
            return { ...prev, [profileId]: next };
        });
        setRescoreNoticeId(profileId);
    }

    return (
        <div className="space-y-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                    <h3 className="text-sm font-semibold text-zinc-100">Resume Profiles</h3>
                    <p className="text-xs text-zinc-400">
                        Configure target work modes, regions, seniority, and alert thresholds per
                        resume.
                    </p>
                </div>
                <span className="inline-flex items-center gap-1.5 rounded-lg border border-violet-500/30 bg-violet-500/10 px-2.5 py-1 font-mono text-[11px] text-violet-200">
                    <Sparkles className="h-3.5 w-3.5 text-violet-400" aria-hidden="true" />
                    <span>BYOK Gemini 3.5/4 Ready</span>
                </span>
            </div>

            <div className="grid gap-4 lg:grid-cols-2">
                {RESUME_PROFILES_PREVIEW.map((profile) => {
                    const selectedModes = workModesById[profile.id] ?? profile.targetWorkModes;
                    return (
                        <article
                            key={profile.id}
                            className="flex flex-col justify-between space-y-4 rounded-2xl border border-zinc-800/90 bg-zinc-900/50 p-4 ring-1 ring-inset ring-white/[0.03] sm:p-5"
                        >
                            <div className="space-y-3">
                                <div className="flex items-start justify-between gap-2">
                                    <div>
                                        <div className="flex items-center gap-2">
                                            <h4 className="text-sm font-semibold text-zinc-100">
                                                {profile.label}
                                            </h4>
                                            <span className="rounded-md bg-emerald-500/15 px-2 py-0.5 text-[10px] font-semibold text-emerald-300 ring-1 ring-emerald-500/30">
                                                Active
                                            </span>
                                        </div>
                                        <p className="mt-1 font-mono text-[11px] text-zinc-500">
                                            Alert &gt;= {profile.alertThreshold}% · Updated{" "}
                                            {profile.updatedAt}
                                        </p>
                                    </div>
                                </div>

                                <div className="space-y-1.5">
                                    <p className="text-[11px] font-medium uppercase tracking-wider text-zinc-400">
                                        Target Work Modes{" "}
                                        <span className="normal-case text-zinc-500">
                                            (click to toggle)
                                        </span>
                                    </p>
                                    <div className="flex flex-wrap gap-1.5">
                                        {PREVIEW_WORK_MODE_OPTIONS.map((opt) => {
                                            const active = selectedModes.includes(opt.value);
                                            return (
                                                <button
                                                    key={opt.value}
                                                    type="button"
                                                    aria-pressed={active}
                                                    onClick={() =>
                                                        toggleWorkMode(profile.id, opt.value)
                                                    }
                                                    className={`rounded-lg border px-2.5 py-1 text-xs font-medium transition ${active
                                                            ? "border-violet-500/50 bg-violet-500/15 text-violet-200"
                                                            : "border-zinc-800 bg-zinc-950/70 text-zinc-500 hover:border-zinc-700 hover:text-zinc-300"
                                                        }`}
                                                >
                                                    {opt.label}
                                                </button>
                                            );
                                        })}
                                    </div>
                                    {rescoreNoticeId === profile.id && (
                                        <p className="font-mono text-[11px] text-violet-300">
                                            {selectedModes.length === 0
                                                ? "Unrestricted work modes · jobs.rescore queued (no re-embedding)"
                                                : `Targeting ${selectedModes.map(formatWorkMode).join(", ")} · jobs.rescore queued (no re-embedding)`}
                                        </p>
                                    )}
                                </div>

                                <div className="flex flex-wrap gap-1.5 text-[11px]">
                                    {profile.targetRegions.map((region) => (
                                        <span
                                            key={region}
                                            className="rounded-md bg-sky-500/10 px-2 py-0.5 text-sky-300 ring-1 ring-sky-500/25"
                                        >
                                            {region}
                                        </span>
                                    ))}
                                    {profile.targetSeniority.map((level) => (
                                        <span
                                            key={level}
                                            className="rounded-md bg-zinc-800/80 px-2 py-0.5 text-zinc-300"
                                        >
                                            {level}
                                        </span>
                                    ))}
                                    {profile.targetContracts.map((contract) => (
                                        <span
                                            key={contract}
                                            className="rounded-md bg-zinc-800/80 px-2 py-0.5 text-zinc-300"
                                        >
                                            {contract}
                                        </span>
                                    ))}
                                </div>
                            </div>

                            <div className="flex flex-wrap gap-1.5 border-t border-zinc-800/80 pt-3">
                                {profile.extractedSkills.map((skill) => (
                                    <span
                                        key={skill}
                                        className="rounded-md border border-zinc-800 bg-zinc-950/80 px-2 py-0.5 font-mono text-[11px] text-zinc-300"
                                    >
                                        {skill}
                                    </span>
                                ))}
                            </div>
                        </article>
                    );
                })}
            </div>
        </div>
    );
}

export function PipelineStatusPreviewCard({
    onClose,
}: Readonly<{ onClose?: () => void }> = {}) {
    return (
        <section className="mb-4 space-y-3 rounded-2xl border border-zinc-800 bg-zinc-900/90 p-4 ring-1 ring-inset ring-white/[0.04]">
            <div className="flex items-center justify-between gap-2">
                <div className="flex items-center gap-2">
                    <Activity className="h-4 w-4 text-emerald-400" aria-hidden="true" />
                    <h3 className="text-xs font-semibold text-zinc-100">Pipeline Status</h3>
                    <span className="rounded-md bg-emerald-500/15 px-2 py-0.5 font-mono text-[10px] font-medium text-emerald-300 ring-1 ring-emerald-500/30">
                        Healthy · 0 failures (24h)
                    </span>
                </div>
                {onClose && (
                    <button
                        type="button"
                        onClick={onClose}
                        aria-label="Close pipeline status preview"
                        className="rounded-lg p-1 text-zinc-400 transition hover:bg-zinc-800 hover:text-zinc-100"
                    >
                        <X className="h-3.5 w-3.5" aria-hidden="true" />
                    </button>
                )}
            </div>

            <div className="grid gap-3 sm:grid-cols-12">
                <div className="grid grid-cols-3 gap-2 sm:col-span-5">
                    <div className="rounded-xl border border-zinc-800 bg-zinc-950/75 p-2.5">
                        <p className="text-[10px] text-zinc-400">Sources</p>
                        <p className="mt-0.5 font-mono text-xs font-semibold text-zinc-100">
                            14 / 14
                        </p>
                    </div>
                    <div className="rounded-xl border border-zinc-800 bg-zinc-950/75 p-2.5">
                        <p className="text-[10px] text-zinc-400">Scored</p>
                        <p className="mt-0.5 font-mono text-xs font-semibold text-zinc-100">98%</p>
                    </div>
                    <div className="rounded-xl border border-zinc-800 bg-zinc-950/75 p-2.5">
                        <p className="text-[10px] text-zinc-400">DLQ</p>
                        <p className="mt-0.5 font-mono text-xs font-semibold text-emerald-300">0</p>
                    </div>
                </div>

                <div className="grid gap-2 sm:col-span-7 sm:grid-cols-2">
                    {PIPELINE_WORKERS_PREVIEW.map((worker) => (
                        <div
                            key={worker.name}
                            className="flex items-center justify-between rounded-xl border border-zinc-800/90 bg-zinc-950/75 px-3 py-2 text-xs"
                        >
                            <div className="min-w-0">
                                <p className="truncate font-mono text-[11px] font-medium text-zinc-200">
                                    {worker.name}
                                </p>
                                <p className="font-mono text-[10px] text-zinc-500">
                                    {worker.processed} processed · {worker.heartbeat}
                                </p>
                            </div>
                            <span className="inline-flex shrink-0 items-center gap-1 rounded-md bg-emerald-500/12 px-1.5 py-0.5 text-[10px] font-medium text-emerald-300 ring-1 ring-emerald-500/25">
                                <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />
                                <span>Alive</span>
                            </span>
                        </div>
                    ))}
                </div>
            </div>
        </section>
    );
}

export function LandingPreviewShowcase() {
    const [activeTab, setActiveTab] = useState<PreviewTabId>("radar");
    const [pipelineOpen, setPipelineOpen] = useState(false);
    const [radarQuery, setRadarQuery] = useState("distributed python kafka pgvector");
    const tabRefs = useRef<Partial<Record<PreviewTabId, HTMLButtonElement | null>>>({});

    function handleSearchSkillInRadar(skill: string) {
        setRadarQuery(skill.toLowerCase());
        setActiveTab("radar");
    }

    function handleTabKeyDown(event: KeyboardEvent<HTMLButtonElement>, currentId: PreviewTabId) {
        const nextId = getNextPreviewTabId(currentId, event.key);
        if (!nextId) {
            return;
        }
        event.preventDefault();
        setActiveTab(nextId);
        tabRefs.current[nextId]?.focus();
    }

    return (
        <section
            id="preview"
            aria-label="Interactive Workspace Preview"
            className="scroll-mt-20 pb-16 sm:pb-24"
        >
            <div className="mx-auto max-w-6xl px-4 sm:px-6">
                <h2 className="sr-only">Interactive Workspace Preview</h2>
                <div className="mb-3 flex items-center justify-between gap-2 px-1">
                    <p className="inline-flex items-center gap-2 font-mono text-xs text-zinc-400">
                        <span className="relative flex h-2 w-2 shrink-0" aria-hidden="true">
                            <span className="absolute inline-flex h-full w-full rounded-full bg-violet-400 opacity-70 motion-safe:animate-ping" />
                            <span className="relative inline-flex h-2 w-2 rounded-full bg-violet-400" />
                        </span>
                        <span className="font-medium text-zinc-300">Interactive preview</span>
                        <span aria-hidden="true" className="text-zinc-600">
                            ·
                        </span>
                        <span>Click tabs and filters to explore</span>
                    </p>
                </div>
                <div className="relative">
                    <div
                        aria-hidden="true"
                        className="pointer-events-none absolute -inset-x-6 -top-8 h-48 rounded-full bg-gradient-to-b from-violet-500/20 via-fuchsia-500/5 to-transparent blur-3xl"
                    />

                    <div className="relative overflow-hidden rounded-2xl border border-white/10 bg-zinc-950 shadow-[0_30px_90px_-20px_rgba(0,0,0,0.85)] ring-1 ring-inset ring-white/[0.04]">
                        <div
                            aria-hidden="true"
                            className="h-px w-full bg-gradient-to-r from-transparent via-violet-400/60 to-transparent"
                        />

                        {/* Authentic Vektryn AppShell Top Bar (same items across mobile & desktop) */}
                        <div className="border-b border-zinc-800/80 bg-zinc-950/95 px-4 py-3 sm:px-5">
                            <div className="flex flex-wrap items-center gap-x-3 gap-y-2.5 xl:gap-x-4">
                                <div className="order-1 flex items-center gap-2.5">
                                    <span className="flex h-8 w-8 items-center justify-center rounded-xl bg-zinc-900 ring-1 ring-zinc-800">
                                        <VektrynLogo className="h-6 w-6" />
                                    </span>
                                    <span className="font-mono text-sm font-semibold tracking-tight text-zinc-100">
                                        vektryn
                                    </span>
                                </div>

                                <div className="order-2 ml-auto flex items-center gap-2 xl:order-4 xl:ml-0">
                                    <span
                                        aria-hidden="true"
                                        className="relative inline-flex h-8 w-8 items-center justify-center rounded-xl border border-zinc-800 bg-zinc-900/70 text-zinc-300"
                                    >
                                        <Bell className="h-3.5 w-3.5" />
                                        <span className="absolute -top-1 -right-1 flex h-4 w-4 items-center justify-center rounded-full bg-violet-600 font-mono text-[9px] font-semibold text-white">
                                            2
                                        </span>
                                    </span>
                                    <span className="inline-flex items-center gap-1.5 rounded-xl border border-zinc-800 bg-zinc-900/70 px-2.5 py-1 text-[11px] font-medium text-zinc-300">
                                        <User
                                            className="h-3.5 w-3.5 text-zinc-400"
                                            aria-hidden="true"
                                        />
                                        <span>alex</span>
                                    </span>
                                </div>

                                <div
                                    role="tablist"
                                    aria-label="Vektryn workspace previews"
                                    className="order-3 flex w-full flex-wrap items-center gap-1 xl:order-2 xl:ml-2 xl:w-auto"
                                >
                                    {PREVIEW_TABS.map((tab) => {
                                        const Icon = TAB_ICONS[tab.id];
                                        const selected = activeTab === tab.id;
                                        return (
                                            <button
                                                key={tab.id}
                                                ref={(node) => {
                                                    tabRefs.current[tab.id] = node;
                                                }}
                                                id={`preview-tab-${tab.id}`}
                                                role="tab"
                                                type="button"
                                                aria-selected={selected}
                                                aria-controls={`preview-panel-${tab.id}`}
                                                tabIndex={selected ? 0 : -1}
                                                onClick={() => setActiveTab(tab.id)}
                                                onKeyDown={(e) => handleTabKeyDown(e, tab.id)}
                                                className={`group inline-flex min-h-9 cursor-pointer items-center gap-1.5 rounded-xl border px-2.5 text-xs font-medium transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-500/70 sm:gap-2 sm:px-3 ${selected
                                                        ? "border-violet-500/40 bg-zinc-900 text-zinc-100 shadow-sm shadow-violet-500/10"
                                                        : "border-transparent text-zinc-400 hover:border-violet-500/30 hover:bg-violet-500/10 hover:text-zinc-100"
                                                    }`}
                                            >
                                                <Icon
                                                    className={`h-3.5 w-3.5 transition ${selected
                                                            ? "text-violet-400"
                                                            : "text-zinc-500 group-hover:text-violet-300"
                                                        }`}
                                                    aria-hidden="true"
                                                />
                                                <span>{tab.label}</span>
                                            </button>
                                        );
                                    })}
                                </div>

                                <div className="order-4 flex w-full flex-wrap items-center gap-2 border-t border-zinc-800/60 pt-2.5 xl:order-3 xl:ml-auto xl:w-auto xl:border-t-0 xl:pt-0">
                                    <button
                                        type="button"
                                        aria-expanded={pipelineOpen}
                                        onClick={() => setPipelineOpen((prev) => !prev)}
                                        className={`inline-flex cursor-pointer items-center gap-1.5 rounded-xl border px-2.5 py-1 text-[11px] transition ${pipelineOpen
                                                ? "border-violet-500/40 bg-violet-500/15 text-violet-200"
                                                : "border-zinc-800 bg-zinc-900/70 text-zinc-300 hover:border-zinc-700 hover:text-zinc-100"
                                            }`}
                                    >
                                        <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />
                                        <span>Pipeline · 14m ago</span>
                                    </button>
                                    <span className="inline-flex items-center gap-1.5 rounded-xl border border-emerald-500/30 bg-emerald-950/35 px-2.5 py-1 text-[11px] font-medium text-emerald-300">
                                        <span className="relative flex h-2 w-2">
                                            <span className="absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-60 motion-safe:animate-ping" />
                                            <span className="relative inline-flex h-2 w-2 rounded-full bg-emerald-400" />
                                        </span>
                                        <span>Live Stream</span>
                                    </span>
                                </div>
                            </div>
                        </div>

                        <div
                            id={`preview-panel-${activeTab}`}
                            role="tabpanel"
                            aria-labelledby={`preview-tab-${activeTab}`}
                            className="bg-[radial-gradient(ellipse_75%_35%_at_50%_-5%,rgba(124,58,237,0.12),transparent_70%)] p-4 sm:p-6"
                        >
                            {pipelineOpen && (
                                <PipelineStatusPreviewCard onClose={() => setPipelineOpen(false)} />
                            )}
                            {activeTab === "radar" && <RadarPreviewPanel initialQuery={radarQuery} />}
                            {activeTab === "tracker" && <TrackerPreviewPanel />}
                            {activeTab === "analytics" && (
                                <AnalyticsPreviewPanel
                                    onSearchSkillInRadar={handleSearchSkillInRadar}
                                />
                            )}
                            {activeTab === "resumes" && <ResumesPreviewPanel />}
                        </div>
                    </div>
                </div>

                {/* Ecosystem Proof: Native ATS & Remote Feeds */}
                <div className="mt-10 flex flex-col items-center gap-3 text-center">
                    <p className="font-mono text-[11px] uppercase tracking-widest text-zinc-500">
                        Continuously ingesting across 14 ATS platforms &amp; remote feeds
                    </p>
                    <div className="flex flex-wrap items-center justify-center gap-x-5 gap-y-2">
                        {INGESTED_SOURCES_STRIP.map((source) => (
                            <span
                                key={source}
                                className="font-mono text-xs font-medium text-zinc-500 transition hover:text-zinc-300"
                            >
                                {source}
                            </span>
                        ))}
                    </div>
                </div>
            </div>
        </section>
    );
}
