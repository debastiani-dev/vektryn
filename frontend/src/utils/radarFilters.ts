import type { SalaryPeriod } from "../types/models";
import { formatAtsSource, formatCompactSalaryValue, formatExactDate } from "./format";
import { formatLanguageLabel } from "./languages";

export interface RadarMetadataFilters {
    seniority: string;
    contractType: string;
    workMode: string;
    language: string;
    region: string;
    atsSource: string;
    hideReposts: boolean;
    minSalary: string;
    maxSalary: string;
    salaryCurrency: string;
    salaryPeriod: SalaryPeriod | "";
    disclosedSalaryOnly: boolean;
}

export const EMPTY_METADATA_FILTERS: RadarMetadataFilters = {
    seniority: "",
    contractType: "",
    workMode: "",
    language: "",
    region: "",
    atsSource: "",
    hideReposts: false,
    minSalary: "",
    maxSalary: "",
    salaryCurrency: "",
    salaryPeriod: "",
    disclosedSalaryOnly: false,
};

export function parsePositiveSalaryInput(raw: string | null | undefined): number | null {
    if (!raw) return null;
    const trimmed = raw.trim().replace(/,/g, "");
    if (!trimmed) return null;
    const parsed = Number(trimmed);
    if (!Number.isFinite(parsed) || parsed <= 0) {
        return null;
    }
    return parsed;
}

export function isSalaryRangeInverted(minRaw: string, maxRaw: string): boolean {
    const minVal = parsePositiveSalaryInput(minRaw);
    const maxVal = parsePositiveSalaryInput(maxRaw);
    return minVal !== null && maxVal !== null && minVal > maxVal;
}

export const DIRECT_ATS_SOURCES = new Set<string>([
    "greenhouse",
    "ashby",
    "lever",
    "workable",
    "smartrecruiters",
    "recruitee",
    "breezy",
    "inhire",
    "gupy",
    "solides",
]);

export function isDirectAtsSource(source: string | null | undefined): boolean {
    if (!source) return false;
    return DIRECT_ATS_SOURCES.has(source.trim().toLowerCase());
}

export function formatRepostLabel(repostCount: number): string {
    if (repostCount <= 1) return "Reposted";
    return `Reposted ×${repostCount}`;
}

export function formatRepostTooltip(
    createdAt: string | null | undefined,
    lastRepostedAt: string | null | undefined,
): string {
    const firstSeen = formatExactDate(createdAt ?? null);
    const lastSeen = formatExactDate(lastRepostedAt ?? null);
    if (firstSeen && lastSeen) {
        return `First observed ${firstSeen} · Last reposted ${lastSeen}`;
    }
    if (lastSeen) {
        return `Last reposted ${lastSeen}`;
    }
    if (firstSeen) {
        return `First observed ${firstSeen}`;
    }
    return "This role has been reposted multiple times";
}

export function formatAdditionalSourcesTooltip(
    primarySource: string,
    observedSources: ReadonlyArray<string>,
): string {
    const others = observedSources
        .filter((s) => s !== primarySource)
        .map((s) => formatAtsSource(s));
    if (others.length === 0) {
        return `Observed across multiple job boards (primary: ${formatAtsSource(primarySource)})`;
    }
    return `Also seen on ${others.join(", ")}`;
}

export interface FilterChoice {
    value: string;
    label: string;
}

export type RadarSortOption = "best_match" | "salary" | "newest" | "posted_at" | "vector";

