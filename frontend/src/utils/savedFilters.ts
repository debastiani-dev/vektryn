import type { ResumeProfile, SavedFilterQueryParams } from "../types/models";
import {
    EMPTY_METADATA_FILTERS,
    RADAR_SORT_OPTIONS,
    type RadarMetadataFilters,
    type RadarSortOption,
} from "./radarFilters";

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

export function normalizeCompanyName(raw: string): string {
    return raw.trim().toLowerCase().split(/\s+/).filter(Boolean).join(" ");
}

function asString(value: unknown): string {
    return typeof value === "string" ? value : "";
}

function asBoolean(value: unknown, fallback: boolean): boolean {
    return typeof value === "boolean" ? value : fallback;
}

function resolvePresetSort(value: unknown): RadarSortOption {
    const rawSort = asString(value);
    return VALID_SORT_VALUES.has(rawSort) ? (rawSort as RadarSortOption) : "best_match";
}

function applyMetadataParams(
    params: SavedFilterQueryParams,
    metadataFilters: RadarMetadataFilters,
): void {
    if (metadataFilters.seniority) params.seniority = metadataFilters.seniority;
    if (metadataFilters.contractType) params.contract_type = metadataFilters.contractType;
    if (metadataFilters.workMode) params.work_mode = metadataFilters.workMode;
    if (metadataFilters.language) params.language = metadataFilters.language;
    if (metadataFilters.region) params.region = metadataFilters.region;
    if (metadataFilters.atsSource) params.ats_source = metadataFilters.atsSource;
}

function hydrateMetadataFilters(params: SavedFilterQueryParams): RadarMetadataFilters {
    return {
        ...EMPTY_METADATA_FILTERS,
        seniority: asString(params.seniority),
        contractType: asString(params.contract_type),
        workMode: asString(params.work_mode),
        language: asString(params.language),
        region: asString(params.region),
        atsSource: asString(params.ats_source),
    };
}

export function serializeRadarStateToPreset(state: RadarFilterState): SavedFilterQueryParams {
    const params: SavedFilterQueryParams = {};
    const trimmedSearch = state.searchTerm.trim();
    if (trimmedSearch) params.search = trimmedSearch;
    if (state.resumeFilter) params.resume_profile = state.resumeFilter;
    if (state.minScore > 0) params.min_score = state.minScore;
    if (state.evaluatedOnly) params.evaluated_only = true;
    if (state.untrackedOnly) params.untracked_only = true;
    if (!state.hideDismissed) params.hide_dismissed = false;
    if (!state.hideMuted) params.hide_muted = false;
    applyMetadataParams(params, state.metadataFilters);
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

export function isPresetActive(
    state: RadarFilterState,
    presetParams: SavedFilterQueryParams,
    availableResumes: ReadonlyArray<Pick<ResumeProfile, "uuid">>,
): boolean {
    const normalizedCurrent = serializeRadarStateToPreset(state);
    const normalizedPreset = serializeRadarStateToPreset(
        hydrateRadarStateFromPreset(presetParams, availableResumes),
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
        (normalizedCurrent.sort_by ?? "best_match") === (normalizedPreset.sort_by ?? "best_match")
    );
}
