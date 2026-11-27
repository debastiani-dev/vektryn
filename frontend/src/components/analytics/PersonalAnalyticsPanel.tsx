import {
    AlertCircle,
    ArrowUpRight,
    CheckCircle2,
    FileText,
    Filter,
    Layers,
    Search,
    Target,
    TrendingUp,
} from "lucide-react";
import { useEffect, useState } from "react";
import { vektrynApi } from "../../api/client";
import type {
    ChannelPerformanceMetric,
    PersonalAnalyticsResponse,
    PersonalAnalyticsWindow,
    PersonalFunnelMetrics,
    ResumeProfile,
    SkillGapMetric,
} from "../../types/models";
import { formatAtsSource, formatContractType } from "../../utils/format";
import { Tooltip } from "../ui/Tooltip";

interface PersonalAnalyticsPanelProps {
    onSearchSkillInRadar?: (skill: string, resumeProfileUuid?: string) => void;
}

const WINDOW_OPTIONS: ReadonlyArray<{ value: PersonalAnalyticsWindow; label: string }> = [
    { value: "30", label: "Last 30d" },
    { value: "90", label: "Last 90d" },
    { value: "all", label: "All Time" },
];

const FUNNEL_BAR_COLORS: Record<string, string> = {
    tracked: "from-zinc-500 to-zinc-400",
    applied: "from-sky-500 to-sky-400",
    screening: "from-violet-500 to-violet-400",
    interviewing: "from-indigo-500 to-violet-400",
    offer: "from-emerald-500 to-emerald-400",
};

function formatPct(value: number | null): string {
    if (value === null || value === undefined) return "—";
    return `${value.toFixed(1)}%`;
}

function formatDays(value: number | null): string {
    if (value === null || value === undefined) return "—";
    return `${value.toFixed(1)}d`;
}

function PersonalSkeleton() {
    return (
        <div className="min-w-0 space-y-6" aria-label="Loading personal analytics">
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
                {[0, 1, 2, 3].map((idx) => (
                    <div
                        key={idx}
                        className="h-24 animate-pulse rounded-2xl border border-zinc-800/80 bg-zinc-900/45"
                    />
                ))}
            </div>
            <div className="h-56 animate-pulse rounded-2xl border border-zinc-800/80 bg-zinc-900/45" />
            <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
                <div className="h-64 animate-pulse rounded-2xl border border-zinc-800/80 bg-zinc-900/45" />
                <div className="h-64 animate-pulse rounded-2xl border border-zinc-800/80 bg-zinc-900/45" />
            </div>
        </div>
    );
}

