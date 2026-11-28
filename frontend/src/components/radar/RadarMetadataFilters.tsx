import { AlertCircle, ChevronDown } from "lucide-react";
import type { ResumeProfile, SalaryPeriod } from "../../types/models";
import { formatLanguageBadge, UNKNOWN_LANGUAGE } from "../../utils/languages";
import {
    buildSalaryCurrencyOptions,
    CONTRACT_OPTIONS,
    type FilterChoice,
    isSalaryRangeInverted,
    MIN_FIT_OPTIONS,
    type RadarMetadataFilters,
    REGION_OPTIONS,
    SALARY_PERIOD_OPTIONS,
    SENIORITY_OPTIONS,
    SOURCE_OPTIONS,
    WORK_MODE_OPTIONS,
} from "../../utils/radarFilters";
import { LanguageCombobox } from "../ui/LanguageCombobox";

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

function CompensationFilterGroup({
    filters,
    preferredCurrency,
    defaultSalaryPeriod,
    availableCurrencies,
    onUpdateMetadata,
}: Readonly<{
    filters: RadarMetadataFilters;
    preferredCurrency: string;
    defaultSalaryPeriod: SalaryPeriod;
    availableCurrencies?: ReadonlyArray<string>;
    onUpdateMetadata: (patch: Partial<RadarMetadataFilters>) => void;
}>) {
    const currencyOptions = buildSalaryCurrencyOptions(availableCurrencies);
    const activeCurrency = (filters.salaryCurrency || preferredCurrency || "USD").toUpperCase();
    const activePeriod = filters.salaryPeriod || defaultSalaryPeriod;
    const isInverted = isSalaryRangeInverted(filters.minSalary, filters.maxSalary);

    return (
        <div className="space-y-3 border-t border-zinc-800/70 pt-3.5 sm:col-span-2 lg:col-span-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="text-[11px] font-medium uppercase tracking-wider text-zinc-400">
                    Compensation Filter (Cross-Currency)
                </span>
                {isInverted && (
                    <span className="inline-flex items-center gap-1 text-xs text-amber-300">
                        <AlertCircle className="h-3.5 w-3.5" />
                        Min salary must be less than or equal to max salary
                    </span>
                )}
            </div>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-5">
                <div className="min-w-0 space-y-1.5">
                    <label
                        htmlFor="radar-filter-min-salary"
                        className="block text-[11px] font-medium uppercase tracking-wider text-zinc-400"
                    >
                        Min Salary
                    </label>
                    <input
                        id="radar-filter-min-salary"
                        type="number"
                        inputMode="numeric"
                        min={0}
                        step="any"
                        placeholder={activePeriod === "monthly" ? "e.g. 20000" : "e.g. 120000"}
                        value={filters.minSalary}
                        onChange={(e) => onUpdateMetadata({ minSalary: e.target.value })}
                        className={`h-10 w-full min-w-0 rounded-xl border bg-zinc-950/80 px-3 font-mono text-sm tabular-nums text-zinc-100 placeholder:font-sans placeholder:text-zinc-500 transition focus:outline-none focus:ring-2 ${
                            isInverted
                                ? "border-amber-500/50 focus:border-amber-400 focus:ring-amber-500/25"
                                : "border-zinc-800 hover:border-zinc-700 focus:border-violet-500 focus:ring-violet-500/25"
                        }`}
                    />
                </div>

                <div className="min-w-0 space-y-1.5">
                    <label
                        htmlFor="radar-filter-max-salary"
                        className="block text-[11px] font-medium uppercase tracking-wider text-zinc-400"
                    >
                        Max Salary
                    </label>
                    <input
                        id="radar-filter-max-salary"
                        type="number"
                        inputMode="numeric"
                        min={0}
                        step="any"
                        placeholder={activePeriod === "monthly" ? "e.g. 40000" : "e.g. 220000"}
                        value={filters.maxSalary}
                        onChange={(e) => onUpdateMetadata({ maxSalary: e.target.value })}
                        className={`h-10 w-full min-w-0 rounded-xl border bg-zinc-950/80 px-3 font-mono text-sm tabular-nums text-zinc-100 placeholder:font-sans placeholder:text-zinc-500 transition focus:outline-none focus:ring-2 ${
                            isInverted
                                ? "border-amber-500/50 focus:border-amber-400 focus:ring-amber-500/25"
                                : "border-zinc-800 hover:border-zinc-700 focus:border-violet-500 focus:ring-violet-500/25"
                        }`}
                    />
                </div>

                <div className="min-w-0 space-y-1.5">
                    <label
                        htmlFor="radar-filter-salary-currency"
                        className="block text-[11px] font-medium uppercase tracking-wider text-zinc-400"
                    >
                        Currency
                    </label>
                    <div className="relative">
                        <select
                            id="radar-filter-salary-currency"
                            value={activeCurrency}
                            onChange={(e) => onUpdateMetadata({ salaryCurrency: e.target.value })}
                            className="h-10 w-full min-w-0 appearance-none truncate rounded-xl border border-zinc-800 bg-zinc-950/80 pr-9 pl-3 text-sm text-zinc-100 transition hover:border-zinc-700 focus:border-violet-500 focus:outline-none focus:ring-2 focus:ring-violet-500/25"
                        >
                            {currencyOptions.map((opt) => (
                                <option key={opt.value} value={opt.value}>
                                    {opt.label}
                                </option>
                            ))}
                        </select>
                        <ChevronDown className="pointer-events-none absolute top-3 right-3 h-4 w-4 text-zinc-500" />
                    </div>
                </div>

                <div className="min-w-0 space-y-1.5">
                    <label
                        htmlFor="radar-filter-salary-period"
                        className="block text-[11px] font-medium uppercase tracking-wider text-zinc-400"
                    >
                        Period
                    </label>
                    <div className="relative">
                        <select
                            id="radar-filter-salary-period"
                            value={activePeriod}
                            onChange={(e) =>
                                onUpdateMetadata({
                                    salaryPeriod: e.target.value as SalaryPeriod,
                                })
                            }
                            className="h-10 w-full min-w-0 appearance-none truncate rounded-xl border border-zinc-800 bg-zinc-950/80 pr-9 pl-3 text-sm text-zinc-100 transition hover:border-zinc-700 focus:border-violet-500 focus:outline-none focus:ring-2 focus:ring-violet-500/25"
                        >
                            {SALARY_PERIOD_OPTIONS.map((opt) => (
                                <option key={opt.value} value={opt.value}>
                                    {opt.label}
                                </option>
                            ))}
                        </select>
                        <ChevronDown className="pointer-events-none absolute top-3 right-3 h-4 w-4 text-zinc-500" />
                    </div>
                </div>

                <div className="min-w-0 space-y-1.5">
                    <span className="block text-[11px] font-medium uppercase tracking-wider text-zinc-400">
                        Disclosure
                    </span>
                    <label
                        htmlFor="radar-filter-disclosed-salary"
                        className={`flex h-10 w-full cursor-pointer items-center justify-between gap-2.5 rounded-xl border px-3 text-sm transition ${
                            filters.disclosedSalaryOnly
                                ? "border-emerald-500/45 bg-emerald-500/10 text-emerald-200"
                                : "border-zinc-800 bg-zinc-950/80 text-zinc-200 hover:border-zinc-700"
                        }`}
                    >
                        <span className="truncate text-xs font-medium">Salary Disclosed Only</span>
                        <input
                            id="radar-filter-disclosed-salary"
                            type="checkbox"
                            checked={filters.disclosedSalaryOnly}
                            onChange={(e) =>
                                onUpdateMetadata({ disclosedSalaryOnly: e.target.checked })
                            }
                            className="h-4 w-4 shrink-0 rounded border-zinc-700 bg-zinc-900 text-violet-500 focus:ring-violet-500/40"
                        />
                    </label>
                </div>
            </div>
        </div>
    );
}

