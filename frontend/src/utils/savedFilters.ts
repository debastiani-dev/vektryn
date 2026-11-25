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
    if (state.metadataFilters.seniority) params.seniority = state.metadataFilters.seniority;
    if (state.metadataFilters.contractType) {
        params.contract_type = state.metadataFilters.contractType;
    }
    if (state.metadataFilters.region) params.region = state.metadataFilters.region;
    if (state.metadataFilters.atsSource) params.ats_source = state.metadataFilters.atsSource;
    if (state.sortBy !== "best_match") params.sort_by = state.sortBy;
    return params;
}

export function hydrateRadarStateFromPreset(
    params: SavedFilterQueryParams,
    availableResumes: ReadonlyArray<Pick<ResumeProfile, "uuid">>,
): RadarFilterState {
    const rawResume = typeof params.resume_profile === "string" ? params.resume_profile : "";
    const resumeExists =
        rawResume.length > 0 && availableResumes.some((resume) => resume.uuid === rawResume);
    const rawSort = typeof params.sort_by === "string" ? params.sort_by : "best_match";
    const sortBy: RadarSortOption = VALID_SORT_VALUES.has(rawSort)
        ? (rawSort as RadarSortOption)
        : "best_match";

    return {
        searchTerm: typeof params.search === "string" ? params.search : "",
        resumeFilter: resumeExists ? rawResume : "",
        minScore: typeof params.min_score === "number" && params.min_score > 0 ? params.min_score : 0,
        evaluatedOnly: Boolean(params.evaluated_only),
        untrackedOnly: Boolean(params.untracked_only),
        hideDismissed: typeof params.hide_dismissed === "boolean" ? params.hide_dismissed : true,
        hideMuted: typeof params.hide_muted === "boolean" ? params.hide_muted : true,
        metadataFilters: {
            ...EMPTY_METADATA_FILTERS,
            seniority: typeof params.seniority === "string" ? params.seniority : "",
            contractType: typeof params.contract_type === "string" ? params.contract_type : "",
            region: typeof params.region === "string" ? params.region : "",
            atsSource: typeof params.ats_source === "string" ? params.ats_source : "",
        },
        sortBy,
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
        (normalizedCurrent.region ?? "") === (normalizedPreset.region ?? "") &&
        (normalizedCurrent.ats_source ?? "") === (normalizedPreset.ats_source ?? "") &&
        (normalizedCurrent.sort_by ?? "best_match") === (normalizedPreset.sort_by ?? "best_match")
    );
}
