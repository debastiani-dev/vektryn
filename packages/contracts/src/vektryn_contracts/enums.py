from enum import StrEnum


class ATSSource(StrEnum):
    GREENHOUSE = "greenhouse"
    LEVER = "lever"
    ASHBY = "ashby"
    WORKABLE = "workable"
    FEED = "feed"


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