from enum import StrEnum


class ATSSource(StrEnum):
    # Global ATS platforms
    GREENHOUSE = "greenhouse"
    ASHBY = "ashby"
    LEVER = "lever"
    WORKABLE = "workable"
    SMARTRECRUITERS = "smartrecruiters"
    RECRUITEE = "recruitee"
    BREEZY = "breezy"
    # Brazilian ATS platforms
    GUPY = "gupy"
    SOLIDES = "solides"  # Reserved enum value (no public unauthenticated JSON feed)
    INHIRE = "inhire"
    # Multi-company feeds (Global & Brazil)
    REMOTIVE = "remotive"
    HIMALAYAS = "himalayas"
    JOBICY = "jobicy"
    TRAMPOS = "trampos"
    GITHUB_VAGAS = "github_vagas"
    # User-submitted external postings
    MANUAL = "manual"


class SeniorityLevel(StrEnum):
    INTERN = "intern"
    JUNIOR = "junior"
    MID = "mid"
    SENIOR = "senior"
    STAFF = "staff"
    PRINCIPAL = "principal"
    LEAD = "lead"
    MANAGER = "manager"
    UNKNOWN = "unknown"


class ContractType(StrEnum):
    CLT = "clt"
    PJ = "pj"
    B2B_CONTRACTOR = "b2b_contractor"
    W2 = "w2"
    C2C = "c2c"
    EOR = "eor"
    UNKNOWN = "unknown"


class RegionEligibility(StrEnum):
    BRAZIL = "brazil"
    LATAM = "latam"
    NORTH_AMERICA = "north_america"
    AMERICAS = "americas"
    EUROPE = "europe"
    EMEA = "emea"
    APAC = "apac"
    WORLDWIDE = "worldwide"
    RESTRICTED = "restricted"
    UNKNOWN = "unknown"


class SalaryPeriod(StrEnum):
    HOURLY = "hourly"
    MONTHLY = "monthly"
    ANNUAL = "annual"


class LeadStatus(StrEnum):
    DISCOVERED = "discovered"
    SAVED = "saved"
    APPLIED = "applied"
    SCREENING = "screening"
    INTERVIEWING = "interviewing"
    OFFER = "offer"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"


class LeadPriority(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class TechCategory(StrEnum):
    LANGUAGE = "language"
    FRAMEWORK = "framework"
    DATABASE = "database"
    BROKER = "broker"
    CLOUD = "cloud"
    DEVOPS = "devops"
    AI_ML = "ai_ml"
    OTHER = "other"


class NotificationKind(StrEnum):
    MATCH_ALERT = "match_alert"
    TRACKED_JOB_CLOSED = "tracked_job_closed"
    PIPELINE_ERROR = "pipeline_error"
    RESCORE_COMPLETED = "rescore_completed"
    MANUAL_IMPORT_READY = "manual_import_ready"
    COLLECTOR_SYNC_COMPLETED = "collector_sync_completed"
    LEAD_FOLLOWUP_DUE = "lead_followup_due"
    AI_QUOTA_EXHAUSTED = "ai_quota_exhausted"
    AI_KEY_INVALID = "ai_key_invalid"