export function MetadataFiltersPanel({
    resumes,
    resumeFilter,
    hideResumeSelect = false,
    minScore,
    filters,
    preferredCurrency = "USD",
    defaultSalaryPeriod = "annual",
    availableCurrencies,
    onResumeChange,
    onMinScoreChange,
    onUpdateMetadata,
}: Readonly<{
    resumes: ReadonlyArray<ResumeProfile>;
    resumeFilter: string;
    hideResumeSelect?: boolean;
    minScore: number;
    filters: RadarMetadataFilters;
    preferredCurrency?: string;
    defaultSalaryPeriod?: SalaryPeriod;
    availableCurrencies?: ReadonlyArray<string>;
    onResumeChange: (value: string) => void;
    onMinScoreChange: (value: number) => void;
    onUpdateMetadata: (patch: Partial<RadarMetadataFilters>) => void;
}>) {
    const activeResumes = resumes.filter((r) => r.is_active);
    const resumeOptions: FilterChoice[] = resumes.map((r) => {
        const langSuffix =
            r.language && r.language !== UNKNOWN_LANGUAGE
                ? ` (${formatLanguageBadge(r.language)})`
                : "";
        return {
            value: r.uuid,
            label: `${r.label}${langSuffix}`,
        };
    });
    const pinnedLanguageCodes = activeResumes
        .map((r) => r.language)
        .filter((code): code is string => Boolean(code && code !== UNKNOWN_LANGUAGE));
    const minFitOptions: FilterChoice[] = MIN_FIT_OPTIONS.filter((o) => o.value > 0).map((o) => ({
        value: String(o.value),
        label: o.label,
    }));

    return (
        <div className="grid grid-cols-1 gap-3.5 border-t border-zinc-800/80 pt-4 sm:grid-cols-2 lg:grid-cols-3">
            {!hideResumeSelect && (
                <FilterSelectField
                    id="radar-filter-resume"
                    label="Resume Profile"
                    allLabel={
                        activeResumes.length >= 2
                            ? "All Active Resumes (Auto-Matched)"
                            : "All resumes"
                    }
                    value={resumeFilter}
                    options={resumeOptions}
                    onChange={onResumeChange}
                />
            )}
            <LanguageCombobox
                id="radar-filter-language"
                label="Language"
                value={filters.language}
                onChange={(language) => onUpdateMetadata({ language })}
                specialOptions={[
                    { code: "", label: "All languages" },
                    { code: UNKNOWN_LANGUAGE, label: "Unknown" },
                ]}
                pinnedCodes={pinnedLanguageCodes}
                placeholder="Search any ISO 639-1 language..."
                compact
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
                id="radar-filter-work-mode"
                label="Work Mode"
                allLabel="All work modes"
                value={filters.workMode}
                options={WORK_MODE_OPTIONS}
                onChange={(workMode) => onUpdateMetadata({ workMode })}
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
            <div className="min-w-0 space-y-1.5">
                <span className="block text-[11px] font-medium uppercase tracking-wider text-zinc-400">
                    Reposts
                </span>
                <label
                    htmlFor="radar-filter-hide-reposts"
                    className={`flex h-10 w-full cursor-pointer items-center justify-between gap-3 rounded-xl border px-3 text-sm transition ${
                        filters.hideReposts
                            ? "border-amber-500/45 bg-amber-500/10 text-amber-200"
                            : "border-zinc-800 bg-zinc-950/80 text-zinc-200 hover:border-zinc-700"
                    }`}
                >
                    <span className="truncate text-xs font-medium">Hide Reposts</span>
                    <input
                        id="radar-filter-hide-reposts"
                        type="checkbox"
                        checked={filters.hideReposts}
                        onChange={(e) => onUpdateMetadata({ hideReposts: e.target.checked })}
                        className="h-4 w-4 rounded border-zinc-700 bg-zinc-900 text-violet-500 focus:ring-violet-500/40"
                    />
                </label>
            </div>
            <CompensationFilterGroup
                filters={filters}
                preferredCurrency={preferredCurrency}
                defaultSalaryPeriod={defaultSalaryPeriod}
                availableCurrencies={availableCurrencies}
                onUpdateMetadata={onUpdateMetadata}
            />
        </div>
    );
}