function FunnelSection({ funnel }: Readonly<{ funnel: PersonalFunnelMetrics }>) {
    const maxStageCount = Math.max(1, funnel.total_leads);
    const rejectedCount = funnel.status_counts.rejected ?? 0;
    const withdrawnCount = funnel.status_counts.withdrawn ?? 0;
    const discoveredCount = funnel.status_counts.discovered ?? 0;

    return (
        <section className="min-w-0 space-y-5 overflow-hidden rounded-2xl border border-zinc-800/90 bg-zinc-900/50 p-4 ring-1 ring-inset ring-white/[0.03] sm:p-6">
            <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="flex items-center gap-2">
                    <TrendingUp className="h-4 w-4 text-violet-400" />
                    <h2 className="text-sm font-semibold text-zinc-100">Application Funnel</h2>
                </div>
                <div className="flex flex-wrap items-center gap-2 text-xs">
                    {discoveredCount > 0 && (
                        <span className="rounded-lg border border-zinc-800 bg-zinc-950/70 px-2.5 py-1 font-mono text-zinc-400">
                            Discovered: {discoveredCount}
                        </span>
                    )}
                    <span className="rounded-lg border border-red-500/20 bg-red-950/20 px-2.5 py-1 font-mono text-red-300">
                        Rejected: {rejectedCount}
                    </span>
                    <span className="rounded-lg border border-zinc-800 bg-zinc-950/70 px-2.5 py-1 font-mono text-zinc-400">
                        Withdrawn: {withdrawnCount}
                    </span>
                </div>
            </div>

            {funnel.total_leads === 0 ? (
                <p className="rounded-xl border border-dashed border-zinc-800 bg-zinc-950/40 px-4 py-8 text-center text-xs text-zinc-400">
                    No tracked applications in this window yet. Save roles from Job Radar to track
                    conversion rates.
                </p>
            ) : (
                <div className="space-y-3.5">
                    {funnel.stages.map((stage) => {
                        const widthPct =
                            stage.count > 0
                                ? Math.max(4, Math.round((stage.count / maxStageCount) * 100))
                                : 0;
                        const barGradient =
                            FUNNEL_BAR_COLORS[stage.key] ?? "from-violet-500 to-violet-400";
                        return (
                            <div key={stage.key} className="space-y-1.5">
                                <div className="flex flex-wrap items-center justify-between gap-x-2 gap-y-1 text-xs">
                                    <span className="font-medium text-zinc-200">{stage.label}</span>
                                    <div className="flex items-center gap-3 font-mono tabular-nums">
                                        {stage.conversion_from_previous_pct !== null && (
                                            <span className="text-[11px] text-zinc-400">
                                                {formatPct(stage.conversion_from_previous_pct)} from
                                                prev
                                            </span>
                                        )}
                                        <span className="w-8 text-right font-semibold text-zinc-100">
                                            {stage.count}
                                        </span>
                                    </div>
                                </div>
                                <div className="h-2.5 w-full overflow-hidden rounded-full bg-zinc-800/90">
                                    <div
                                        className={`h-full rounded-full bg-gradient-to-r transition-all ${barGradient}`}
                                        style={{ width: `${widthPct}%` }}
                                    />
                                </div>
                            </div>
                        );
                    })}
                </div>
            )}
        </section>
    );
}

