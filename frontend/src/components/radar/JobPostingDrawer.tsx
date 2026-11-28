import {
    Banknote,
    BookmarkCheck,
    BookmarkPlus,
    Building2,
    Calendar,
    ExternalLink,
    FileText,
    Globe2,
    Hash,
    Layers,
    Mail,
    MapPin,
    Repeat,
    Sparkles,
    X,
} from "lucide-react";
import { useEffect, useState } from "react";
import { vektrynApi } from "../../api/client";
import type {
    ContractType,
    JobPostingDetail,
    MatchScore,
    SalaryDisplayCadence,
    SalaryNormalizedPayload,
    SeniorityLevel,
    WorkMode,
} from "../../types/models";
import {
    formatApplyLinkLabel,
    formatApplyLinkTooltip,
    formatAtsSource,
    formatContractType,
    formatExactDate,
    formatNormalizedSalary,
    formatRegionEligibility,
    formatRelativeTime,
    formatSeniority,
    formatWorkMode,
    isMailtoUrl,
    type FormattedSalaryDisplay,
    workModeBadgeStyle,
} from "../../utils/format";
import {
    formatKnownLanguageBadge,
    getLanguageName,
    languageBadgeStyle,
} from "../../utils/languages";
import { formatRepostLabel, formatRepostTooltip } from "../../utils/radarFilters";
import { SlideOverDrawer } from "../ui/SlideOverDrawer";
import { Tooltip } from "../ui/Tooltip";
import { ObservedSourcesSection } from "./ObservedSourcesSection";

export interface JobListingPreview {
    uuid: string;
    title: string;
    company_name: string;
    apply_url: string;
    ats_source?: string;
    primary_source?: string;
    sources_count?: number;
    observed_sources?: string[];
    repost_count?: number;
    last_reposted_at?: string | null;
    external_id?: string;
    location_raw?: string;
    seniority?: SeniorityLevel;
    contract_type?: ContractType;
    work_mode?: WorkMode;
    language?: string;
    region_eligibility?: string[];
    salary_min?: string | null;
    salary_max?: string | null;
    salary_currency?: string | null;
    salary_period?: string | null;
    salary_annual_min_usd?: string | null;
    salary_annual_max_usd?: string | null;
    salary_annual_mid_usd?: string | null;
    salary_normalized?: SalaryNormalizedPayload | null;
    tech_stack?: string[];
    is_active?: boolean;
    posted_at?: string | null;
    created_at?: string;
}

interface JobPostingDrawerProps {
    jobPreview: JobListingPreview | null;
    match?: MatchScore | null;
    salaryCadence?: SalaryDisplayCadence;
    saving?: boolean;
    saved?: boolean;
    onClose: () => void;
    onSaveLead?: () => void;
    onOpenGapDetails?: () => void;
}

function CompensationMetaCard({
    salaryDisplay,
    rawCurrency,
}: Readonly<{
    salaryDisplay: FormattedSalaryDisplay | null;
    rawCurrency?: string | null;
}>) {
    return (
        <div className="rounded-2xl border border-zinc-800/90 bg-zinc-900/45 p-4 ring-1 ring-inset ring-white/[0.03]">
            <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-zinc-400">
                <Banknote className="h-4 w-4 text-emerald-400" />
                Compensation
            </div>
            {salaryDisplay ? (
                <>
                    <Tooltip content={salaryDisplay.tooltip}>
                        <p
                            className={`mt-2 inline-block font-mono text-sm font-medium tabular-nums ${
                                salaryDisplay.isUnverified ? "text-zinc-300" : "text-zinc-100"
                            }`}
                        >
                            {salaryDisplay.label}
                        </p>
                    </Tooltip>
                    {salaryDisplay.isUnverified && (
                        <p className="mt-1 text-xs text-amber-300/85">Unverified range</p>
                    )}
                    {!salaryDisplay.isUnverified && salaryDisplay.isConverted && (
                        <p className="mt-1 text-xs text-zinc-400">
                            {salaryDisplay.originalLabel
                                ? `Original: ${salaryDisplay.originalLabel}`
                                : `Converted to ${salaryDisplay.displayCurrency ?? "USD"}`}
                            {salaryDisplay.fxAsOf ? ` · FX ${salaryDisplay.fxAsOf}` : ""}
                        </p>
                    )}
                    {!salaryDisplay.isUnverified &&
                        !salaryDisplay.isConverted &&
                        salaryDisplay.originalLabel &&
                        salaryDisplay.originalLabel !== salaryDisplay.label && (
                            <p className="mt-1 text-xs text-zinc-400">
                                Original: {salaryDisplay.originalLabel}
                            </p>
                        )}
                    {!salaryDisplay.isUnverified &&
                        !salaryDisplay.isConverted &&
                        (!salaryDisplay.originalLabel ||
                            salaryDisplay.originalLabel === salaryDisplay.label) &&
                        rawCurrency && (
                            <p className="mt-1 text-xs text-zinc-500">
                                Currency: {rawCurrency.toUpperCase()}
                            </p>
                        )}
                </>
            ) : (
                <p className="mt-2 font-mono text-sm font-medium tabular-nums text-zinc-100">
                    Not disclosed
                </p>
            )}
        </div>
    );
}

