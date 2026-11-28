from enum import StrEnum
from typing import Final

UNKNOWN_LANGUAGE: Final[str] = "unknown"

ISO_639_1_CODES: Final[frozenset[str]] = frozenset(
    {
        "aa",
        "ab",
        "ae",
        "af",
        "ak",
        "am",
        "an",
        "ar",
        "as",
        "av",
        "ay",
        "az",
        "ba",
        "be",
        "bg",
        "bh",
        "bi",
        "bm",
        "bn",
        "bo",
        "br",
        "bs",
        "ca",
        "ce",
        "ch",
        "co",
        "cr",
        "cs",
        "cu",
        "cv",
        "cy",
        "da",
        "de",
        "dv",
        "dz",
        "ee",
        "el",
        "en",
        "eo",
        "es",
        "et",
        "eu",
        "fa",
        "ff",
        "fi",
        "fj",
        "fo",
        "fr",
        "fy",
        "ga",
        "gd",
        "gl",
        "gn",
        "gu",
        "gv",
        "ha",
        "he",
        "hi",
        "ho",
        "hr",
        "ht",
        "hu",
        "hy",
        "hz",
        "ia",
        "id",
        "ie",
        "ig",
        "ii",
        "ik",
        "io",
        "is",
        "it",
        "iu",
        "ja",
        "jv",
        "ka",
        "kg",
        "ki",
        "kj",
        "kk",
        "kl",
        "km",
        "kn",
        "ko",
        "kr",
        "ks",
        "ku",
        "kv",
        "kw",
        "ky",
        "la",
        "lb",
        "lg",
        "li",
        "ln",
        "lo",
        "lt",
        "lu",
        "lv",
        "mg",
        "mh",
        "mi",
        "mk",
        "ml",
        "mn",
        "mr",
        "ms",
        "mt",
        "my",
        "na",
        "nb",
        "nd",
        "ne",
        "ng",
        "nl",
        "nn",
        "no",
        "nr",
        "nv",
        "ny",
        "oc",
        "oj",
        "om",
        "or",
        "os",
        "pa",
        "pi",
        "pl",
        "ps",
        "pt",
        "qu",
        "rm",
        "rn",
        "ro",
        "ru",
        "rw",
        "sa",
        "sc",
        "sd",
        "se",
        "sg",
        "si",
        "sk",
        "sl",
        "sm",
        "sn",
        "so",
        "sq",
        "sr",
        "ss",
        "st",
        "su",
        "sv",
        "sw",
        "ta",
        "te",
        "tg",
        "th",
        "ti",
        "tk",
        "tl",
        "tn",
        "to",
        "tr",
        "ts",
        "tt",
        "tw",
        "ty",
        "ug",
        "uk",
        "ur",
        "uz",
        "ve",
        "vi",
        "vo",
        "wa",
        "wo",
        "xh",
        "yi",
        "yo",
        "za",
        "zh",
        "zu",
    }
)

VALID_LANGUAGE_CODES: Final[frozenset[str]] = ISO_639_1_CODES | {UNKNOWN_LANGUAGE}


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


class WorkMode(StrEnum):
    REMOTE = "remote"
    HYBRID = "hybrid"
    ONSITE = "onsite"
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
