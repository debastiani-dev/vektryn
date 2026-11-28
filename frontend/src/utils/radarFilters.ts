import { formatLanguageLabel } from "./languages";

export interface RadarMetadataFilters {
    seniority: string;
    contractType: string;
    workMode: string;
    language: string;
    region: string;
    atsSource: string;
}

export const EMPTY_METADATA_FILTERS: RadarMetadataFilters = {
    seniority: "",
    contractType: "",
    workMode: "",
    language: "",
    region: "",
    atsSource: "",
};

export interface FilterChoice {
    value: string;
    label: string;
}

export type RadarSortOption = "best_match" | "newest" | "posted_at" | "vector";

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
    | "atsSource";

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

export function countActivePanelFilters(params: {
    resumeFilter: string;
    minScore: number;
    metadataFilters: RadarMetadataFilters;
}): number {
    let count = 0;
    if (params.resumeFilter) count += 1;
    if (params.minScore > 0) count += 1;
    if (params.metadataFilters.seniority) count += 1;
    if (params.metadataFilters.contractType) count += 1;
    if (params.metadataFilters.workMode) count += 1;
    if (params.metadataFilters.language) count += 1;
    if (params.metadataFilters.region) count += 1;
    if (params.metadataFilters.atsSource) count += 1;
    return count;
}

export function buildActiveFilterChips(params: {
    resumeFilter: string;
    resumeLabel?: string;
    minScore: number;
    metadataFilters: RadarMetadataFilters;
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
    return chips;
}
