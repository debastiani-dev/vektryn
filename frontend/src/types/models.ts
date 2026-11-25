export type SeniorityLevel =
    | "intern"
    | "junior"
    | "mid"
    | "senior"
    | "staff"
    | "principal"
    | "lead"
    | "manager"
    | "unknown";

export type ContractType =
    | "clt"
    | "pj"
    | "b2b_contractor"
    | "w2"
    | "c2c"
    | "eor"
    | "unknown";

export type LeadStatus =
    | "discovered"
    | "saved"
    | "applied"
    | "screening"
    | "interviewing"
    | "offer"
    | "rejected"
    | "withdrawn";

export type LeadPriority = "low" | "medium" | "high";

export type TechCategory =
    | "language"
    | "framework"
    | "database"
    | "broker"
    | "cloud"
    | "devops"
    | "ai_ml"
    | "other";

export interface JobPostingSummary {
    uuid: string;
    ats_source: string;
    external_id?: string;
    title: string;
    company_name: string;
    apply_url: string;
    location_raw: string;
    seniority: SeniorityLevel;
    contract_type: ContractType;
    region_eligibility: string[];
    salary_min: string | null;
    salary_max: string | null;
    salary_currency: string | null;
    salary_period: string | null;
    tech_stack: string[];
    is_active: boolean;
    posted_at: string | null;
    created_at?: string;
}

export interface JobPostingDetail extends JobPostingSummary {
    external_id: string;
    raw_html_gcs_uri: string;
    description_clean: string;
    closed_at: string | null;
    created_at: string;
    modified_at: string;
}

export interface MatchScore {
    uuid: string;
    job_posting: JobPostingSummary;
    resume_profile_uuid: string;
    resume_profile_label?: string;
    cosine_similarity: number;
    fit_score: number | null;
    matched_skills: string[];
    missing_keywords: string[];
    talking_points: string[];
    gap_summary: string;
    scoring_model: string;
    is_stale?: boolean;
    alert_sent_at?: string | null;
    created_at: string;
}

export interface ApplicationLead {
    uuid: string;
    job_posting: JobPostingSummary | string;
    resume_profile: string | null;
    job_title?: string;
    company_name?: string;
    apply_url?: string;
    ats_source?: string;
    status: LeadStatus;
    priority: LeadPriority;
    applied_at: string | null;
    last_activity_at: string | null;
    notes: string;
    created_at: string;
    modified_at: string;
}

export interface StackTrendDaily {
    bucket_date: string;
    tag: string;
    category: TechCategory;
    mention_count: number;
    unique_companies_count: number;
    median_annual_usd: string | null;
}

export interface LiveMatchAlert {
    event_id: string;
    user_id: string;
    job_posting_uuid: string;
    resume_profile_uuid: string;
    match_score_uuid: string;
    title: string;
    company_name: string;
    fit_score: number;
    cosine_similarity: number;
    matched_skills: string[];
    missing_keywords: string[];
    apply_url: string;
}

export interface CurrentUser {
    id: string;
    username: string;
    email: string;
    stream_token: string;
}

export interface ResumeProfile {
    uuid: string;
    label: string;
    target_seniority: SeniorityLevel[];
    target_contract_types: ContractType[];
    target_regions: string[];
    min_alert_score: number;
    raw_text: string;
    source_file_gcs_uri: string;
    content_hash: string;
    extracted_skills: string[];
    has_embedding: boolean;
    is_active: boolean;
    created_at: string;
    modified_at: string;
}

export interface PaginatedResponse<T> {
    count: number;
    next: string | null;
    previous: string | null;
    results: T[];
}

export interface MatchScoreSummary {
    ai_scored_count: number;
    strong_fit_count: number;
    alert_threshold_count: number;
}

export interface MatchScoreListResponse extends PaginatedResponse<MatchScore> {
    summary?: MatchScoreSummary;
}

export interface RescoreResponse {
    status: "queued";
    event_id: string;
    resume_profile_uuid: string;
    max_jobs: number;
    force: boolean;
}