export const RADAR_SORT_OPTIONS: ReadonlyArray<{
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
        value: "salary",
        label: "Highest Salary",
        ordering: "-job_posting__salary_annual_mid_usd,-fit_score,-created_at",
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

export const SALARY_CURRENCY_OPTIONS: ReadonlyArray<FilterChoice> = [
    { value: "USD", label: "USD ($)" },
    { value: "BRL", label: "BRL (R$)" },
    { value: "EUR", label: "EUR (€)" },
    { value: "GBP", label: "GBP (£)" },
    { value: "CAD", label: "CAD (C$)" },
    { value: "AUD", label: "AUD (A$)" },
    { value: "CHF", label: "CHF" },
    { value: "PLN", label: "PLN" },
];

export const SALARY_PERIOD_OPTIONS: ReadonlyArray<{ value: SalaryPeriod; label: string }> = [
    { value: "monthly", label: "Monthly" },
    { value: "annual", label: "Annual" },
    { value: "hourly", label: "Hourly" },
];

export function buildSalaryCurrencyOptions(
    availableCodes?: ReadonlyArray<string>,
): FilterChoice[] {
    const primaryOrder = ["USD", "BRL", "EUR", "GBP"];
    const knownLabels = new Map(SALARY_CURRENCY_OPTIONS.map((opt) => [opt.value, opt.label]));
    const seen = new Set<string>();
    const options: FilterChoice[] = [];

    for (const code of primaryOrder) {
        seen.add(code);
        options.push({ value: code, label: knownLabels.get(code) ?? code });
    }

    const extraCodes = (availableCodes ?? SALARY_CURRENCY_OPTIONS.map((o) => o.value))
        .map((c) => c.trim().toUpperCase())
        .filter((c) => c.length === 3 && !seen.has(c))
        .sort((a, b) => a.localeCompare(b));

    for (const code of extraCodes) {
        seen.add(code);
        options.push({ value: code, label: knownLabels.get(code) ?? code });
    }
    return options;
}

export const MIN_FIT_OPTIONS: ReadonlyArray<{ value: number; label: string; shortLabel: string }> =
    [
        { value: 0, label: "All roles", shortLabel: "" },
        { value: 70, label: "70%+ (Alert threshold)", shortLabel: "70%+" },
        { value: 80, label: "80%+ (Strong match)", shortLabel: "80%+" },
    ];

export const SENIORITY_OPTIONS: ReadonlyArray<FilterChoice> = [
    { value: "intern", label: "Intern" },
    { value: "junior", label: "Junior" },
    { value: "mid", label: "Mid-Level" },
    { value: "senior", label: "Senior" },
    { value: "staff", label: "Staff" },
    { value: "principal", label: "Principal" },
    { value: "lead", label: "Lead" },
    { value: "manager", label: "Manager" },
];

export const CONTRACT_OPTIONS: ReadonlyArray<FilterChoice> = [
    { value: "clt", label: "CLT" },
    { value: "pj", label: "PJ" },
    { value: "b2b_contractor", label: "B2B Contractor" },
    { value: "w2", label: "W2" },
    { value: "c2c", label: "C2C" },
    { value: "eor", label: "EOR" },
];

export const WORK_MODE_OPTIONS: ReadonlyArray<FilterChoice> = [
    { value: "remote", label: "Remote" },
    { value: "hybrid", label: "Hybrid" },
    { value: "onsite", label: "On-site" },
    { value: "unknown", label: "Unknown" },
];

export const REGION_OPTIONS: ReadonlyArray<FilterChoice> = [
    { value: "brazil", label: "Brazil" },
    { value: "latam", label: "LATAM" },
    { value: "north_america", label: "North America" },
    { value: "americas", label: "Americas" },
    { value: "europe", label: "Europe" },
    { value: "emea", label: "EMEA" },
    { value: "apac", label: "APAC" },
    { value: "worldwide", label: "Worldwide" },
];

export const SOURCE_OPTIONS: ReadonlyArray<FilterChoice> = [
    { value: "manual", label: "Manual Import" },
    { value: "greenhouse", label: "Greenhouse" },
    { value: "ashby", label: "Ashby" },
    { value: "lever", label: "Lever" },
    { value: "workable", label: "Workable" },
    { value: "smartrecruiters", label: "SmartRecruiters" },
    { value: "recruitee", label: "Recruitee" },
    { value: "breezy", label: "Breezy" },
    { value: "gupy", label: "Gupy" },
    { value: "inhire", label: "InHire" },
    { value: "remotive", label: "Remotive" },
    { value: "himalayas", label: "Himalayas" },
    { value: "jobicy", label: "Jobicy" },
    { value: "trampos", label: "Trampos" },
    { value: "github_vagas", label: "GitHub Vagas" },
];

export type ActiveFilterChipKey =
    | "resume"
    | "minScore"
    | "seniority"
    | "contractType"
    | "workMode"
    | "language"
    | "region"
    | "atsSource"
    | "hideReposts"
    | "minSalary"
    | "maxSalary"
    | "disclosedSalaryOnly";

export interface ActiveFilterChip {
    key: ActiveFilterChipKey;
    prefix: string;
    label: string;
}

export function lookupOptionLabel(options: ReadonlyArray<FilterChoice>, value: string): string {
    return options.find((opt) => opt.value === value)?.label ?? value;
}

export function resolveRadarOrdering(sortBy: RadarSortOption): string | null {
    if (sortBy === "best_match") {
        return null;
    }
    return RADAR_SORT_OPTIONS.find((opt) => opt.value === sortBy)?.ordering ?? null;
}

function countCompensationFilters(metadataFilters: RadarMetadataFilters): number {
    let count = 0;
    if (parsePositiveSalaryInput(metadataFilters.minSalary) !== null) count += 1;
    if (parsePositiveSalaryInput(metadataFilters.maxSalary) !== null) count += 1;
    if (metadataFilters.disclosedSalaryOnly) count += 1;
    return count;
}

export function countActivePanelFilters(params: {
    resumeFilter: string;
    minScore: number;
    metadataFilters: RadarMetadataFilters;
}): number {
    let count = countCompensationFilters(params.metadataFilters);
    if (params.resumeFilter) count += 1;
    if (params.minScore > 0) count += 1;
    if (params.metadataFilters.seniority) count += 1;
    if (params.metadataFilters.contractType) count += 1;
    if (params.metadataFilters.workMode) count += 1;
    if (params.metadataFilters.language) count += 1;
    if (params.metadataFilters.region) count += 1;
    if (params.metadataFilters.atsSource) count += 1;
    if (params.metadataFilters.hideReposts) count += 1;
    return count;
}

function appendCompensationFilterChips(
    chips: ActiveFilterChip[],
    metadataFilters: RadarMetadataFilters,
    defaultSalaryCurrency: string,
    defaultSalaryPeriod: SalaryPeriod,
): void {
    const currency = (metadataFilters.salaryCurrency || defaultSalaryCurrency || "USD").toUpperCase();
    const period = metadataFilters.salaryPeriod || defaultSalaryPeriod;
    const minSalary = parsePositiveSalaryInput(metadataFilters.minSalary);
    const maxSalary = parsePositiveSalaryInput(metadataFilters.maxSalary);

    if (minSalary !== null) {
        chips.push({
            key: "minSalary",
            prefix: "Min Salary",
            label: `>= ${formatCompactSalaryValue(minSalary, currency, period)}`,
        });
    }
    if (maxSalary !== null) {
        chips.push({
            key: "maxSalary",
            prefix: "Max Salary",
            label: `<= ${formatCompactSalaryValue(maxSalary, currency, period)}`,
        });
    }
    if (metadataFilters.disclosedSalaryOnly) {
        chips.push({
            key: "disclosedSalaryOnly",
            prefix: "Compensation",
            label: "Salary Disclosed",
        });
    }
}

export function buildActiveFilterChips(params: {
    resumeFilter: string;
    resumeLabel?: string;
    minScore: number;
    metadataFilters: RadarMetadataFilters;
    defaultSalaryCurrency?: string;
    defaultSalaryPeriod?: SalaryPeriod;
}): ActiveFilterChip[] {
    const chips: ActiveFilterChip[] = [];
    if (params.resumeFilter) {
        chips.push({
            key: "resume",
            prefix: "Resume",
            label: params.resumeLabel || "Selected",
        });
    }
    if (params.minScore > 0) {
        const fitOpt = MIN_FIT_OPTIONS.find((o) => o.value === params.minScore);
        chips.push({
            key: "minScore",
            prefix: "Min Fit",
            label: fitOpt?.shortLabel || `${params.minScore}%+`,
        });
    }
    if (params.metadataFilters.seniority) {
        chips.push({
            key: "seniority",
            prefix: "Seniority",
            label: lookupOptionLabel(SENIORITY_OPTIONS, params.metadataFilters.seniority),
        });
    }
    if (params.metadataFilters.contractType) {
        chips.push({
            key: "contractType",
            prefix: "Contract",
            label: lookupOptionLabel(CONTRACT_OPTIONS, params.metadataFilters.contractType),
        });
    }
    if (params.metadataFilters.workMode) {
        chips.push({
            key: "workMode",
            prefix: "Work Mode",
            label: lookupOptionLabel(WORK_MODE_OPTIONS, params.metadataFilters.workMode),
        });
    }
    if (params.metadataFilters.language) {
        chips.push({
            key: "language",
            prefix: "Language",
            label: formatLanguageLabel(params.metadataFilters.language),
        });
    }
    if (params.metadataFilters.region) {
        chips.push({
            key: "region",
            prefix: "Region",
            label: lookupOptionLabel(REGION_OPTIONS, params.metadataFilters.region),
        });
    }
    if (params.metadataFilters.atsSource) {
        chips.push({
            key: "atsSource",
            prefix: "Source",
            label: lookupOptionLabel(SOURCE_OPTIONS, params.metadataFilters.atsSource),
        });
    }
    if (params.metadataFilters.hideReposts) {
        chips.push({
            key: "hideReposts",
            prefix: "Reposts",
            label: "Hidden",
        });
    }
    appendCompensationFilterChips(
        chips,
        params.metadataFilters,
        params.defaultSalaryCurrency ?? "USD",
        params.defaultSalaryPeriod ?? "annual",
    );
    return chips;
}

function appendSalaryQueryParams(
    params: URLSearchParams,
    metadataFilters: RadarMetadataFilters,
    minSalaryRaw: string,
    maxSalaryRaw: string,
    preferredCurrency: string,
    defaultSalaryPeriod: SalaryPeriod,
): void {
    const minSalary = parsePositiveSalaryInput(minSalaryRaw);
    const maxSalary = parsePositiveSalaryInput(maxSalaryRaw);
    if (minSalary !== null) params.set("min_salary", String(minSalary));
    if (maxSalary !== null) params.set("max_salary", String(maxSalary));
    if (minSalary !== null || maxSalary !== null) {
        const currency = (metadataFilters.salaryCurrency || preferredCurrency || "USD").toUpperCase();
        const period = metadataFilters.salaryPeriod || defaultSalaryPeriod;
        params.set("salary_currency", currency);
        params.set("salary_period", period);
    }
    if (metadataFilters.disclosedSalaryOnly) {
        params.set("disclosed_salary_only", "true");
    }
}

export function buildMatchesQueryParams(opts: {
    page: number;
    minScore: number;
    resumeFilter: string;
    evaluatedOnly: boolean;
    untrackedOnly: boolean;
    hideDismissed: boolean;
    hideMuted: boolean;
    sortBy: RadarSortOption;
    search: string;
    metadataFilters: RadarMetadataFilters;
    minSalaryRaw?: string;
    maxSalaryRaw?: string;
    preferredCurrency?: string;
    defaultSalaryPeriod?: SalaryPeriod;
}): string {
    const params = new URLSearchParams();
    params.set("page", String(opts.page));
    if (opts.minScore > 0) params.set("min_fit_score", String(opts.minScore));
    if (opts.resumeFilter) params.set("resume_profile", opts.resumeFilter);
    if (opts.evaluatedOnly) params.set("evaluated_only", "true");
    if (opts.untrackedOnly) params.set("untracked_only", "true");
    if (!opts.hideDismissed) params.set("hide_dismissed", "false");
    if (!opts.hideMuted) params.set("hide_muted", "false");
    if (opts.search) params.set("search", opts.search);
    if (opts.metadataFilters.seniority) params.set("seniority", opts.metadataFilters.seniority);
    if (opts.metadataFilters.contractType) {
        params.set("contract_type", opts.metadataFilters.contractType);
    }
    if (opts.metadataFilters.workMode) params.set("work_mode", opts.metadataFilters.workMode);
    if (opts.metadataFilters.region) params.set("region", opts.metadataFilters.region);
    if (opts.metadataFilters.atsSource) params.set("ats_source", opts.metadataFilters.atsSource);
    if (opts.metadataFilters.language) params.set("language", opts.metadataFilters.language);
    if (opts.metadataFilters.hideReposts) params.set("hide_reposts", "true");
    appendSalaryQueryParams(
        params,
        opts.metadataFilters,
        opts.minSalaryRaw ?? opts.metadataFilters.minSalary,
        opts.maxSalaryRaw ?? opts.metadataFilters.maxSalary,
        opts.preferredCurrency ?? "USD",
        opts.defaultSalaryPeriod ?? "annual",
    );
    const orderingParam = resolveRadarOrdering(opts.sortBy);
    if (orderingParam) params.set("ordering", orderingParam);
    return `?${params.toString()}`;
}
