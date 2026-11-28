import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { GapAnalysisDrawer } from "../components/radar/GapAnalysisDrawer";
import { JobPostingDrawer } from "../components/radar/JobPostingDrawer";
import { RadarSearchToolbar } from "../components/radar/RadarSearchToolbar";
import type { JobPostingSummary, MatchScore, SalaryNormalizedPayload } from "../types/models";
import {
    formatNormalizedSalary,
    getDefaultSalaryCadence,
    readStoredSalaryCadence,
    writeStoredSalaryCadence,
} from "./format";
import {
    buildActiveFilterChips,
    buildMatchesQueryParams,
    countActivePanelFilters,
    EMPTY_METADATA_FILTERS,
    isSalaryRangeInverted,
    resolveRadarOrdering,
} from "./radarFilters";
import {
    hydrateRadarStateFromPreset,
    isPresetActive,
    serializeRadarStateToPreset,
} from "./savedFilters";

function createMemoryStorage(): Storage {
    const store = new Map<string, string>();
    return {
        get length() {
            return store.size;
        },
        clear() {
            store.clear();
        },
        getItem(key: string) {
            return store.get(key) ?? null;
        },
        key(index: number) {
            return Array.from(store.keys())[index] ?? null;
        },
        removeItem(key: string) {
            store.delete(key);
        },
        setItem(key: string, value: string) {
            store.set(key, value);
        },
    };
}

function makeJob(overrides: Partial<JobPostingSummary> = {}): JobPostingSummary {
    return {
        uuid: "job-1",
        ats_source: "greenhouse",
        title: "Senior Python Engineer",
        company_name: "Acme",
        apply_url: "https://boards.greenhouse.io/acme/jobs/1",
        location_raw: "Remote",
        seniority: "senior",
        contract_type: "b2b_contractor",
        work_mode: "remote",
        language: "en",
        region_eligibility: ["worldwide"],
        salary_min: "120000.00",
        salary_max: "150000.00",
        salary_currency: "USD",
        salary_period: "annual",
        salary_annual_min_usd: "120000.00",
        salary_annual_max_usd: "150000.00",
        salary_annual_mid_usd: "135000.00",
        salary_normalized: {
            currency: "BRL",
            annual_min: 696000,
            annual_max: 870000,
            monthly_min: 58000,
            monthly_max: 72500,
            is_converted: true,
            fx_as_of_date: "2026-11-28",
        },
        tech_stack: ["Python", "PostgreSQL"],
        is_active: true,
        posted_at: "2026-11-27T12:00:00Z",
        ...overrides,
    };
}

function makeMatch(jobOverrides: Partial<JobPostingSummary> = {}): MatchScore {
    return {
        uuid: "match-1",
        job_posting: makeJob(jobOverrides),
        resume_profile_uuid: "resume-1",
        cosine_similarity: 0.92,
        fit_score: 88,
        matched_skills: ["Python"],
        missing_keywords: [],
        talking_points: ["Strong backend match"],
        gap_summary: "Aligned with Python backend experience.",
        scoring_model: "gemini-3.5-flash-lite",
        created_at: "2026-11-27T12:00:00Z",
    };
}

