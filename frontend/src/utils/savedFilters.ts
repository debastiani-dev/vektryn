import type { ResumeProfile, SalaryPeriod, SavedFilterQueryParams } from "../types/models";
import {
    EMPTY_METADATA_FILTERS,
    parsePositiveSalaryInput,
    RADAR_SORT_OPTIONS,
    type RadarMetadataFilters,
    type RadarSortOption,
} from "./radarFilters";

export interface SalaryPresetDefaults {
    currency?: string;
    period?: SalaryPeriod;
}

export interface RadarFilterState {
    searchTerm: string;
    resumeFilter: string;
    minScore: number;
    evaluatedOnly: boolean;
    untrackedOnly: boolean;
    hideDismissed: boolean;
    hideMuted: boolean;
    metadataFilters: RadarMetadataFilters;
    sortBy: RadarSortOption;
}

const VALID_SORT_VALUES = new Set<string>(RADAR_SORT_OPTIONS.map((opt) => opt.value));
const VALID_SALARY_PERIODS = new Set<string>(["hourly", "monthly", "annual"]);

export function normalizeCompanyName(raw: string): string {
    return raw.trim().toLowerCase().split(/\s+/).filter(Boolean).join(" ");
}

function asString(value: unknown): string {
    return typeof value === "string" ? value : "";
}

function asBoolean(value: unknown, fallback: boolean): boolean {
    return typeof value === "boolean" ? value : fallback;
}

function asPositiveNumberString(value: unknown): string {
    if (typeof value === "number" && Number.isFinite(value) && value > 0) {
        return String(value);
    }
    if (typeof value === "string") {
        const parsed = parsePositiveSalaryInput(value);
        return parsed !== null ? String(parsed) : "";
    }
    return "";
}

function asSalaryPeriod(value: unknown): SalaryPeriod | "" {
    const raw = asString(value).trim().toLowerCase();
    return VALID_SALARY_PERIODS.has(raw) ? (raw as SalaryPeriod) : "";
}

function resolvePresetSort(value: unknown): RadarSortOption {
    const rawSort = asString(value);
    return VALID_SORT_VALUES.has(rawSort) ? (rawSort as RadarSortOption) : "best_match";
}

function applyCompensationParams(
    params: SavedFilterQueryParams,
    metadataFilters: RadarMetadataFilters,
    salaryDefaults?: SalaryPresetDefaults,
): void {
    const minSalary = parsePositiveSalaryInput(metadataFilters.minSalary);
    const maxSalary = parsePositiveSalaryInput(metadataFilters.maxSalary);
    if (minSalary !== null) params.min_salary = minSalary;
    if (maxSalary !== null) params.max_salary = maxSalary;
    if (minSalary !== null || maxSalary !== null) {
        params.salary_currency = (
            metadataFilters.salaryCurrency ||
            salaryDefaults?.currency ||
            "USD"
        ).toUpperCase();
        params.salary_period =
            metadataFilters.salaryPeriod || salaryDefaults?.period || "annual";
    }
    if (metadataFilters.disclosedSalaryOnly) {
        params.disclosed_salary_only = true;
    }
}

function applyMetadataParams(
    params: SavedFilterQueryParams,
    metadataFilters: RadarMetadataFilters,
    salaryDefaults?: SalaryPresetDefaults,
): void {
    if (metadataFilters.seniority) params.seniority = metadataFilters.seniority;
    if (metadataFilters.contractType) params.contract_type = metadataFilters.contractType;
    if (metadataFilters.workMode) params.work_mode = metadataFilters.workMode;
    if (metadataFilters.language) params.language = metadataFilters.language;
    if (metadataFilters.region) params.region = metadataFilters.region;
    if (metadataFilters.atsSource) params.ats_source = metadataFilters.atsSource;
    if (metadataFilters.hideReposts) params.hide_reposts = true;
    applyCompensationParams(params, metadataFilters, salaryDefaults);
}

function hydrateMetadataFilters(params: SavedFilterQueryParams): RadarMetadataFilters {
    const minSalary = asPositiveNumberString(params.min_salary);
    const maxSalary = asPositiveNumberString(params.max_salary);
    const hasBound = Boolean(minSalary || maxSalary);
    return {
        ...EMPTY_METADATA_FILTERS,
        seniority: asString(params.seniority),
        contractType: asString(params.contract_type),
        workMode: asString(params.work_mode),
        language: asString(params.language),
        region: asString(params.region),
        atsSource: asString(params.ats_source),
        hideReposts: Boolean(params.hide_reposts),
        minSalary,
        maxSalary,
        salaryCurrency: hasBound ? asString(params.salary_currency).trim().toUpperCase() : "",
        salaryPeriod: hasBound ? asSalaryPeriod(params.salary_period) : "",
        disclosedSalaryOnly: Boolean(params.disclosed_salary_only),
    };
}