function ChannelPerformanceCard({
    title,
    emptyLabel,
    rows,
    formatKey,
}: Readonly<{
    title: string;
    emptyLabel: string;
    rows: ReadonlyArray<ChannelPerformanceMetric>;
    formatKey: (key: string) => string;
}>) {
    return (
        <section className="min-w-0 space-y-4 overflow-hidden rounded-2xl border border-zinc-800/90 bg-zinc-900/50 p-4 ring-1 ring-inset ring-white/[0.03] sm:p-6">
            <div className="flex items-center gap-2">
                <Layers className="h-4 w-4 shrink-0 text-sky-400" />
                <h2 className="text-sm font-semibold text-zinc-100">{title}</h2>
            </div>

            {rows.length === 0 ? (
                <p className="rounded-xl border border-dashed border-zinc-800 bg-zinc-950/40 px-4 py-8 text-center text-xs text-zinc-500">
                    {emptyLabel}
                </p>
            ) : (
                <div className="w-full max-w-full overflow-x-auto">
                    <table className="w-full border-collapse text-left text-xs">
                        <thead>
                            <tr className="border-b border-zinc-800 text-[11px] uppercase tracking-wider text-zinc-400">
                                <th className="pb-2.5 pr-3">Channel</th>
                                <th className="pb-2.5 px-2 text-right">Tracked</th>
                                <th className="pb-2.5 px-2 text-right">Applied</th>
                                <th className="pb-2.5 px-2 text-right">Response</th>
                                <th className="pb-2.5 pl-2 text-right">Interview</th>
                            </tr>
                        </thead>
                        <tbody className="divide-y divide-zinc-800/70">
                            {rows.map((row) => (
                                <tr key={row.key} className="hover:bg-zinc-900/60">
                                    <td className="py-2.5 pr-3 font-medium text-zinc-200">
                                        {formatKey(row.key)}
                                    </td>
                                    <td className="py-2.5 px-2 text-right font-mono tabular-nums text-zinc-400">
                                        {row.total_leads}
                                    </td>
                                    <td className="py-2.5 px-2 text-right font-mono tabular-nums text-zinc-200">
                                        {row.applied_count}
                                    </td>
                                    <td className="py-2.5 px-2 text-right font-mono tabular-nums text-sky-300">
                                        {formatPct(row.response_rate_pct)}
                                    </td>
                                    <td className="py-2.5 pl-2 text-right font-mono tabular-nums text-emerald-300">
                                        {formatPct(row.interview_rate_pct)}
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            )}
        </section>
    );
}

function SkillGapListCard({
    title,
    subtitle,
    variant,
    items,
    emptyMessage,
    onSelectSkill,
}: Readonly<{
    title: string;
    subtitle: string;
    variant: "missing" | "matched";
    items: ReadonlyArray<SkillGapMetric>;
    emptyMessage: string;
    onSelectSkill?: (skill: string) => void;
}>) {
    const maxCount = items.reduce((best, item) => Math.max(best, item.match_count), 1);
    const isMissing = variant === "missing";
    const barClass = isMissing
        ? "from-amber-500 to-orange-400"
        : "from-emerald-500 to-teal-400";
    const pillClass = isMissing
        ? "border-amber-500/25 bg-amber-500/10 text-amber-200"
        : "border-emerald-500/25 bg-emerald-500/10 text-emerald-200";

    return (
        <section className="min-w-0 space-y-4 overflow-hidden rounded-2xl border border-zinc-800/90 bg-zinc-900/50 p-4 ring-1 ring-inset ring-white/[0.03] sm:p-6">
            <div className="space-y-1">
                <div className="flex items-center gap-2">
                    {isMissing ? (
                        <AlertCircle className="h-4 w-4 shrink-0 text-amber-400" />
                    ) : (
                        <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-400" />
                    )}
                    <h2 className="text-sm font-semibold text-zinc-100">{title}</h2>
                </div>
                <p className="text-xs text-zinc-400">{subtitle}</p>
            </div>

            {items.length === 0 ? (
                <p className="rounded-xl border border-dashed border-zinc-800 bg-zinc-950/40 px-4 py-8 text-center text-xs text-zinc-500">
                    {emptyMessage}
                </p>
            ) : (
                <div className="space-y-2.5">
                    {items.map((item) => {
                        const widthPct = Math.max(
                            6,
                            Math.round((item.match_count / maxCount) * 100),
                        );
                        const shareLabel =
                            item.pct_of_high_fit !== null
                                ? `${item.pct_of_high_fit.toFixed(0)}% of matches`
                                : "";
                        return (
                            <button
                                key={item.skill}
                                type="button"
                                onClick={() => onSelectSkill?.(item.skill)}
                                className="group block w-full min-w-0 max-w-full overflow-hidden rounded-xl border border-zinc-800/80 bg-zinc-950/55 px-3.5 py-2.5 text-left transition hover:border-violet-500/45 hover:bg-zinc-900/80 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-500/70"
                            >
                                <div className="flex flex-wrap items-center justify-between gap-x-2 gap-y-1.5 text-xs">
                                    <span className="flex min-w-0 items-center gap-2">
                                        <span
                                            className={`truncate rounded-md border px-2 py-0.5 font-mono text-[11px] font-medium ${pillClass}`}
                                        >
                                            {item.skill}
                                        </span>
                                        <span className="hidden items-center gap-1 text-[11px] text-violet-300 opacity-0 transition group-hover:inline-flex group-hover:opacity-100">
                                            <Search className="h-3 w-3" />
                                            Search Radar
                                        </span>
                                    </span>

                                    <span className="flex shrink-0 items-center gap-2 font-mono text-[11px] tabular-nums text-zinc-300">
                                        <span>
                                            {item.match_count}{" "}
                                            {item.match_count === 1 ? "role" : "roles"}
                                        </span>
                                        {shareLabel && (
                                            <span className="text-zinc-500">· {shareLabel}</span>
                                        )}
                                        <ArrowUpRight className="h-3.5 w-3.5 text-zinc-500 transition group-hover:text-violet-300" />
                                    </span>
                                </div>

                                <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-zinc-800">
                                    <div
                                        className={`h-full rounded-full bg-gradient-to-r ${barClass}`}
                                        style={{ width: `${widthPct}%` }}
                                    />
                                </div>
                            </button>
                        );
                    })}
                </div>
            )}
        </section>
    );
}

export function PersonalAnalyticsPanel({
    onSearchSkillInRadar,
}: Readonly<PersonalAnalyticsPanelProps>) {
    const [days, setDays] = useState<PersonalAnalyticsWindow>("30");
    const [resumeProfileUuid, setResumeProfileUuid] = useState("");
    const [resumes, setResumes] = useState<ResumeProfile[]>([]);
    const [data, setData] = useState<PersonalAnalyticsResponse | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        let active = true;
        vektrynApi
            .listResumes()
            .then((res) => {
                if (active) setResumes(res.results);
            })
            .catch(() => {
                if (active) setResumes([]);
            });
        return () => {
            active = false;
        };
    }, []);

    useEffect(() => {
        let active = true;
        vektrynApi
            .getPersonalAnalytics({
                days,
                resumeProfileUuid: resumeProfileUuid || undefined,
            })
            .then((res) => {
                if (!active) return;
                setData(res);
                setError(null);
            })
            .catch((err) => {
                if (!active) return;
                setError(
                    err instanceof Error ? err.message : "Failed to load personal analytics",
                );
            })
            .finally(() => {
                if (active) setLoading(false);
            });

        return () => {
            active = false;
        };
    }, [days, resumeProfileUuid]);

    const appliedStage = data?.funnel.stages.find((stage) => stage.key === "applied");
    const interviewingStage = data?.funnel.stages.find(
        (stage) => stage.key === "interviewing",
    );
    const appliedCount = appliedStage?.count ?? 0;
    const interviewRate =
        appliedCount > 0 && interviewingStage
            ? Math.round((interviewingStage.count / appliedCount) * 1000) / 10
            : null;

    return (
        <div className="min-w-0 space-y-6">
            <div className="flex min-w-0 flex-col gap-4 rounded-2xl border border-zinc-800/80 bg-zinc-900/45 p-4 ring-1 ring-inset ring-white/[0.03] sm:flex-row sm:items-center sm:justify-between">
                <div className="flex flex-wrap items-center gap-2">
                    <Filter className="mr-1 h-4 w-4 text-zinc-500" />
                    {WINDOW_OPTIONS.map((opt) => {
                        const active = days === opt.value;
                        return (
                            <button
                                key={opt.value}
                                type="button"
                                onClick={() => {
                                    setDays(opt.value);
                                    setLoading(true);
                                }}
                                className={`rounded-xl px-3.5 py-2 text-xs font-medium transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-500/70 ${
                                    active
                                        ? "bg-violet-600 text-white shadow-sm shadow-violet-600/25"
                                        : "border border-zinc-800 bg-zinc-950/70 text-zinc-400 hover:border-zinc-700 hover:text-zinc-200"
                                }`}
                            >
                                {opt.label}
                            </button>
                        );
                    })}
                </div>

                <div className="flex w-full min-w-0 items-center gap-2 text-xs sm:w-auto">
                    <FileText className="h-4 w-4 shrink-0 text-zinc-500" />
                    <label
                        htmlFor="personal-analytics-resume"
                        className="shrink-0 text-zinc-400"
                    >
                        Resume
                    </label>
                    <select
                        id="personal-analytics-resume"
                        value={resumeProfileUuid}
                        onChange={(e) => {
                            setResumeProfileUuid(e.target.value);
                            setLoading(true);
                        }}
                        className="min-w-0 max-w-full flex-1 truncate rounded-xl border border-zinc-800 bg-zinc-950/80 px-3 py-1.5 text-xs text-zinc-200 focus:border-violet-500 focus:outline-none focus:ring-2 focus:ring-violet-500/25 sm:w-56 sm:flex-initial"
                    >
                        <option value="">All Resumes</option>
                        {resumes.map((profile) => (
                            <option key={profile.uuid} value={profile.uuid}>
                                {profile.label}
                            </option>
                        ))}
                    </select>
                </div>
            </div>

            {error && (
                <div className="rounded-2xl border border-red-500/30 bg-red-950/20 px-5 py-4 text-sm text-red-300">
                    {error}
                </div>
            )}

            {loading && !data && <PersonalSkeleton />}

            {data && (
                <div className="min-w-0 space-y-6">
                    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
                        <Tooltip
                            content="Total tracked applications created in the selected time window"
                            className="block min-w-0"
                        >
                            <div className="min-w-0 rounded-2xl border border-zinc-800/90 bg-zinc-900/45 px-5 py-4 ring-1 ring-inset ring-white/[0.03]">
                                <p className="text-xs font-medium uppercase tracking-wider text-zinc-400">
                                    Tracked / Applied
                                </p>
                                <p className="mt-2 font-mono text-2xl font-semibold tabular-nums text-zinc-100">
                                    {data.funnel.total_leads} / {appliedCount}
                                </p>
                            </div>
                        </Tooltip>

                        <Tooltip
                            content="Share of applied roles that reached interviewing or offer"
                            className="block min-w-0"
                        >
                            <div className="min-w-0 rounded-2xl border border-emerald-500/20 bg-emerald-950/15 px-5 py-4 ring-1 ring-inset ring-white/[0.03]">
                                <p className="text-xs font-medium uppercase tracking-wider text-emerald-300/80">
                                    Interview Rate
                                </p>
                                <p className="mt-2 font-mono text-2xl font-semibold tabular-nums text-emerald-300">
                                    {formatPct(interviewRate)}
                                </p>
                            </div>
                        </Tooltip>

                        <Tooltip
                            content="Median elapsed days since applied_at across applied leads in this window"
                            className="block min-w-0"
                        >
                            <div className="min-w-0 rounded-2xl border border-zinc-800/90 bg-zinc-900/45 px-5 py-4 ring-1 ring-inset ring-white/[0.03]">
                                <p className="text-xs font-medium uppercase tracking-wider text-zinc-400">
                                    Median Age Applied
                                </p>
                                <p className="mt-2 font-mono text-2xl font-semibold tabular-nums text-sky-300">
                                    {formatDays(data.funnel.median_days_since_applied)}
                                </p>
                            </div>
                        </Tooltip>

                        <Tooltip
                            content="High-fit AI-scored matches meeting your resume alert threshold"
                            className="block min-w-0"
                        >
                            <div className="min-w-0 rounded-2xl border border-violet-500/20 bg-violet-950/15 px-5 py-4 ring-1 ring-inset ring-white/[0.03]">
                                <div className="flex items-center gap-1.5 text-xs font-medium uppercase tracking-wider text-violet-300/80">
                                    <Target className="h-3.5 w-3.5 shrink-0" />
                                    High-Fit Matches
                                </div>
                                <p className="mt-2 font-mono text-2xl font-semibold tabular-nums text-violet-300">
                                    {data.skill_gaps.high_fit_match_count}
                                </p>
                            </div>
                        </Tooltip>
                    </div>

                    <FunnelSection funnel={data.funnel} />

                    <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
                        <ChannelPerformanceCard
                            title="Performance by ATS Source"
                            emptyLabel="No channel data recorded for this window."
                            rows={data.channels.by_ats_source}
                            formatKey={formatAtsSource}
                        />
                        <ChannelPerformanceCard
                            title="Performance by Contract Type"
                            emptyLabel="No contract breakdown recorded for this window."
                            rows={data.channels.by_contract_type}
                            formatKey={formatContractType}
                        />
                    </div>

                    <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
                        <SkillGapListCard
                            title="Top Missing Skills"
                            subtitle={`Most recurring gaps across ${data.skill_gaps.high_fit_match_count} high-fit matches. Click a skill to search Job Radar.`}
                            variant="missing"
                            items={data.skill_gaps.missing_keywords}
                            emptyMessage="No recurring skill gaps found in high-fit matches for this window."
                            onSelectSkill={(skill) =>
                                onSearchSkillInRadar?.(skill, resumeProfileUuid || undefined)
                            }
                        />
                        <SkillGapListCard
                            title="Top Matched Strengths"
                            subtitle={`Most frequently matched skills across ${data.skill_gaps.high_fit_match_count} high-fit matches. Click a skill to search Job Radar.`}
                            variant="matched"
                            items={data.skill_gaps.matched_skills}
                            emptyMessage="No high-fit matched skills recorded in this window yet."
                            onSelectSkill={(skill) =>
                                onSearchSkillInRadar?.(skill, resumeProfileUuid || undefined)
                            }
                        />
                    </div>
                </div>
            )}
        </div>
    );
}