describe("Spec #23 cross-currency salary formatting & cadence", () => {
    beforeEach(() => {
        vi.stubGlobal("localStorage", createMemoryStorage());
    });

    afterEach(() => {
        vi.unstubAllGlobals();
    });

    it("defaults cadence to monthly for BRL and annual for USD/EUR/GBP when unset", () => {
        expect(readStoredSalaryCadence()).toBeNull();
        expect(getDefaultSalaryCadence("BRL")).toBe("monthly");
        expect(getDefaultSalaryCadence("USD")).toBe("annual");
        expect(getDefaultSalaryCadence("EUR")).toBe("annual");
        expect(getDefaultSalaryCadence("GBP")).toBe("annual");

        writeStoredSalaryCadence("annual");
        expect(readStoredSalaryCadence()).toBe("annual");
    });

    it("formats converted salary with ~ prefix and original + FX date tooltip", () => {
        const job = makeJob();

        const monthly = formatNormalizedSalary(job, "monthly");
        expect(monthly?.label).toBe("~R$58k–R$72.5k/mo");
        expect(monthly?.isConverted).toBe(true);
        expect(monthly?.isUnverified).toBe(false);
        expect(monthly?.tooltip).toContain("Original: $120k–$150k/yr");
        expect(monthly?.tooltip).toContain("Converted to BRL");
        expect(monthly?.tooltip).toContain("2026-11-28");

        const annual = formatNormalizedSalary(job, "annual");
        expect(annual?.label).toBe("~R$696k–R$870k/yr");
    });

    it("omits ~ prefix for same-currency display even when cadence switches", () => {
        const nativeBrl: SalaryNormalizedPayload = {
            currency: "BRL",
            annual_min: 240000,
            annual_max: 300000,
            monthly_min: 20000,
            monthly_max: 25000,
            is_converted: false,
            fx_as_of_date: "2026-11-28",
        };
        const job = makeJob({
            salary_min: "20000.00",
            salary_max: "25000.00",
            salary_currency: "BRL",
            salary_period: "monthly",
            salary_normalized: nativeBrl,
        });

        const monthly = formatNormalizedSalary(job, "monthly");
        expect(monthly?.label).toBe("R$20k–R$25k/mo");
        expect(monthly?.label.startsWith("~")).toBe(false);

        const annual = formatNormalizedSalary(job, "annual");
        expect(annual?.label).toBe("R$240k–R$300k/yr");
        expect(annual?.label.startsWith("~")).toBe(false);
        expect(annual?.tooltip).toContain("Original: R$20k–R$25k/mo");
    });

    it("falls back to unverified range when raw salary exists but salary_normalized is null", () => {
        const job = makeJob({
            salary_min: "50.00",
            salary_max: "100.00",
            salary_currency: "USD",
            salary_period: "annual",
            salary_annual_min_usd: null,
            salary_annual_max_usd: null,
            salary_annual_mid_usd: null,
            salary_normalized: null,
        });

        const display = formatNormalizedSalary(job, "annual");
        expect(display?.isUnverified).toBe(true);
        expect(display?.label).toBe("$50–$100/yr");
        expect(display?.tooltip).toContain("Unverified range");
    });
});

describe("Spec #23 compensation filtering, sorting, and SavedFilter hygiene", () => {
    it("supports Highest Salary sort ordering and inverted range detection", () => {
        expect(resolveRadarOrdering("salary")).toBe(
            "-job_posting__salary_annual_mid_usd,-fit_score,-created_at",
        );
        expect(isSalaryRangeInverted("30000", "20000")).toBe(true);
        expect(isSalaryRangeInverted("20000", "30000")).toBe(false);
    });

    it("builds query params and active filter chips for min/max/currency/period/disclosed", () => {
        const metadataFilters = {
            ...EMPTY_METADATA_FILTERS,
            minSalary: "20000",
            maxSalary: "35000",
            salaryCurrency: "BRL",
            salaryPeriod: "monthly" as const,
            disclosedSalaryOnly: true,
        };

        expect(
            countActivePanelFilters({
                resumeFilter: "",
                minScore: 0,
                metadataFilters,
            }),
        ).toBe(3);

        const chips = buildActiveFilterChips({
            resumeFilter: "",
            minScore: 0,
            metadataFilters,
            defaultSalaryCurrency: "BRL",
            defaultSalaryPeriod: "monthly",
        });
        expect(chips).toEqual([
            { key: "minSalary", prefix: "Min Salary", label: ">= R$20k/mo" },
            { key: "maxSalary", prefix: "Max Salary", label: "<= R$35k/mo" },
            { key: "disclosedSalaryOnly", prefix: "Compensation", label: "Salary Disclosed" },
        ]);

        const qs = buildMatchesQueryParams({
            page: 1,
            minScore: 0,
            resumeFilter: "",
            evaluatedOnly: false,
            untrackedOnly: false,
            hideDismissed: true,
            hideMuted: true,
            sortBy: "salary",
            search: "python",
            metadataFilters,
            preferredCurrency: "BRL",
            defaultSalaryPeriod: "monthly",
        });
        expect(qs).toContain("min_salary=20000");
        expect(qs).toContain("max_salary=35000");
        expect(qs).toContain("salary_currency=BRL");
        expect(qs).toContain("salary_period=monthly");
        expect(qs).toContain("disclosed_salary_only=true");
        expect(qs).toContain("ordering=-job_posting__salary_annual_mid_usd");
    });

    it("enforces SavedFilter salary param hygiene (Refinement #5)", () => {
        const baseState = {
            searchTerm: "",
            resumeFilter: "",
            minScore: 0,
            evaluatedOnly: false,
            untrackedOnly: false,
            hideDismissed: true,
            hideMuted: true,
            metadataFilters: { ...EMPTY_METADATA_FILTERS },
            sortBy: "best_match" as const,
        };

        const disclosedOnly = serializeRadarStateToPreset(
            {
                ...baseState,
                metadataFilters: {
                    ...EMPTY_METADATA_FILTERS,
                    salaryCurrency: "BRL",
                    salaryPeriod: "monthly",
                    disclosedSalaryOnly: true,
                },
            },
            { currency: "BRL", period: "monthly" },
        );
        expect(disclosedOnly).toEqual({ disclosed_salary_only: true });

        const withBound = serializeRadarStateToPreset(
            {
                ...baseState,
                metadataFilters: {
                    ...EMPTY_METADATA_FILTERS,
                    minSalary: "20000",
                },
                sortBy: "salary",
            },
            { currency: "BRL", period: "monthly" },
        );
        expect(withBound).toEqual({
            min_salary: 20000,
            salary_currency: "BRL",
            salary_period: "monthly",
            sort_by: "salary",
        });

        const hydrated = hydrateRadarStateFromPreset(withBound, []);
        expect(hydrated.metadataFilters.minSalary).toBe("20000");
        expect(hydrated.metadataFilters.salaryCurrency).toBe("BRL");
        expect(hydrated.metadataFilters.salaryPeriod).toBe("monthly");
        expect(hydrated.sortBy).toBe("salary");
        expect(
            isPresetActive(hydrated, withBound, [], { currency: "USD", period: "annual" }),
        ).toBe(true);
    });
});

