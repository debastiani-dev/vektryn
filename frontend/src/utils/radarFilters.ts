export interface RadarMetadataFilters {
    seniority: string;
    contractType: string;
    region: string;
    atsSource: string;
}

export const EMPTY_METADATA_FILTERS: RadarMetadataFilters = {
    seniority: "",
    contractType: "",
    region: "",
    atsSource: "",
};

export interface FilterChoice {
    value: string;
    label: string;
}

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

export function lookupOptionLabel(options: ReadonlyArray<FilterChoice>, value: string): string {
    return options.find((opt) => opt.value === value)?.label ?? value;
}

export function countActiveMetadataFilters(filters: RadarMetadataFilters): number {
    let count = 0;
    if (filters.seniority) count += 1;
    if (filters.contractType) count += 1;
    if (filters.region) count += 1;
    if (filters.atsSource) count += 1;
    return count;
}
