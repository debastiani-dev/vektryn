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

export type WorkMode = "remote" | "hybrid" | "onsite" | "unknown";

export type SalaryPeriod = "hourly" | "monthly" | "annual";
export type SalaryDisplayCadence = "annual" | "monthly";

export interface SalaryNormalizedPayload {
    currency: string;
    annual_min: number | null;
    annual_max: number | null;
    monthly_min: number | null;
    monthly_max: number | null;
    is_converted: boolean;
    fx_as_of_date: string;
}

export interface FxRatesResponse {
    base: string;
    as_of_date: string;
    source: string;
    rates: Record<string, number>;
}

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

export interface JobPostingSource {
    uuid: string;
    ats_source: string;
    apply_url: string;
    is_primary: boolean;
    is_active: boolean;
    first_seen_at: string;
    last_seen_at: string;
}

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
    work_mode: WorkMode;
    language?: string;
    region_eligibility: string[];
    salary_min: string | null;
    salary_max: string | null;
    salary_currency: string | null;
    salary_period: string | null;
    salary_annual_min_usd?: string | null;
    salary_annual_max_usd?: string | null;
    salary_annual_mid_usd?: string | null;
    salary_normalized?: SalaryNormalizedPayload | null;
    tech_stack: string[];
    is_active: boolean;
    posted_at: string | null;
    created_at?: string;
    repost_count?: number;
    last_reposted_at?: string | null;
    sources_count?: number;
    primary_source?: string;
    observed_sources?: string[];
}

export interface JobPostingDetail extends JobPostingSummary {
    external_id: string;
    raw_html_gcs_uri: string;
    description_clean: string;
    closed_at: string | null;
    created_at: string;
    modified_at: string;
    sources?: JobPostingSource[];
}

export interface ResumeProfileSummary {
    uuid: string;
    label: string;
    language: string;
}

export interface MatchScore {
    uuid: string;
    job_posting: JobPostingSummary;
    resume_profile_uuid: string;
    resume_profile_label?: string;
    resume_profile_summary?: ResumeProfileSummary;
    resume_min_alert_score?: number;
    is_routed_winner?: boolean;
    cosine_similarity: number;
    fit_score: number | null;
    matched_skills: string[];
    missing_keywords: string[];
    talking_points: string[];
    gap_summary: string;
    fit_highlights?: string[];
    watchout_note?: string;
    scoring_model: string;
    is_stale?: boolean;
    alert_sent_at?: string | null;
    created_at: string;
}

export interface ApplicationLead {
    uuid: string;
    job_posting: JobPostingSummary | string;
    resume_profile: string | null;
    resume_profile_summary?: ResumeProfileSummary | null;
    job_title?: string;
    company_name?: string;
    apply_url?: string;
    ats_source?: string;
    primary_source?: string;
    work_mode?: WorkMode;
    language?: string;
    repost_count?: number;
    last_reposted_at?: string | null;
    salary_min?: string | null;
    salary_max?: string | null;
    salary_currency?: string | null;
    salary_period?: string | null;
    salary_annual_min_usd?: string | null;
    salary_annual_max_usd?: string | null;
    salary_annual_mid_usd?: string | null;
    salary_normalized?: SalaryNormalizedPayload | null;
    status: LeadStatus;
    priority: LeadPriority;
    applied_at: string | null;
    last_activity_at: string | null;
    next_action_at: string | null;
    notes: string;
    created_at: string;
    modified_at: string;
}

export interface SavedFilterQueryParams {
    search?: string;
    resume_profile?: string;
    min_score?: number;
    evaluated_only?: boolean;
    seniority?: string;
    contract_type?: string;
    work_mode?: string;
    language?: string;
    region?: string;
    ats_source?: string;
    sort_by?: string;
    hide_dismissed?: boolean;
    hide_muted?: boolean;
    hide_reposts?: boolean;
    untracked_only?: boolean;
    min_salary?: number;
    max_salary?: number;
    salary_currency?: string;
    salary_period?: SalaryPeriod;
    disclosed_salary_only?: boolean;
}