function DescriptionSkeleton() {
    return (
        <div className="space-y-3 animate-pulse" aria-label="Loading job description">
            <div className="h-4 w-11/12 rounded bg-zinc-800/80" />
            <div className="h-4 w-full rounded bg-zinc-800/70" />
            <div className="h-4 w-5/6 rounded bg-zinc-800/70" />
            <div className="h-4 w-3/4 rounded bg-zinc-800/60" />
            <div className="pt-2 h-4 w-full rounded bg-zinc-800/70" />
            <div className="h-4 w-10/12 rounded bg-zinc-800/70" />
            <div className="h-4 w-4/5 rounded bg-zinc-800/60" />
        </div>
    );
}

function formatPostedDisplay(postedAt: string | null | undefined): string {
    const postedAge = formatRelativeTime(postedAt ?? null);
    const postedExact = formatExactDate(postedAt ?? null);
    if (postedExact && postedAge) {
        return `${postedExact} (${postedAge})`;
    }
    return postedExact ?? "Unknown";
}

function getSaveButtonLabel(saved: boolean, saving: boolean): string {
    if (saved) return "Saved in Pipeline";
    if (saving) return "Saving...";
    return "Save to Tracker";
}

function JobDescriptionBody({
    loadingDetail,
    detailError,
    descriptionClean,
}: Readonly<{
    loadingDetail: boolean;
    detailError: string | null;
    descriptionClean: string;
}>) {
    if (loadingDetail) {
        return <DescriptionSkeleton />;
    }
    if (detailError) {
        return (
            <div className="rounded-xl border border-red-500/30 bg-red-950/20 px-4 py-3 text-sm text-red-300">
                {detailError}
            </div>
        );
    }
    const cleanedText = descriptionClean.trim();
    if (!cleanedText) {
        return (
            <p className="text-sm text-zinc-500">
                No full job description text is stored for this posting. Use &ldquo;Open Original Posting&rdquo; below to read the source listing.
            </p>
        );
    }
    return (
        <div className="whitespace-pre-wrap break-words text-sm leading-7 text-zinc-300">
            {cleanedText}
        </div>
    );
}

function JobTechStackSection({
    techStack,
    matchedSet,
}: Readonly<{
    techStack: string[];
    matchedSet: Set<string>;
}>) {
    if (techStack.length === 0) {
        return null;
    }
    return (
        <section className="rounded-2xl border border-zinc-800/90 bg-zinc-900/45 p-5 ring-1 ring-inset ring-white/[0.03] sm:p-6">
            <h3 className="mb-3.5 flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-zinc-300">
                <Layers className="h-4 w-4 text-violet-400" />
                Tech Stack ({techStack.length})
            </h3>
            <div className="flex flex-wrap gap-2">
                {techStack.map((tag) => {
                    const isMatched = matchedSet.has(tag.toLowerCase());
                    const tagTooltip = isMatched
                        ? `${tag} — matches your resume profile`
                        : `${tag} — listed in job requirements`;
                    return (
                        <Tooltip key={tag} content={tagTooltip}>
                            <span
                                className={`rounded-lg border px-3 py-1 font-mono text-xs ${
                                    isMatched
                                        ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-200"
                                        : "border-zinc-800 bg-zinc-800/75 text-zinc-300"
                                }`}
                            >
                                {tag}
                            </span>
                        </Tooltip>
                    );
                })}
            </div>
        </section>
    );
}