export function serializeRadarStateToPreset(
    state: RadarFilterState,
    salaryDefaults?: SalaryPresetDefaults,
): SavedFilterQueryParams {
    const params: SavedFilterQueryParams = {};
    const trimmedSearch = state.searchTerm.trim();
    if (trimmedSearch) params.search = trimmedSearch;
    if (state.resumeFilter) params.resume_profile = state.resumeFilter;
    if (state.minScore > 0) params.min_score = state.minScore;
    if (state.evaluatedOnly) params.evaluated_only = true;
    if (state.untrackedOnly) params.untracked_only = true;
    if (!state.hideDismissed) params.hide_dismissed = false;
    if (!state.hideMuted) params.hide_muted = false;
    applyMetadataParams(params, state.metadataFilters, salaryDefaults);
    if (state.sortBy !== "best_match") params.sort_by = state.sortBy;
    return params;
}

export function hydrateRadarStateFromPreset(
    params: SavedFilterQueryParams,
    availableResumes: ReadonlyArray<Pick<ResumeProfile, "uuid">>,
): RadarFilterState {
    const rawResume = asString(params.resume_profile);
    const resumeExists =
        rawResume.length > 0 && availableResumes.some((resume) => resume.uuid === rawResume);
    const minScore =
        typeof params.min_score === "number" && params.min_score > 0 ? params.min_score : 0;

    return {
        searchTerm: asString(params.search),
        resumeFilter: resumeExists ? rawResume : "",
        minScore,
        evaluatedOnly: Boolean(params.evaluated_only),
        untrackedOnly: Boolean(params.untracked_only),
        hideDismissed: asBoolean(params.hide_dismissed, true),
        hideMuted: asBoolean(params.hide_muted, true),
        metadataFilters: hydrateMetadataFilters(params),
        sortBy: resolvePresetSort(params.sort_by),
    };
}

function areSalaryParamsEqual(
    current: SavedFilterQueryParams,
    preset: SavedFilterQueryParams,
): boolean {
    return (
        (current.min_salary ?? 0) === (preset.min_salary ?? 0) &&
        (current.max_salary ?? 0) === (preset.max_salary ?? 0) &&
        (current.salary_currency ?? "") === (preset.salary_currency ?? "") &&
        (current.salary_period ?? "") === (preset.salary_period ?? "") &&
        Boolean(current.disclosed_salary_only) === Boolean(preset.disclosed_salary_only)
    );
}

export function isPresetActive(
    state: RadarFilterState,
    presetParams: SavedFilterQueryParams,
    availableResumes: ReadonlyArray<Pick<ResumeProfile, "uuid">>,
    salaryDefaults?: SalaryPresetDefaults,
): boolean {
    const normalizedCurrent = serializeRadarStateToPreset(state, salaryDefaults);
    const normalizedPreset = serializeRadarStateToPreset(
        hydrateRadarStateFromPreset(presetParams, availableResumes),
        salaryDefaults,
    );
    return (
        (normalizedCurrent.search ?? "") === (normalizedPreset.search ?? "") &&
        (normalizedCurrent.resume_profile ?? "") === (normalizedPreset.resume_profile ?? "") &&
        (normalizedCurrent.min_score ?? 0) === (normalizedPreset.min_score ?? 0) &&
        Boolean(normalizedCurrent.evaluated_only) === Boolean(normalizedPreset.evaluated_only) &&
        Boolean(normalizedCurrent.untracked_only) === Boolean(normalizedPreset.untracked_only) &&
        (normalizedCurrent.hide_dismissed ?? true) === (normalizedPreset.hide_dismissed ?? true) &&
        (normalizedCurrent.hide_muted ?? true) === (normalizedPreset.hide_muted ?? true) &&
        (normalizedCurrent.seniority ?? "") === (normalizedPreset.seniority ?? "") &&
        (normalizedCurrent.contract_type ?? "") === (normalizedPreset.contract_type ?? "") &&
        (normalizedCurrent.work_mode ?? "") === (normalizedPreset.work_mode ?? "") &&
        (normalizedCurrent.language ?? "") === (normalizedPreset.language ?? "") &&
        (normalizedCurrent.region ?? "") === (normalizedPreset.region ?? "") &&
        (normalizedCurrent.ats_source ?? "") === (normalizedPreset.ats_source ?? "") &&
        Boolean(normalizedCurrent.hide_reposts) === Boolean(normalizedPreset.hide_reposts) &&
        areSalaryParamsEqual(normalizedCurrent, normalizedPreset) &&
        (normalizedCurrent.sort_by ?? "best_match") === (normalizedPreset.sort_by ?? "best_match")
    );
}