export interface DismissedJob {
    uuid: string;
    job_posting: string;
    job_title: string;
    company_name: string;
    ats_source: string;
    created_at: string;
}

export interface MutedCompany {
    uuid: string;
    company_name_display: string;
    company_name_normalized: string;
    created_at: string;
}

export interface SavedFilter {
    uuid: string;
    name: string;
    query_params: SavedFilterQueryParams;
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

export interface StackTrendSeriesResponse {
    dates: string[];
    tags: string[];
    results: StackTrendDaily[];
}

export interface LiveMatchAlert {
    event_id: string;
    notification_uuid?: string | null;
    user_id: string;
    job_posting_uuid: string;
    resume_profile_uuid: string;
    resume_profile_label?: string;
    resume_language?: string;
    match_score_uuid: string;
    title: string;
    company_name: string;
    fit_score: number;
    cosine_similarity: number;
    matched_skills: string[];
    missing_keywords: string[];
    apply_url: string;
}

export type NotificationKind =
    | "match_alert"
    | "tracked_job_closed"
    | "pipeline_error"
    | "rescore_completed"
    | "manual_import_ready"
    | "collector_sync_completed"
    | "lead_followup_due"
    | "ai_quota_exhausted"
    | "ai_key_invalid";

export interface NotificationPayload {
    job_posting_uuid?: string;
    resume_profile_uuid?: string;
    resume_profile_label?: string;
    resume_language?: string;
    match_score_uuid?: string;
    lead_uuid?: string;
    lead_status?: string;
    title?: string;
    company_name?: string;
    fit_score?: number;
    cosine_similarity?: number;
    matched_skills?: string[];
    missing_keywords?: string[];
    apply_url?: string;
    source?: string;
    error_type?: string;
    error_message?: string;
    [key: string]: unknown;
}

export interface NotificationItem {
    uuid: string;
    kind: NotificationKind;
    title: string;
    body: string;
    payload: NotificationPayload;
    read_at: string | null;
    dismissed_at: string | null;
    is_read: boolean;
    created_at: string;
    modified_at: string;
}

export interface NotificationListResponse extends PaginatedResponse<NotificationItem> {
    unread_count: number;
}

export interface NotificationActionResponse {
    notification: NotificationItem;
    unread_count: number;
}

export interface ReadAllNotificationsResponse {
    updated_count: number;
    unread_count: number;
}

export type PreferredCurrency = "USD" | "BRL" | "EUR" | "GBP";

export type PreferredGeminiModel =
    | "auto"
    | "gemini-4-carbon"
    | "gemini-4-neon"
    | "gemini-4-argon"
    | "gemini-4-hydrogen"
    | "gemini-3.8-flash"
    | "gemini-3.5-flash-lite";

export interface BaseUserProfileSummary {
    display_name: string;
    timezone: string;
    preferred_currency: PreferredCurrency;
    default_copilot_tone: CopilotTone;
}

export interface UserProfileSummary extends BaseUserProfileSummary {
    has_gemini_api_key?: boolean;
    gemini_api_key_last4?: string;
    preferred_gemini_model?: PreferredGeminiModel;
    allow_model_fallback?: boolean;
}

export interface UserProfileDetail extends UserProfileSummary {
    id: string;
    username: string;
    email: string;
    is_staff: boolean;
    is_superuser: boolean;
    linkedin_url: string;
    github_url: string;
    portfolio_url: string;
    has_gemini_api_key: boolean;
    gemini_api_key_last4: string;
    preferred_gemini_model: PreferredGeminiModel;
    allow_model_fallback: boolean;
    pending_resumes_embedded?: number;
    pending_resumes_remaining?: number;
    embedding_warning?: string | null;
    created_at: string;
    modified_at: string;
}

export interface UserProfileUpdateInput {
    email?: string;
    display_name?: string;
    timezone?: string;
    preferred_currency?: PreferredCurrency;
    default_copilot_tone?: CopilotTone;
    linkedin_url?: string;
    github_url?: string;
    portfolio_url?: string;
    gemini_api_key?: string | null;
    preferred_gemini_model?: PreferredGeminiModel;
    allow_model_fallback?: boolean;
}

export interface CurrentUser {
    id: string;
    username: string;
    email: string;
    is_staff?: boolean;
    is_superuser?: boolean;
    stream_token: string;
    profile?: UserProfileSummary;
}

export interface ChangePasswordInput {
    current_password: string;
    new_password: string;
    confirm_password?: string;
}

export interface ChangePasswordResponse {
    detail: string;
}

export interface AccountDeactivateResponse {
    detail: string;
}

export interface StaffManagedUserProfile extends BaseUserProfileSummary {
    linkedin_url: string;
    github_url: string;
    portfolio_url: string;
}

export interface StaffManagedUser {
    id: number;
    username: string;
    email: string;
    is_active: boolean;
    is_staff: boolean;
    is_superuser: boolean;
    date_joined: string;
    last_login: string | null;
    profile: StaffManagedUserProfile;
}

export interface StaffUserCreateInput {
    username: string;
    email?: string;
    password: string;
    is_staff?: boolean;
    is_active?: boolean;
    profile?: Partial<StaffManagedUserProfile>;
}

export interface StaffUserUpdateInput {
    email?: string;
    is_active?: boolean;
    is_staff?: boolean;
    profile?: Partial<StaffManagedUserProfile>;
}

export interface ResumeProfile {
    uuid: string;
    label: string;
    target_seniority: SeniorityLevel[];
    target_contract_types: ContractType[];
    target_regions: string[];
    target_work_modes: WorkMode[];
    language?: string;
    strict_language_match?: boolean;
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

export type HybridSearchMode = "hybrid" | "keyword";

export interface MatchScoreListResponse extends PaginatedResponse<MatchScore> {
    summary?: MatchScoreSummary;
    search_mode?: HybridSearchMode | null;
}

export interface RescoreResponse {
    status: "queued";
    event_id: string;
    resume_profile_uuid: string;
    max_jobs: number;
    force: boolean;
}

export interface ManualJobImportInput {
    url?: string;
    title?: string;
    company_name?: string;
    apply_url?: string;
    location_raw?: string;
    description?: string;
}

export interface ManualJobImportResponse {
    status: "queued" | "already_exists" | "reactivated";
    ats_source: string;
    external_id: string;
    content_hash: string;
    title: string;
    company_name: string;
    apply_url: string;
    event_id: string | null;
    job_posting_uuid: string | null;
    merged_into_existing?: boolean;
}

export type PipelineOverallStatus = "healthy" | "warning" | "degraded";
export type DlqHealthStatus = "healthy" | "warning" | "unavailable";
export type WorkerLivenessStatus = "alive" | "stale" | "offline" | "unknown";
export type WorkerHealthStatus = "healthy" | "warning" | "degraded" | "unavailable";

export interface WorkerHeartbeatItem {
    worker: string;
    status: WorkerLivenessStatus;
    last_heartbeat_at: string | null;
    last_message_at: string | null;
    processed_count: number;
    age_seconds: number | null;
}

export interface WorkersHealthSummary {
    status: WorkerHealthStatus;
    items: WorkerHeartbeatItem[];
}

export interface CollectorSourceLog {
    source: string;
    fetched_count: number;
    ingested_count: number;
    deduped_count: number;
    error_count: number;
    duration_ms: number;
    ran_at: string;
}

export interface PipelineStatusResponse {
    overall_status: PipelineOverallStatus;
    status_reasons?: string[];
    last_collect_at: string | null;
    latest_run_totals: {
        fetched_count: number;
        ingested_count: number;
        deduped_count: number;
        error_count: number;
        duration_ms: number;
    };
    sources: CollectorSourceLog[];
    jobs: {
        active_count: number;
        matched_active_count?: number;
        ai_scored_count: number;
        unscored_active_count: number;
        pending_match_count: number;
        recent_unmatched_count: number;
        unembedded_active_count: number;
    };
    rollup: {
        latest_bucket_date: string | null;
        latest_updated_at: string | null;
    };
    dlq: {
        status: DlqHealthStatus;
        recent_24h_count: number | null;
        total_count: number | null;
    };
    workers?: WorkersHealthSummary;
    collect_trigger: {
        can_trigger: boolean;
        is_running?: boolean;
        running_started_at?: string | null;
        cooldown_remaining_seconds: number;
    };
}

export type ReplayableTopic = "jobs.raw" | "jobs.enriched" | "jobs.rescore";

export interface DlqMessageItem {
    event_id: string;
    original_topic: string;
    partition: number;
    offset: number;
    dlq_partition: number;
    dlq_offset: number;
    error_type: string;
    error_message: string;
    retry_count: number;
    produced_at: string | null;
    payload_preview: string;
    payload_truncated: boolean;
    replayable: boolean;
    replayed_at: string | null;
    dismissed_at: string | null;
}

export interface DlqDismissResponse {
    dismissed_count: number;
    dismissed_at: string | null;
    event_ids: string[];
}

export interface DlqInspectResponse {
    total_count: number;
    returned_count: number;
    limit: number;
    replay_cooldown_remaining_seconds: number;
    items: DlqMessageItem[];
}

export interface DlqReplayRequest {
    dry_run?: boolean;
    event_ids?: string[];
    limit?: number;
    original_topic?: ReplayableTopic;
}

export interface DlqReplayItemResult {
    event_id: string;
    original_topic: string;
    dlq_partition: number;
    dlq_offset: number;
    status: "would_replay" | "replayed" | "skipped" | "failed";
    reason: string;
}

export interface DlqReplayResponse {
    dry_run: boolean;
    matched_count: number;
    replayed_count: number;
    skipped_count: number;
    failed_count: number;
    cooldown_seconds: number;
    items: DlqReplayItemResult[];
}

export interface TriggerCollectResponse {
    status: "queued";
    mode: "cloud_run_job" | "stream_edge_local";
    job_name: string;
    execution_id: string | null;
    cooldown_seconds: number;
}

export type MatchArtifactKind =
    | "tailored_bullets"
    | "cover_letter"
    | "recruiter_outreach"
    | "interview_questions"
    | "questions_to_ask";

export type CopilotTone =
    | "balanced"
    | "concise"
    | "executive"
    | "technical"
    | "conversational";

export interface MatchArtifact {
    uuid: string;
    match_score: string;
    kind: MatchArtifactKind;
    resume_content_hash: string;
    content_markdown: string;
    model_name: string;
    is_stale: boolean;
    created_at: string;
    modified_at: string;
}

export interface MatchArtifactListResponse {
    results: MatchArtifact[];
}

export interface MatchArtifactGenerateInput {
    kind: MatchArtifactKind;
    regenerate?: boolean;
    tone?: CopilotTone;
    guidance?: string;
}

export interface MatchArtifactGenerateResponse extends MatchArtifact {
    cached: boolean;
}

export type PersonalAnalyticsWindow = "30" | "90" | "all";

export interface FunnelStageMetric {
    key: "tracked" | "applied" | "screening" | "interviewing" | "offer";
    label: string;
    count: number;
    conversion_from_previous_pct: number | null;
}

export interface PersonalFunnelMetrics {
    total_leads: number;
    status_counts: Record<LeadStatus, number>;
    stages: FunnelStageMetric[];
    applied_to_offer_pct: number | null;
    median_days_since_applied: number | null;
}

export interface ChannelPerformanceMetric {
    key: string;
    total_leads: number;
    applied_count: number;
    response_count: number;
    interview_count: number;
    offer_count: number;
    response_rate_pct: number | null;
    interview_rate_pct: number | null;
}

export interface SkillGapMetric {
    skill: string;
    match_count: number;
    pct_of_high_fit: number | null;
    avg_fit_score: number | null;
}

export interface PersonalAnalyticsResponse {
    window: {
        days: number | null;
        label: string;
        resume_profile_uuid: string | null;
    };
    funnel: PersonalFunnelMetrics;
    channels: {
        by_ats_source: ChannelPerformanceMetric[];
        by_contract_type: ChannelPerformanceMetric[];
    };
    skill_gaps: {
        high_fit_match_count: number;
        missing_keywords: SkillGapMetric[];
        matched_skills: SkillGapMetric[];
    };
}