function JobDrawerFooter({
    applyUrl,
    saving,
    saved,
    onSaveLead,
    onOpenGapDetails,
}: Readonly<{
    applyUrl: string;
    saving: boolean;
    saved: boolean;
    onSaveLead?: () => void;
    onOpenGapDetails?: () => void;
}>) {
    const isEmailApply = isMailtoUrl(applyUrl);
    const saveTooltip = saved
        ? "This role is already saved in your Pipeline Tracker"
        : "Save this role to your Pipeline Tracker";

    return (
        <div className="flex flex-col-reverse gap-2.5 border-t border-zinc-800/90 bg-zinc-900/80 px-4 py-3.5 sm:flex-row sm:flex-wrap sm:items-center sm:justify-between sm:gap-4 sm:px-8 sm:py-5">
            <div className="flex flex-wrap items-center gap-2 sm:gap-3">
                {onSaveLead && (
                    <Tooltip content={saveTooltip} className="inline-flex flex-1 sm:flex-initial">
                        <button
                            type="button"
                            disabled={saving || saved}
                            onClick={onSaveLead}
                            className={`inline-flex w-full items-center justify-center gap-2 rounded-xl border px-3.5 py-2.5 text-sm font-medium transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-500/70 disabled:cursor-not-allowed sm:w-auto sm:px-4 ${
                                saved
                                    ? "border-emerald-500/30 bg-emerald-950/30 text-emerald-200"
                                    : "border-zinc-700 bg-zinc-800 text-zinc-100 hover:bg-zinc-700 disabled:opacity-50"
                            }`}
                        >
                            {saved ? (
                                <BookmarkCheck className="h-4 w-4 shrink-0 text-emerald-400" />
                            ) : (
                                <BookmarkPlus className="h-4 w-4 shrink-0 text-violet-400" />
                            )}
                            {getSaveButtonLabel(saved, saving)}
                        </button>
                    </Tooltip>
                )}

                {onOpenGapDetails && (
                    <Tooltip
                        content="Switch to AI skill gap analysis and talking points"
                        className="inline-flex flex-1 sm:flex-initial"
                    >
                        <button
                            type="button"
                            onClick={onOpenGapDetails}
                            className="inline-flex w-full items-center justify-center gap-2 rounded-xl border border-zinc-800 bg-zinc-900 px-3.5 py-2.5 text-sm font-medium text-zinc-300 transition hover:border-zinc-700 hover:bg-zinc-800 hover:text-zinc-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-500/70 sm:w-auto sm:px-4"
                        >
                            <Sparkles className="h-4 w-4 shrink-0 text-violet-400" />
                            Gap Details
                        </button>
                    </Tooltip>
                )}
            </div>

            <Tooltip
                content={formatApplyLinkTooltip(
                    applyUrl,
                    "Open the job application page in a new tab",
                )}
                className="inline-flex w-full sm:w-auto"
            >
                <a
                    href={applyUrl}
                    target={isEmailApply ? undefined : "_blank"}
                    rel={isEmailApply ? undefined : "noreferrer"}
                    className="inline-flex w-full items-center justify-center gap-2 rounded-xl bg-violet-600 px-4 py-2.5 text-sm font-medium text-white shadow-sm shadow-violet-600/20 transition hover:bg-violet-500 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-500/70 focus-visible:ring-offset-2 focus-visible:ring-offset-zinc-900 sm:w-auto sm:px-5"
                >
                    {formatApplyLinkLabel(applyUrl, "Open Original Posting")}{" "}
                    {isEmailApply ? (
                        <Mail className="h-4 w-4 shrink-0" />
                    ) : (
                        <ExternalLink className="h-4 w-4 shrink-0" />
                    )}
                </a>
            </Tooltip>
        </div>
    );
}