describe("Spec #23 UI rendering", () => {
    it("renders Annual/Monthly cadence toggle and compensation controls in RadarSearchToolbar", () => {
        const html = renderToStaticMarkup(
            <RadarSearchToolbar
                searchTerm=""
                debouncedSearch=""
                searchMode={null}
                loading={false}
                shownCount={1}
                totalCount={1}
                resumes={[]}
                resumeFilter=""
                minScore={0}
                evaluatedOnly={false}
                untrackedOnly={false}
                hideDismissed
                hideMuted
                hiddenMutedCount={0}
                sortBy="salary"
                metadataFilters={{
                    ...EMPTY_METADATA_FILTERS,
                    minSalary: "20000",
                    disclosedSalaryOnly: true,
                }}
                filtersOpen
                hasActiveFilters
                preferredCurrency="BRL"
                salaryCadence="monthly"
                availableCurrencies={["USD", "BRL", "EUR", "GBP", "CHF"]}
                onChangeSalaryCadence={() => undefined}
                onSearchChange={() => undefined}
                onCommitSearch={() => undefined}
                onClearSearch={() => undefined}
                onToggleEvaluatedOnly={() => undefined}
                onToggleUntrackedOnly={() => undefined}
                onOpenTriageModal={() => undefined}
                onToggleFiltersOpen={() => undefined}
                onSortChange={() => undefined}
                onResumeChange={() => undefined}
                onMinScoreChange={() => undefined}
                onUpdateMetadata={() => undefined}
                onRemoveChip={() => undefined}
                onResetAll={() => undefined}
            />,
        );

        expect(html).toContain("Highest Salary");
        expect(html).toContain("Annual");
        expect(html).toContain("Monthly");
        expect(html).toContain('aria-pressed="true"');
        expect(html).toContain("Min Salary");
        expect(html).toContain("Max Salary");
        expect(html).toContain("Salary Disclosed Only");
        expect(html).toContain("CHF");
    });

    it("renders normalized converted salary and original provenance in JobPostingDrawer and GapAnalysisDrawer", () => {
        const job = makeJob();
        const drawerHtml = renderToStaticMarkup(
            <JobPostingDrawer jobPreview={job} salaryCadence="monthly" onClose={() => undefined} />,
        );
        expect(drawerHtml).toContain("~R$58k–R$72.5k/mo");
        expect(drawerHtml).toContain("Original: $120k–$150k/yr");
        expect(drawerHtml).toContain("FX 2026-11-28");

        const gapHtml = renderToStaticMarkup(
            <GapAnalysisDrawer
                match={makeMatch()}
                salaryCadence="annual"
                saving={false}
                saved={false}
                onClose={() => undefined}
                onSaveLead={() => undefined}
            />,
        );
        expect(gapHtml).toContain("~R$696k–R$870k/yr");

        const unverifiedHtml = renderToStaticMarkup(
            <JobPostingDrawer
                jobPreview={makeJob({
                    salary_min: "50.00",
                    salary_max: "100.00",
                    salary_normalized: null,
                })}
                salaryCadence="annual"
                onClose={() => undefined}
            />,
        );
        expect(unverifiedHtml).toContain("Unverified range");
    });
});
