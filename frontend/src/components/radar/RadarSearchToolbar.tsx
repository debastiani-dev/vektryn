import {
    ArrowUpDown,
    ChevronDown,
    EyeOff,
    FileText,
    Loader2,
    Search,
    SlidersHorizontal,
    Sparkles,
    X,
} from "lucide-react";
import type { HybridSearchMode, ResumeProfile } from "../../types/models";
import { formatLanguageBadge, UNKNOWN_LANGUAGE } from "../../utils/languages";
import {
    type ActiveFilterChipKey,
    buildActiveFilterChips,
    countActivePanelFilters,
    RADAR_SORT_OPTIONS,
    type RadarMetadataFilters,
    type RadarSortOption,
} from "../../utils/radarFilters";
import { Tooltip } from "../ui/Tooltip";
import { MetadataFiltersPanel } from "./RadarMetadataFilters";

function SearchModeBadge({ mode }: Readonly<{ mode: HybridSearchMode | null }>) {
    if (!mode) return null;
    const isHybrid = mode === "hybrid";
    const tooltip = isHybrid
        ? "Ranked with Reciprocal Rank Fusion combining PostgreSQL full-text search and pgvector semantic similarity."
        : "Ranked with PostgreSQL full-text search.";
    return (
        <Tooltip content={tooltip} className="inline-flex">
            <span
                className={`inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-[11px] font-medium ${
                    isHybrid
                        ? "bg-violet-500/15 text-violet-300 ring-1 ring-violet-500/35"
                        : "bg-zinc-800/90 text-zinc-400 ring-1 ring-zinc-700/70"
                }`}
            >
                {isHybrid && <Sparkles className="h-3 w-3" />}
                {isHybrid ? "Hybrid RRF" : "Keyword"}
            </span>
        </Tooltip>
    );
}

interface RadarSearchToolbarProps {
    searchTerm: string;
    debouncedSearch: string;
    searchMode: HybridSearchMode | null;
    loading: boolean;
    shownCount: number;
    totalCount: number;
    resumes: ReadonlyArray<ResumeProfile>;
    resumeFilter: string;
    minScore: number;
    evaluatedOnly: boolean;
    untrackedOnly: boolean;
    hideDismissed: boolean;
    hideMuted: boolean;
    hiddenMutedCount: number;
    sortBy: RadarSortOption;
    metadataFilters: RadarMetadataFilters;
    filtersOpen: boolean;
    hasActiveFilters: boolean;
    onSearchChange: (value: string) => void;
    onCommitSearch: () => void;
    onClearSearch: () => void;
    onToggleEvaluatedOnly: () => void;
    onToggleUntrackedOnly: () => void;
    onOpenTriageModal: () => void;
    onToggleFiltersOpen: () => void;
    onSortChange: (value: RadarSortOption) => void;
    onResumeChange: (value: string) => void;
    onMinScoreChange: (value: number) => void;
    onUpdateMetadata: (patch: Partial<RadarMetadataFilters>) => void;
    onRemoveChip: (key: ActiveFilterChipKey) => void;
    onResetAll: () => void;
}

