import { ChevronDown } from "lucide-react";
import type { ResumeProfile } from "../../types/models";
import {
    CONTRACT_OPTIONS,
    type FilterChoice,
    MIN_FIT_OPTIONS,
    type RadarMetadataFilters,
    REGION_OPTIONS,
    SENIORITY_OPTIONS,
    SOURCE_OPTIONS,
} from "../../utils/radarFilters";

function FilterSelectField({
    id,
    label,
    allLabel,
    value,
    options,
    onChange,
}: Readonly<{
    id: string;
    label: string;
    allLabel: string;
    value: string;
    options: ReadonlyArray<FilterChoice>;
    onChange: (value: string) => void;
}>) {
    return (
        <div className="min-w-0 space-y-1.5">
            <label
                htmlFor={id}
                className="block text-[11px] font-medium uppercase tracking-wider text-zinc-400"
            >
                {label}
            </label>
            <div className="relative">
                <select
                    id={id}
                    value={value}
                    onChange={(e) => onChange(e.target.value)}
                    className="h-10 w-full min-w-0 appearance-none truncate rounded-xl border border-zinc-800 bg-zinc-950/80 pr-9 pl-3 text-sm text-zinc-100 transition hover:border-zinc-700 focus:border-violet-500 focus:outline-none focus:ring-2 focus:ring-violet-500/25"
                >
                    <option value="">{allLabel}</option>
                    {options.map((opt) => (
                        <option key={opt.value} value={opt.value}>
                            {opt.label}
                        </option>
                    ))}
                </select>
                <ChevronDown className="pointer-events-none absolute top-3 right-3 h-4 w-4 text-zinc-500" />
            </div>
        </div>
    );
}

export function MetadataFiltersPanel({
    resumes,
    resumeFilter,
    minScore,
    filters,
    onResumeChange,
    onMinScoreChange,
    onUpdateMetadata,
}: Readonly<{
    resumes: ReadonlyArray<ResumeProfile>;
    resumeFilter: string;
    minScore: number;
    filters: RadarMetadataFilters;
    onResumeChange: (value: string) => void;
    onMinScoreChange: (value: number) => void;
    onUpdateMetadata: (patch: Partial<RadarMetadataFilters>) => void;
}>) {
    const resumeOptions: FilterChoice[] = resumes.map((r) => ({
        value: r.uuid,
        label: r.label,
    }));
    const minFitOptions: FilterChoice[] = MIN_FIT_OPTIONS.filter((o) => o.value > 0).map((o) => ({
        value: String(o.value),
        label: o.label,
    }));

    return (
        <div className="grid grid-cols-1 gap-3.5 border-t border-zinc-800/80 pt-4 sm:grid-cols-2 lg:grid-cols-3">
            <FilterSelectField
                id="radar-filter-resume"
                label="Resume Profile"
                allLabel="All resumes"
                value={resumeFilter}
                options={resumeOptions}
                onChange={onResumeChange}
            />
            <FilterSelectField
                id="radar-filter-min-fit"
                label="Minimum AI Fit"
                allLabel="All roles"
                value={minScore > 0 ? String(minScore) : ""}
                options={minFitOptions}
                onChange={(val) => onMinScoreChange(val ? Number(val) : 0)}
            />
            <FilterSelectField
                id="radar-filter-source"
                label="Source"
                allLabel="Any source"
                value={filters.atsSource}
                options={SOURCE_OPTIONS}
                onChange={(atsSource) => onUpdateMetadata({ atsSource })}
            />
            <FilterSelectField
                id="radar-filter-seniority"
                label="Seniority"
                allLabel="Any seniority"
                value={filters.seniority}
                options={SENIORITY_OPTIONS}
                onChange={(seniority) => onUpdateMetadata({ seniority })}
            />
            <FilterSelectField
                id="radar-filter-contract"
                label="Contract Type"
                allLabel="Any contract"
                value={filters.contractType}
                options={CONTRACT_OPTIONS}
                onChange={(contractType) => onUpdateMetadata({ contractType })}
            />
            <FilterSelectField
                id="radar-filter-region"
                label="Region"
                allLabel="Any region"
                value={filters.region}
                options={REGION_OPTIONS}
                onChange={(region) => onUpdateMetadata({ region })}
            />
        </div>
    );
}