export function JobPostingDrawer({
    jobPreview,
    match = null,
    salaryCadence = "annual",
    saving = false,
    saved = false,
    onClose,
    onSaveLead,
    onOpenGapDetails,
}: Readonly<JobPostingDrawerProps>) {
    const [fetchState, setFetchState] = useState<{
        uuid: string | null;
        detail: JobPostingDetail | null;
        error: string | null;
    }>({ uuid: null, detail: null, error: null });

    const jobUuid = jobPreview?.uuid ?? null;
    const detail = jobUuid && fetchState.uuid === jobUuid ? fetchState.detail : null;
    const detailError = jobUuid && fetchState.uuid === jobUuid ? fetchState.error : null;
    const loadingDetail = Boolean(jobUuid && fetchState.uuid !== jobUuid);

    useEffect(() => {
        if (!jobUuid) {
            return;
        }

        let cancelled = false;
        vektrynApi
            .getJob(jobUuid)
            .then((res) => {
                if (!cancelled) {
                    setFetchState({ uuid: jobUuid, detail: res, error: null });
                }
            })
            .catch((err) => {
                if (!cancelled) {
                    setFetchState({
                        uuid: jobUuid,
                        detail: null,
                        error:
                            err instanceof Error ? err.message : "Failed to load full job listing",
                    });
                }
            });

        return () => {
            cancelled = true;
        };
    }, [jobUuid]);

    if (!jobPreview) {
        return null;
    }

    const job = detail ?? jobPreview;
    const isActive = job.is_active ?? true;
    const seniorityLabel = job.seniority ? formatSeniority(job.seniority) : "";
    const contractLabel = job.contract_type ? formatContractType(job.contract_type) : "";
    const jobLanguageBadge = formatKnownLanguageBadge(job.language);
    const jobLanguageName = getLanguageName(job.language);
    const atsSource = job.primary_source || job.ats_source || "";
    const repostCount = detail?.repost_count ?? job.repost_count ?? 0;
    const lastRepostedAt = detail?.last_reposted_at ?? job.last_reposted_at ?? null;
    const regionList = job.region_eligibility ?? [];
    const techStack = job.tech_stack ?? [];
    const salaryDisplay = formatNormalizedSalary(job, salaryCadence);
    const postedDisplay = formatPostedDisplay(job.posted_at);
    const ingestedExact = formatExactDate(detail?.created_at ?? job.created_at ?? null);
    const closedExact = formatExactDate(detail?.closed_at ?? null);
    const externalId = detail?.external_id ?? job.external_id ?? null;
    const matchedSet = new Set(
        (match?.matched_skills ?? []).map((skill) => skill.toLowerCase()),
    );

    return (
        <SlideOverDrawer
            labelledBy="job-drawer-title"
            closeLabel="Close job listing drawer"
            desktopMaxWidthPx={768}
            onClose={onClose}
        >
                <div className="flex items-start justify-between gap-3 border-b border-zinc-800/90 bg-zinc-950/90 px-4 py-3.5 sm:gap-4 sm:px-8 sm:py-6">
                    <div className="min-w-0 flex-1 space-y-2 sm:space-y-2.5">
                        <div className="flex flex-wrap items-center gap-1.5 sm:gap-2">
                            <Tooltip
                                content={
                                    isActive
                                        ? "Job listing is currently active upstream"
                                        : "Job listing has been marked closed"
                                }
                                side="bottom"
                            >
                                <span
                                    className={`inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1 text-xs font-medium ring-1 ${isActive
                                            ? "bg-emerald-500/12 text-emerald-300 ring-emerald-500/30"
                                            : "bg-rose-500/12 text-rose-300 ring-rose-500/30"
                                        }`}
                                >
                                    <span
                                        className={`h-1.5 w-1.5 rounded-full ${isActive ? "bg-emerald-400" : "bg-rose-400"
                                            }`}
                                    />
                                    {isActive ? "Active Listing" : "Closed"}
                                </span>
                            </Tooltip>

                            {seniorityLabel && (
                                <Tooltip content="Detected seniority level" side="bottom">
                                    <span className="rounded-lg bg-zinc-800/80 px-2.5 py-1 text-xs font-medium text-zinc-300">
                                        {seniorityLabel}
                                    </span>
                                </Tooltip>
                            )}

                            <Tooltip content="Workplace arrangement" side="bottom">
                                <span
                                    className={`rounded-lg px-2.5 py-1 text-xs font-medium ${workModeBadgeStyle(job.work_mode)}`}
                                >
                                    {formatWorkMode(job.work_mode)}
                                </span>
                            </Tooltip>

                            {contractLabel && (
                                <Tooltip content="Employment / contract type" side="bottom">
                                    <span className="rounded-lg bg-zinc-800/80 px-2.5 py-1 text-xs font-medium text-zinc-300">
                                        {contractLabel}
                                    </span>
                                </Tooltip>
                            )}

                            {jobLanguageBadge && (
                                <Tooltip
                                    content={`Detected job language: ${jobLanguageName}`}
                                    side="bottom"
                                >
                                    <span
                                        className={`inline-flex items-center gap-1 rounded-lg px-2 py-1 font-mono text-xs font-semibold ${languageBadgeStyle(job.language)}`}
                                    >
                                        <Globe2 className="h-3 w-3" />
                                        {jobLanguageBadge}
                                    </span>
                                </Tooltip>
                            )}

                            {atsSource && (
                                <Tooltip
                                    content={`Primary source: ${formatAtsSource(atsSource)}`}
                                    side="bottom"
                                >
                                    <span className="text-xs font-medium text-zinc-500">
                                        {formatAtsSource(atsSource)}
                                    </span>
                                </Tooltip>
                            )}

                            {repostCount >= 1 && (
                                <Tooltip
                                    content={formatRepostTooltip(
                                        detail?.created_at ?? job.created_at,
                                        lastRepostedAt,
                                    )}
                                    side="bottom"
                                >
                                    <span className="inline-flex items-center gap-1 rounded-lg bg-amber-500/12 px-2 py-1 text-xs font-medium text-amber-300 ring-1 ring-amber-500/30">
                                        <Repeat className="h-3 w-3" />
                                        {formatRepostLabel(repostCount)}
                                    </span>
                                </Tooltip>
                            )}
                        </div>

                        <h2
                            id="job-drawer-title"
                            className="break-words text-base font-semibold leading-snug text-zinc-100 sm:text-xl"
                        >
                            {job.title}
                        </h2>

                        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-zinc-400 sm:text-sm">
                            <span className="inline-flex min-w-0 items-center gap-1.5 font-medium text-zinc-200">
                                <Building2 className="h-4 w-4 shrink-0 text-zinc-500" />
                                <span className="break-words">{job.company_name}</span>
                            </span>
                            <span className="inline-flex min-w-0 items-center gap-1.5">
                                <MapPin className="h-4 w-4 shrink-0 text-zinc-500" />
                                <span className="break-words">{job.location_raw || "Remote"}</span>
                            </span>
                        </div>
                    </div>

                    <Tooltip content="Close job listing (Esc)" side="bottom" className="inline-flex shrink-0">
                        <button
                            type="button"
                            onClick={onClose}
                            aria-label="Close job listing drawer"
                            className="shrink-0 rounded-xl p-2 text-zinc-400 transition hover:bg-zinc-900 hover:text-zinc-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-500/70"
                        >
                            <X className="h-5 w-5" />
                        </button>
                    </Tooltip>
                </div>

                <div className="min-w-0 flex-1 space-y-4 overflow-x-hidden overflow-y-auto overscroll-contain px-4 py-4 sm:space-y-6 sm:px-8 sm:py-7">
                    <section className="grid min-w-0 gap-3.5 sm:grid-cols-2 sm:gap-4">
                        <CompensationMetaCard
                            salaryDisplay={salaryDisplay}
                            rawCurrency={job.salary_currency}
                        />

                        <div className="rounded-2xl border border-zinc-800/90 bg-zinc-900/45 p-4 ring-1 ring-inset ring-white/[0.03]">
                            <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-zinc-400">
                                <Globe2 className="h-4 w-4 text-sky-400" />
                                Region Eligibility
                            </div>
                            {regionList.length > 0 ? (
                                <div className="mt-2 flex flex-wrap gap-1.5">
                                    {regionList.map((region) => (
                                        <span
                                            key={region}
                                            className="rounded-md bg-sky-500/12 px-2.5 py-0.5 text-xs font-medium text-sky-300 ring-1 ring-sky-500/25"
                                        >
                                            {formatRegionEligibility(region)}
                                        </span>
                                    ))}
                                </div>
                            ) : (
                                <p className="mt-2 text-sm text-zinc-400">Not specified</p>
                            )}
                        </div>

                        <div className="rounded-2xl border border-zinc-800/90 bg-zinc-900/45 p-4 ring-1 ring-inset ring-white/[0.03]">
                            <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-zinc-400">
                                <Calendar className="h-4 w-4 text-violet-400" />
                                Listing Timeline
                            </div>
                            <div className="mt-2 space-y-1 text-xs text-zinc-300">
                                <p>
                                    <span className="text-zinc-500">Posted: </span>
                                    <span className="font-mono tabular-nums">{postedDisplay}</span>
                                </p>
                                {ingestedExact && (
                                    <p>
                                        <span className="text-zinc-500">Collected: </span>
                                        <span className="font-mono tabular-nums">
                                            {ingestedExact}
                                        </span>
                                    </p>
                                )}
                                {closedExact && (
                                    <p className="text-rose-300">
                                        <span className="text-rose-400/80">Closed: </span>
                                        <span className="font-mono tabular-nums">
                                            {closedExact}
                                        </span>
                                    </p>
                                )}
                            </div>
                        </div>

                        <div className="rounded-2xl border border-zinc-800/90 bg-zinc-900/45 p-4 ring-1 ring-inset ring-white/[0.03]">
                            <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-zinc-400">
                                <Hash className="h-4 w-4 text-zinc-400" />
                                Source Metadata
                            </div>
                            <div className="mt-2 space-y-1 text-xs text-zinc-300">
                                <p>
                                    <span className="text-zinc-500">ATS: </span>
                                    {formatAtsSource(atsSource) || "Unknown"}
                                </p>
                                {externalId && (
                                    <p className="truncate">
                                        <span className="text-zinc-500">External ID: </span>
                                        <span className="font-mono text-zinc-400">
                                            {externalId}
                                        </span>
                                    </p>
                                )}
                            </div>
                        </div>
                    </section>

                    <ObservedSourcesSection
                        sources={detail?.sources}
                        loading={loadingDetail}
                        repostCount={repostCount}
                        createdAt={detail?.created_at ?? job.created_at ?? null}
                        lastRepostedAt={lastRepostedAt}
                    />

                    <JobTechStackSection techStack={techStack} matchedSet={matchedSet} />

                    <section className="rounded-2xl border border-zinc-800/90 bg-zinc-900/45 p-5 ring-1 ring-inset ring-white/[0.03] sm:p-6">
                        <h3 className="mb-4 flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-zinc-300">
                            <FileText className="h-4 w-4 text-violet-400" />
                            Full Job Description
                        </h3>
                        <JobDescriptionBody
                            loadingDetail={loadingDetail}
                            detailError={detailError}
                            descriptionClean={detail?.description_clean ?? ""}
                        />
                    </section>
                </div>

                <JobDrawerFooter
                    applyUrl={job.apply_url}
                    saving={saving}
                    saved={saved}
                    onSaveLead={onSaveLead}
                    onOpenGapDetails={onOpenGapDetails}
                />
        </SlideOverDrawer>
    );
}