export function RadarSearchToolbar({
    searchTerm,
    debouncedSearch,
    searchMode,
    loading,
    shownCount,
    totalCount,
    resumes,
    resumeFilter,
    minScore,
    evaluatedOnly,
    untrackedOnly,
    hideDismissed,
    hideMuted,
    hiddenMutedCount,
    sortBy,
    metadataFilters,
    filtersOpen,
    hasActiveFilters,
    onSearchChange,
    onCommitSearch,
    onClearSearch,
    onToggleEvaluatedOnly,
    onToggleUntrackedOnly,
    onOpenTriageModal,
    onToggleFiltersOpen,
    onSortChange,
    onResumeChange,
    onMinScoreChange,
    onUpdateMetadata,
    onRemoveChip,
    onResetAll,
}: Readonly<RadarSearchToolbarProps>) {
    const isDebouncing = searchTerm.trim() !== debouncedSearch;
    const isSearching = isDebouncing || (loading && Boolean(debouncedSearch));
    const activeResumes = resumes.filter((r) => r.is_active);
    const promoteResumeSelector = activeResumes.length >= 2;
    const panelFilterCount = countActivePanelFilters({
        resumeFilter: promoteResumeSelector ? "" : resumeFilter,
        minScore,
        metadataFilters,
    });
    const resumeLabel = resumes.find((r) => r.uuid === resumeFilter)?.label;
    const activeChips = buildActiveFilterChips({
        resumeFilter,
        resumeLabel,
        minScore,
        metadataFilters,
    });
    const roleUnit = totalCount === 1 ? "role" : "roles";
    const statusSummary = loading
        ? "Updating results..."
        : `Showing ${shownCount} of ${totalCount} ${roleUnit}`;

    return (
        <section
            aria-label="Search and filter job matches"
            className="space-y-3.5 rounded-2xl border border-zinc-800/80 bg-zinc-900/45 p-4 ring-1 ring-inset ring-white/[0.03] sm:p-5"
        >
            {/* Row 1: Spacious Search Bar + Fixed Compact Controls */}
            <div className="flex flex-col gap-3 lg:flex-row lg:items-center">
                <div className="relative min-w-0 flex-1">
                    {isSearching ? (
                        <Loader2 className="pointer-events-none absolute top-3 left-3.5 h-4 w-4 animate-spin text-violet-400" />
                    ) : (
                        <Search className="pointer-events-none absolute top-3 left-3.5 h-4 w-4 text-zinc-500" />
                    )}
                    <input
                        type="search"
                        value={searchTerm}
                        onChange={(e) => onSearchChange(e.target.value)}
                        onKeyDown={(e) => {
                            if (e.key === "Enter") {
                                onCommitSearch();
                            } else if (e.key === "Escape" && searchTerm) {
                                onClearSearch();
                            }
                        }}
                        placeholder="Search stack, role, company, or concept (e.g. DRF, KRaft, distributed Python)..."
                        aria-label="Search job matches"
                        className="h-10 w-full min-w-0 rounded-xl border border-zinc-800 bg-zinc-950/80 pr-10 pl-10 text-sm text-zinc-100 placeholder:text-zinc-500 transition hover:border-zinc-700 focus:border-violet-500 focus:outline-none focus:ring-2 focus:ring-violet-500/25 [&::-webkit-search-cancel-button]:hidden"
                    />
                    {searchTerm && (
                        <Tooltip
                            content="Clear search (Esc)"
                            className="absolute top-1.5 right-2 inline-flex"
                        >
                            <button
                                type="button"
                                onClick={onClearSearch}
                                aria-label="Clear search"
                                className="rounded-lg p-1.5 text-zinc-500 transition hover:bg-zinc-800 hover:text-zinc-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-500/70"
                            >
                                <X className="h-4 w-4" />
                            </button>
                        </Tooltip>
                    )}
                </div>

                <div className="flex flex-wrap items-center gap-2.5 lg:shrink-0">
                    {promoteResumeSelector && (
                        <Tooltip content="Auto-match across all active resumes or drill into a single resume profile">
                            <div className="relative shrink-0">
                                <FileText
                                    className="pointer-events-none absolute top-3 left-3 h-4 w-4 text-violet-400"
                                    aria-hidden="true"
                                />
                                <select
                                    id="radar-toolbar-resume"
                                    aria-label="Filter by resume profile"
                                    value={resumeFilter}
                                    onChange={(e) => onResumeChange(e.target.value)}
                                    className="h-10 max-w-[240px] appearance-none truncate rounded-xl border border-violet-500/35 bg-zinc-950/90 pr-8 pl-9 text-xs font-medium text-zinc-100 transition hover:border-violet-400/50 focus:border-violet-500 focus:outline-none focus:ring-2 focus:ring-violet-500/25"
                                >
                                    <option value="">All Active Resumes (Auto-Matched)</option>
                                    {resumes.map((r) => {
                                        const langSuffix =
                                            r.language && r.language !== UNKNOWN_LANGUAGE
                                                ? ` (${formatLanguageBadge(r.language)})`
                                                : "";
                                        const pausedSuffix = r.is_active ? "" : " · Paused";
                                        return (
                                            <option key={r.uuid} value={r.uuid}>
                                                {`${r.label}${langSuffix}${pausedSuffix}`}
                                            </option>
                                        );
                                    })}
                                </select>
                                <ChevronDown className="pointer-events-none absolute top-3 right-2.5 h-4 w-4 text-zinc-500" />
                            </div>
                        </Tooltip>
                    )}

                    <Tooltip content="Only show roles with a Stage 2 AI fit score">
                        <button
                            type="button"
                            aria-pressed={evaluatedOnly}
                            onClick={onToggleEvaluatedOnly}
                            className={`inline-flex h-10 shrink-0 items-center gap-1.5 rounded-xl border px-3.5 text-xs font-medium transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-500/70 ${
                                evaluatedOnly
                                    ? "border-violet-500/45 bg-violet-500/15 text-violet-200"
                                    : "border-zinc-800 bg-zinc-950/80 text-zinc-300 hover:border-zinc-700 hover:text-zinc-100"
                            }`}
                        >
                            AI Scored Only
                        </button>
                    </Tooltip>

                    <Tooltip content="Hide roles already tracked in your Pipeline Tracker (including saved, applied, and interviewing leads)">
                        <button
                            type="button"
                            aria-pressed={untrackedOnly}
                            onClick={onToggleUntrackedOnly}
                            className={`inline-flex h-10 shrink-0 items-center gap-1.5 rounded-xl border px-3.5 text-xs font-medium transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-500/70 ${
                                untrackedOnly
                                    ? "border-violet-500/45 bg-violet-500/15 text-violet-200"
                                    : "border-zinc-800 bg-zinc-950/80 text-zinc-300 hover:border-zinc-700 hover:text-zinc-100"
                            }`}
                        >
                            Unapplied Only
                        </button>
                    </Tooltip>

                    <Tooltip content="Manage hidden roles, muted companies, and feed visibility">
                        <button
                            type="button"
                            onClick={onOpenTriageModal}
                            className={`inline-flex h-10 shrink-0 items-center gap-1.5 rounded-xl border px-3 text-xs font-medium transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-500/70 ${
                                !hideDismissed || !hideMuted
                                    ? "border-amber-500/45 bg-amber-500/15 text-amber-200"
                                    : "border-zinc-800 bg-zinc-950/80 text-zinc-300 hover:border-zinc-700 hover:text-zinc-100"
                            }`}
                        >
                            <EyeOff className="h-3.5 w-3.5" />
                            <span>Hidden &amp; Muted</span>
                            {hiddenMutedCount > 0 && (
                                <span className="rounded-md bg-zinc-800 px-1.5 py-0.5 font-mono text-[11px] leading-none tabular-nums text-zinc-200">
                                    {hiddenMutedCount}
                                </span>
                            )}
                        </button>
                    </Tooltip>

                    <Tooltip content="Filter by resume, minimum fit, seniority, contract, region, or source">
                        <button
                            type="button"
                            aria-expanded={filtersOpen}
                            onClick={onToggleFiltersOpen}
                            className={`inline-flex h-10 shrink-0 items-center gap-2 rounded-xl border px-3.5 text-xs font-medium transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-500/70 ${
                                filtersOpen || panelFilterCount > 0
                                    ? "border-violet-500/45 bg-violet-500/15 text-violet-200"
                                    : "border-zinc-800 bg-zinc-950/80 text-zinc-300 hover:border-zinc-700 hover:text-zinc-100"
                            }`}
                        >
                            <SlidersHorizontal className="h-3.5 w-3.5" />
                            <span>Filters</span>
                            {panelFilterCount > 0 && (
                                <span className="rounded-md bg-violet-500/30 px-1.5 py-0.5 font-mono text-[11px] leading-none tabular-nums text-violet-100">
                                    {panelFilterCount}
                                </span>
                            )}
                            <ChevronDown
                                className={`h-3.5 w-3.5 transition-transform ${
                                    filtersOpen ? "rotate-180" : ""
                                }`}
                            />
                        </button>
                    </Tooltip>

                    <Tooltip content="Order matching roles server-side">
                        <div className="relative shrink-0">
                            <ArrowUpDown className="pointer-events-none absolute top-3 left-3 h-4 w-4 text-zinc-400" />
                            <select
                                id="radar-sort"
                                aria-label="Sort matching roles"
                                value={sortBy}
                                onChange={(e) => onSortChange(e.target.value as RadarSortOption)}
                                className="h-10 w-48 appearance-none truncate rounded-xl border border-zinc-800 bg-zinc-950/80 pr-8 pl-9 text-xs font-medium text-zinc-100 transition hover:border-zinc-700 focus:border-violet-500 focus:outline-none focus:ring-2 focus:ring-violet-500/25"
                            >
                                {RADAR_SORT_OPTIONS.map((opt) => (
                                    <option key={opt.value} value={opt.value}>
                                        {opt.value === "best_match" && debouncedSearch
                                            ? "Relevance (Hybrid)"
                                            : opt.label}
                                    </option>
                                ))}
                            </select>
                            <ChevronDown className="pointer-events-none absolute top-3 right-2.5 h-4 w-4 text-zinc-500" />
                        </div>
                    </Tooltip>
                </div>
            </div>

            {/* Row 2: Collapsible Structured Filters Panel */}
            {filtersOpen && (
                <MetadataFiltersPanel
                    resumes={resumes}
                    resumeFilter={resumeFilter}
                    hideResumeSelect={promoteResumeSelector}
                    minScore={minScore}
                    filters={metadataFilters}
                    onResumeChange={onResumeChange}
                    onMinScoreChange={onMinScoreChange}
                    onUpdateMetadata={onUpdateMetadata}
                />
            )}

            {/* Row 3: Status Count, Search Mode Badge & Removable Active Filter Chips */}
            <div className="flex flex-wrap items-center justify-between gap-2.5 border-t border-zinc-800/70 pt-3">
                <div className="flex flex-wrap items-center gap-2">
                    <span className="font-mono text-xs tabular-nums text-zinc-400">
                        {statusSummary}
                    </span>
                    {Boolean(debouncedSearch) && !loading && <SearchModeBadge mode={searchMode} />}
                </div>

                {(activeChips.length > 0 || hasActiveFilters) && (
                    <div className="flex flex-wrap items-center gap-2">
                        {activeChips.map((chip) => (
                            <button
                                key={chip.key}
                                type="button"
                                onClick={() => onRemoveChip(chip.key)}
                                aria-label={`Remove ${chip.prefix} filter: ${chip.label}`}
                                className="inline-flex max-w-[220px] items-center gap-1.5 rounded-lg border border-violet-500/35 bg-violet-500/12 px-2.5 py-1 text-xs font-medium text-violet-200 transition hover:bg-violet-500/20 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-500/70"
                            >
                                <span className="shrink-0 text-violet-300/75">{chip.prefix}:</span>
                                <span className="truncate">{chip.label}</span>
                                <X className="h-3 w-3 shrink-0 text-violet-300" />
                            </button>
                        ))}
                        {hasActiveFilters && (
                            <button
                                type="button"
                                onClick={onResetAll}
                                className="rounded-lg px-2 py-1 text-xs font-medium text-zinc-400 transition hover:bg-zinc-800/70 hover:text-zinc-200"
                            >
                                Reset all
                            </button>
                        )}
                    </div>
                )}
            </div>
        </section>
    );
}
