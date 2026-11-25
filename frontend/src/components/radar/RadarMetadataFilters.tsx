import { ChevronDown, X } from "lucide-react";
import {
    CONTRACT_OPTIONS,
    type FilterChoice,
    lookupOptionLabel,
    type RadarMetadataFilters,
    REGION_OPTIONS,
    SENIORITY_OPTIONS,
    SOURCE_OPTIONS,
} from "../../utils/radarFilters";

function MetadataSelectField({
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
        <div className="space-y-1.5">
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
                    className="w-full appearance-none rounded-xl border border-zinc-800 bg-zinc-950/75 py-2 pr-9 pl-3 text-sm text-zinc-100 transition focus:border-violet-500 focus:outline-none focus:ring-2 focus:ring-violet-500/25"
                >
                    <option value="">{allLabel}</option>
                    {options.map((opt) => (
                        <option key={opt.value} value={opt.value}>
                            {opt.label}
                        </option>
                    ))}
                </select>
                <ChevronDown className="pointer-events-none absolute top-2.5 right-3 h-4 w-4 text-zinc-500" />
            </div>
        </div>
    );
}

export function MetadataFiltersPanel({
    filters,
    onUpdate,
}: Readonly<{
    filters: RadarMetadataFilters;
    onUpdate: (patch: Partial<RadarMetadataFilters>) => void;
}>) {
    return (
        <div className="grid gap-3 border-t border-zinc-800/80 pt-4 sm:grid-cols-2 lg:grid-cols-4">
            <MetadataSelectField
                id="radar-filter-seniority"
                label="Seniority"
                allLabel="Any seniority"
                value={filters.seniority}
                options={SENIORITY_OPTIONS}
                onChange={(seniority) => onUpdate({ seniority })}
            />
            <MetadataSelectField
                id="radar-filter-contract"
                label="Contract Type"
                allLabel="Any contract"
                value={filters.contractType}
                options={CONTRACT_OPTIONS}
                onChange={(contractType) => onUpdate({ contractType })}
            />
            <MetadataSelectField
                id="radar-filter-region"
                label="Region"
                allLabel="Any region"
                value={filters.region}
                options={REGION_OPTIONS}
                onChange={(region) => onUpdate({ region })}
            />
            <MetadataSelectField
                id="radar-filter-source"
                label="Source"
                allLabel="Any source"
                value={filters.atsSource}
                options={SOURCE_OPTIONS}
                onChange={(atsSource) => onUpdate({ atsSource })}
            />
        </div>
    );
}

export function ActiveMetadataFilterChips({
    filters,
    onRemove,
    onClearAll,
}: Readonly<{
    filters: RadarMetadataFilters;
    onRemove: (key: keyof RadarMetadataFilters) => void;
    onClearAll: () => void;
}>) {
    const chips: Array<{ key: keyof RadarMetadataFilters; prefix: string; label: string }> = [];
    if (filters.seniority) {
        chips.push({
            key: "seniority",
            prefix: "Seniority",
            label: lookupOptionLabel(SENIORITY_OPTIONS, filters.seniority),
        });
    }
    if (filters.contractType) {
        chips.push({
            key: "contractType",
            prefix: "Contract",
            label: lookupOptionLabel(CONTRACT_OPTIONS, filters.contractType),
        });
    }
    if (filters.region) {
        chips.push({
            key: "region",
            prefix: "Region",
            label: lookupOptionLabel(REGION_OPTIONS, filters.region),
        });
    }
    if (filters.atsSource) {
        chips.push({
            key: "atsSource",
            prefix: "Source",
            label: lookupOptionLabel(SOURCE_OPTIONS, filters.atsSource),
        });
    }

    if (chips.length === 0) {
        return null;
    }

    return (
        <div className="flex flex-wrap items-center gap-2 border-t border-zinc-800/70 pt-3">
            {chips.map((chip) => (
                <button
                    key={chip.key}
                    type="button"
                    onClick={() => onRemove(chip.key)}
                    aria-label={`Remove ${chip.prefix} filter: ${chip.label}`}
                    className="inline-flex items-center gap-1.5 rounded-lg border border-violet-500/35 bg-violet-500/12 px-2.5 py-1 text-xs font-medium text-violet-200 transition hover:bg-violet-500/20 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-500/70"
                >
                    <span className="text-violet-300/75">{chip.prefix}:</span>
                    <span>{chip.label}</span>
                    <X className="h-3 w-3 text-violet-300" />
                </button>
            ))}
            <button
                type="button"
                onClick={onClearAll}
                className="ml-1 text-xs font-medium text-zinc-400 transition hover:text-zinc-200"
            >
                Clear filters
            </button>
        </div>
    );
}
