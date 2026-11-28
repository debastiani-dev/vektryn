import type { WorkMode } from "../../types/models";

export type PreviewTabId = "radar" | "tracker" | "analytics" | "resumes";
export type RadarPreviewFilter = "all" | "remote" | "high_fit" | "unapplied";
export type CopilotPreviewMode = "gap" | "copilot";
export type CopilotArtifactKind =
    | "tailored_bullets"
    | "cover_letter"
    | "recruiter_outreach"
    | "interview_questions"
    | "questions_to_ask";
export type AnalyticsPreviewSubTab = "market" | "personal";
export type StackCategoryFilter = "all" | "Language" | "Database" | "Broker" | "DevOps";
export type StackSortField = "mentions" | "medianUsdValue";
export type PersonalWindowOption = "7d" | "30d" | "90d";
export type KanbanPriority = "low" | "medium" | "high";

export interface PreviewTabMeta {
    id: PreviewTabId;
    label: string;
}

export interface RadarPreviewRole {
    id: string;
    title: string;
    company: string;
    location: string;
    source: string;
    additionalSources?: string[];
    repostCount?: number;
    seniority: string;
    workMode: WorkMode;
    language: "EN" | "PT";
    matchedResume: string;
    postedAge: string;
    region: "Global Remote" | "Brazil / LATAM";
    contract: string;
    salary: string;
    fitScore: number;
    vectorPercent: number;
    alertTriggered: boolean;
    tracked: boolean;
    stack: string[];
    matchedSkills: string[];
}

export interface CopilotDraftPreview {
    kind: CopilotArtifactKind;
    label: string;
    tone: string;
    heading: string;
    lines: string[];
}

export interface KanbanPreviewCard {
    id: string;
    title: string;
    company: string;
    salary: string;
    workMode: WorkMode;
    fitScore: number;
    priority: KanbanPriority;
    followupLabel?: string;
    overdue?: boolean;
}

export interface KanbanPreviewColumn {
    id: string;
    label: string;
    dotClass: string;
    topBorderClass: string;
    cards: KanbanPreviewCard[];
}

export interface StackDemandPreviewRow {
    rank: number;
    tech: string;
    category: Exclude<StackCategoryFilter, "all">;
    categoryClass: string;
    mentions: number;
    companies: number;
    medianUsd: string;
    medianUsdValue: number;
    barPct: number;
}

export interface StackVelocitySeriesPreview {
    tech: string;
    color: string;
    dotClass: string;
    points: number[];
}

export interface ChannelPerformancePreviewRow {
    source: string;
    tracked: number;
    applied: number;
    responsePct: string;
    interviewPct: string;
}

export interface FunnelStagePreview {
    key: string;
    label: string;
    count: number;
    conversionPct: string | null;
    widthPct: number;
    barGradient: string;
}

export interface SkillGapBar {
    skill: string;
    mentions: number;
    sharePct: number;
}

export interface PersonalWindowSnapshot {
    label: string;
    tracked: number;
    responseRate: string;
    interviewRate: string;
    offers: number;
    rejected: number;
    withdrawn: number;
    funnel: FunnelStagePreview[];
}

export interface PipelineWorkerPreview {
    name: string;
    processed: number;
    heartbeat: string;
}

export interface ResumeProfilePreview {
    id: string;
    label: string;
    active: boolean;
    alertThreshold: number;
    targetWorkModes: WorkMode[];
    targetRegions: string[];
    targetSeniority: string[];
    targetContracts: string[];
    extractedSkills: string[];
    updatedAt: string;
}

export const VEKTRYN_GITHUB_URL = "https://github.com/debastiani-dev/vektryn";

export const INGESTED_SOURCES_STRIP = [
    "Greenhouse",
    "Ashby",
    "Lever",
    "Workable",
    "SmartRecruiters",
    "Recruitee",
    "Breezy",
    "InHire",
    "Remotive",
    "Himalayas",
    "Jobicy",
    "Gupy",
    "Trampos",
    "GitHub Vagas",
];

export const PREVIEW_TABS: PreviewTabMeta[] = [
    { id: "radar", label: "Job Radar" },
    { id: "tracker", label: "Pipeline Tracker" },
    { id: "analytics", label: "Stack Trends" },
    { id: "resumes", label: "Resumes" },
];

export const PREVIEW_WORK_MODE_OPTIONS: ReadonlyArray<{ value: WorkMode; label: string }> = [
    { value: "remote", label: "Remote" },
    { value: "hybrid", label: "Hybrid" },
    { value: "onsite", label: "On-site" },
    { value: "unknown", label: "Unknown" },
];

export const RADAR_PREVIEW_FILTERS: Array<{ id: RadarPreviewFilter; label: string }> = [
    { id: "all", label: "All Roles" },
    { id: "remote", label: "Remote Only" },
    { id: "high_fit", label: "High Fit >= 85" },
    { id: "unapplied", label: "Unapplied Only" },
];

export const RADAR_PREVIEW_ROLES: RadarPreviewRole[] = [
    {
        id: "role-1",
        title: "Senior Backend Engineer — Distributed Systems",
        company: "Linearity Labs",
        location: "Remote · Global",
        source: "Ashby",
        additionalSources: ["Remotive", "Himalayas"],
        seniority: "Senior",
        workMode: "remote",
        language: "EN",
        matchedResume: "Senior Backend",
        postedAge: "2h ago",
        region: "Global Remote",
        contract: "B2B Contractor",
        salary: "$145k – $175k",
        fitScore: 92,
        vectorPercent: 86,
        alertTriggered: true,
        tracked: false,
        stack: ["Python", "Django", "Kafka", "PostgreSQL", "Docker", "Kubernetes"],
        matchedSkills: ["Python", "Django", "Kafka", "PostgreSQL", "Docker"],
    },
    {
        id: "role-2",
        title: "Staff Platform Engineer (Data & Streaming)",
        company: "NuvemPay",
        location: "Remote · Brazil / LATAM",
        source: "Greenhouse",
        repostCount: 1,
        seniority: "Staff",
        workMode: "remote",
        language: "PT",
        matchedResume: "Staff Platform",
        postedAge: "5h ago",
        region: "Brazil / LATAM",
        contract: "PJ",
        salary: "$120k – $140k",
        fitScore: 88,
        vectorPercent: 81,
        alertTriggered: true,
        tracked: true,
        stack: ["Python", "FastAPI", "Redis", "pgvector", "Terraform", "Go"],
        matchedSkills: ["Python", "FastAPI", "Redis", "pgvector", "Terraform"],
    },
    {
        id: "role-3",
        title: "Senior Fullstack Engineer — Python + React",
        company: "Helios Cloud",
        location: "Sao Paulo · 2d/wk office",
        source: "Lever",
        seniority: "Senior",
        workMode: "hybrid",
        language: "PT",
        matchedResume: "Fullstack",
        postedAge: "1d ago",
        region: "Brazil / LATAM",
        contract: "CLT",
        salary: "$110k – $135k",
        fitScore: 81,
        vectorPercent: 77,
        alertTriggered: false,
        tracked: false,
        stack: ["TypeScript", "React", "Python", "PostgreSQL", "GCP", "GraphQL"],
        matchedSkills: ["TypeScript", "React", "Python", "PostgreSQL", "GCP"],
    },
];

export const GAP_ANALYSIS_PREVIEW = {
    roleTitle: "Senior Backend Engineer — Distributed Systems",
    company: "Linearity Labs",
    location: "Remote · Global",
    workMode: "remote" as WorkMode,
    source: "Ashby",
    contract: "B2B Contractor",
    salary: "$145k – $175k",
    fitScore: 92,
    vectorPercent: 86,
    scoringModel: "gemini-4-carbon",
    summary:
        "Strong alignment across Python/Django APIs, Kafka event streaming, and PostgreSQL vector/relational indexing.",
    highlights: [
        "Direct overlap with idempotent Kafka consumers, Redis deduplication, and dead-letter replay.",
        "Production experience building hybrid pgvector + LLM pipelines maps cleanly to their search roadmap.",
        "Terraform IaC and GCP Cloud Run deployments align with their lean platform team model.",
    ],
    watchoutNote:
        "Role lists multi-cluster Kubernetes HPA as a nice-to-have; frame Cloud Run autoscaling and container ops clearly.",
    matchedSkills: ["Python", "Django", "Apache Kafka", "PostgreSQL", "Redis", "Docker"],
    missingKeywords: ["Kubernetes HPA", "gRPC Protobuf"],
};

export const COPILOT_DRAFTS_PREVIEW: CopilotDraftPreview[] = [
    {
        kind: "tailored_bullets",
        label: "Tailored Bullets",
        tone: "Technical",
        heading: "Tailored Resume Bullets",
        lines: [
            "Designed an idempotent Kafka + Redis ingestion pipeline processing 120k+ daily webhook events with zero duplicate downstream writes and automated DLQ replay.",
            "Led PostgreSQL query and pgvector HNSW index tuning across multi-tenant search endpoints, cutting p95 latency from 640ms to 85ms.",
            "Standardized cloud services and private VPC networking in Terraform, reducing production deployment lead time by 60%.",
        ],
    },
    {
        kind: "cover_letter",
        label: "Cover Letter",
        tone: "Balanced",
        heading: "Draft Cover Letter — Linearity Labs",
        lines: [
            "Hi Linearity Labs Engineering Team — I'm applying for the Senior Backend Engineer role on Distributed Systems.",
            "Over the past six years I've built high-throughput Python/Django APIs, Kafka event pipelines, and PostgreSQL-backed search services designed for reliability under burst load.",
            "I'd love to discuss how my background in distributed event processing and cloud infrastructure can support your platform roadmap.",
        ],
    },
    {
        kind: "recruiter_outreach",
        label: "Outreach",
        tone: "Concise",
        heading: "Direct Hiring Manager / Recruiter Note",
        lines: [
            "Hi [Name] — saw your Senior Backend Engineer opening at Linearity Labs. My core stack matches closely (Python, Django, Kafka event pipelines, PostgreSQL, GCP/Terraform).",
            "Happy to share a brief system design overview and my resume if you're still reviewing candidates this week.",
        ],
    },
    {
        kind: "interview_questions",
        label: "Interview Prep",
        tone: "Technical",
        heading: "Likely Interview Questions & Grounded Angles",
        lines: [
            "How do you prevent duplicate side effects in Kafka consumers under rebalances? Anchor on SHA-256 content hashes + Redis locks + Postgres UPSERT idempotency.",
            "How would you keep hybrid lexical + vector search p95 under 100ms? Anchor on pgvector HNSW + PostgreSQL tsvector + Reciprocal Rank Fusion.",
        ],
    },
    {
        kind: "questions_to_ask",
        label: "Ask Them",
        tone: "Executive",
        heading: "High-Signal Questions for the Team",
        lines: [
            "What is the highest-leverage reliability or throughput bottleneck in the event pipeline over the next two quarters?",
            "How are schema evolution and dead-letter recovery owned across backend and platform engineers today?",
        ],
    },
];

export const KANBAN_PREVIEW_COLUMNS: KanbanPreviewColumn[] = [
    {
        id: "saved",
        label: "Saved",
        dotClass: "bg-violet-400",
        topBorderClass: "border-t-violet-500/80",
        cards: [
            {
                id: "k-1",
                title: "Senior Fullstack Engineer",
                company: "Helios Cloud",
                salary: "$110k – $135k",
                workMode: "hybrid",
                fitScore: 81,
                priority: "medium",
            },
        ],
    },
    {
        id: "applied",
        label: "Applied",
        dotClass: "bg-sky-400",
        topBorderClass: "border-t-sky-500/80",
        cards: [
            {
                id: "k-2",
                title: "Senior Backend Engineer",
                company: "Linearity Labs",
                salary: "$145k – $175k",
                workMode: "remote",
                fitScore: 92,
                priority: "high",
                followupLabel: "Follow-up overdue (1d)",
                overdue: true,
            },
        ],
    },
    {
        id: "screening",
        label: "Screening",
        dotClass: "bg-amber-400",
        topBorderClass: "border-t-amber-500/80",
        cards: [
            {
                id: "k-3",
                title: "Staff Platform Engineer",
                company: "NuvemPay",
                salary: "$120k – $140k",
                workMode: "remote",
                fitScore: 88,
                priority: "high",
                followupLabel: "Tech screen Thu 14:00",
            },
        ],
    },
    {
        id: "interviewing",
        label: "Interviewing",
        dotClass: "bg-indigo-400",
        topBorderClass: "border-t-indigo-500/80",
        cards: [
            {
                id: "k-4",
                title: "Principal Python Engineer",
                company: "Arcadia Data",
                salary: "$160k – $185k",
                workMode: "remote",
                fitScore: 90,
                priority: "high",
            },
        ],
    },
    {
        id: "offer",
        label: "Offer",
        dotClass: "bg-emerald-400",
        topBorderClass: "border-t-emerald-500/80",
        cards: [
            {
                id: "k-5",
                title: "Lead Systems Engineer",
                company: "Vanguard Mesh",
                salary: "$165k – $190k",
                workMode: "remote",
                fitScore: 94,
                priority: "high",
            },
        ],
    },
];

export const STACK_CATEGORY_FILTERS: Array<{ id: StackCategoryFilter; label: string }> = [
    { id: "all", label: "All Categories" },
    { id: "Language", label: "Languages" },
    { id: "Database", label: "Databases" },
    { id: "Broker", label: "Brokers" },
    { id: "DevOps", label: "DevOps" },
];

export const STACK_VELOCITY_DATES = ["Nov 23", "Nov 24", "Nov 25", "Nov 26", "Nov 27"];

export const STACK_VELOCITY_SERIES: StackVelocitySeriesPreview[] = [
    { tech: "Python", color: "#a78bfa", dotClass: "bg-violet-400", points: [118, 126, 134, 141, 148] },
    {
        tech: "TypeScript",
        color: "#38bdf8",
        dotClass: "bg-sky-400",
        points: [108, 114, 121, 127, 132],
    },
    {
        tech: "PostgreSQL",
        color: "#34d399",
        dotClass: "bg-emerald-400",
        points: [86, 92, 97, 104, 109],
    },
    {
        tech: "Kubernetes",
        color: "#fbbf24",
        dotClass: "bg-amber-400",
        points: [64, 70, 74, 79, 84],
    },
];

export const STACK_DEMAND_PREVIEW: StackDemandPreviewRow[] = [
    {
        rank: 1,
        tech: "Python",
        category: "Language",
        categoryClass: "bg-violet-500/15 text-violet-300 ring-violet-500/30",
        mentions: 148,
        companies: 62,
        medianUsd: "$148,000",
        medianUsdValue: 148000,
        barPct: 100,
    },
    {
        rank: 2,
        tech: "TypeScript",
        category: "Language",
        categoryClass: "bg-violet-500/15 text-violet-300 ring-violet-500/30",
        mentions: 132,
        companies: 58,
        medianUsd: "$142,000",
        medianUsdValue: 142000,
        barPct: 89,
    },
    {
        rank: 3,
        tech: "PostgreSQL",
        category: "Database",
        categoryClass: "bg-sky-500/15 text-sky-300 ring-sky-500/30",
        mentions: 109,
        companies: 51,
        medianUsd: "$150,000",
        medianUsdValue: 150000,
        barPct: 74,
    },
    {
        rank: 4,
        tech: "Kubernetes",
        category: "DevOps",
        categoryClass: "bg-emerald-500/15 text-emerald-300 ring-emerald-500/30",
        mentions: 84,
        companies: 41,
        medianUsd: "$162,000",
        medianUsdValue: 162000,
        barPct: 57,
    },
    {
        rank: 5,
        tech: "Apache Kafka",
        category: "Broker",
        categoryClass: "bg-amber-500/15 text-amber-300 ring-amber-500/30",
        mentions: 53,
        companies: 27,
        medianUsd: "$168,000",
        medianUsdValue: 168000,
        barPct: 36,
    },
    {
        rank: 6,
        tech: "Go",
        category: "Language",
        categoryClass: "bg-violet-500/15 text-violet-300 ring-violet-500/30",
        mentions: 49,
        companies: 24,
        medianUsd: "$158,000",
        medianUsdValue: 158000,
        barPct: 33,
    },
];

export const FUNNEL_STAGES_PREVIEW: FunnelStagePreview[] = [
    {
        key: "tracked",
        label: "Tracked",
        count: 18,
        conversionPct: null,
        widthPct: 100,
        barGradient: "from-zinc-500 to-zinc-400",
    },
    {
        key: "applied",
        label: "Applied",
        count: 12,
        conversionPct: "66.7%",
        widthPct: 67,
        barGradient: "from-sky-500 to-sky-400",
    },
    {
        key: "screening",
        label: "Screening",
        count: 6,
        conversionPct: "50.0%",
        widthPct: 33,
        barGradient: "from-violet-500 to-violet-400",
    },
    {
        key: "interviewing",
        label: "Interviewing",
        count: 3,
        conversionPct: "50.0%",
        widthPct: 17,
        barGradient: "from-indigo-500 to-violet-400",
    },
    {
        key: "offer",
        label: "Offer",
        count: 1,
        conversionPct: "33.3%",
        widthPct: 8,
        barGradient: "from-emerald-500 to-emerald-400",
    },
];

export const PERSONAL_WINDOW_SNAPSHOTS: Record<PersonalWindowOption, PersonalWindowSnapshot> = {
    "7d": {
        label: "Last 7d",
        tracked: 6,
        responseRate: "50.0%",
        interviewRate: "25.0%",
        offers: 0,
        rejected: 1,
        withdrawn: 0,
        funnel: [
            { ...FUNNEL_STAGES_PREVIEW[0], count: 6, widthPct: 100 },
            { ...FUNNEL_STAGES_PREVIEW[1], count: 4, conversionPct: "66.7%", widthPct: 67 },
            { ...FUNNEL_STAGES_PREVIEW[2], count: 2, conversionPct: "50.0%", widthPct: 33 },
            { ...FUNNEL_STAGES_PREVIEW[3], count: 1, conversionPct: "50.0%", widthPct: 17 },
            { ...FUNNEL_STAGES_PREVIEW[4], count: 0, conversionPct: "0%", widthPct: 0 },
        ],
    },
    "30d": {
        label: "Last 30d",
        tracked: 18,
        responseRate: "50.0%",
        interviewRate: "25.0%",
        offers: 1,
        rejected: 2,
        withdrawn: 1,
        funnel: FUNNEL_STAGES_PREVIEW,
    },
    "90d": {
        label: "Last 90d",
        tracked: 42,
        responseRate: "46.4%",
        interviewRate: "21.4%",
        offers: 2,
        rejected: 7,
        withdrawn: 3,
        funnel: [
            { ...FUNNEL_STAGES_PREVIEW[0], count: 42, widthPct: 100 },
            { ...FUNNEL_STAGES_PREVIEW[1], count: 28, conversionPct: "66.7%", widthPct: 67 },
            { ...FUNNEL_STAGES_PREVIEW[2], count: 13, conversionPct: "46.4%", widthPct: 31 },
            { ...FUNNEL_STAGES_PREVIEW[3], count: 6, conversionPct: "46.2%", widthPct: 14 },
            { ...FUNNEL_STAGES_PREVIEW[4], count: 2, conversionPct: "33.3%", widthPct: 6 },
        ],
    },
};

export const CHANNEL_PERFORMANCE_PREVIEW: ChannelPerformancePreviewRow[] = [
    { source: "Ashby", tracked: 7, applied: 5, responsePct: "60.0%", interviewPct: "40.0%" },
    { source: "Greenhouse", tracked: 6, applied: 4, responsePct: "50.0%", interviewPct: "25.0%" },
    { source: "Lever", tracked: 5, applied: 3, responsePct: "33.3%", interviewPct: "0.0%" },
];

export const SKILL_GAP_BARS_PREVIEW: SkillGapBar[] = [
    { skill: "Kubernetes", mentions: 14, sharePct: 47 },
    { skill: "gRPC", mentions: 11, sharePct: 37 },
    { skill: "Go", mentions: 9, sharePct: 30 },
    { skill: "ClickHouse", mentions: 6, sharePct: 20 },
];

export const MATCHED_STRENGTHS_PREVIEW: SkillGapBar[] = [
    { skill: "Python", mentions: 28, sharePct: 93 },
    { skill: "PostgreSQL", mentions: 24, sharePct: 80 },
    { skill: "Apache Kafka", mentions: 19, sharePct: 63 },
    { skill: "Docker", mentions: 17, sharePct: 57 },
];

export const PIPELINE_WORKERS_PREVIEW: PipelineWorkerPreview[] = [
    { name: "enrichment-worker", processed: 418, heartbeat: "12s ago" },
    { name: "matcher-worker", processed: 392, heartbeat: "9s ago" },
];

export const RESUME_PROFILES_PREVIEW: ResumeProfilePreview[] = [
    {
        id: "res-1",
        label: "Senior Backend — Python & Distributed",
        active: true,
        alertThreshold: 85,
        targetWorkModes: ["remote"],
        targetRegions: ["Global Remote", "Brazil / LATAM"],
        targetSeniority: ["Senior", "Staff"],
        targetContracts: ["B2B", "PJ"],
        extractedSkills: ["Python", "Django", "FastAPI", "Kafka", "PostgreSQL", "pgvector", "GCP"],
        updatedAt: "2h ago",
    },
    {
        id: "res-2",
        label: "Fullstack Engineer — Python + React",
        active: true,
        alertThreshold: 80,
        targetWorkModes: ["remote", "hybrid"],
        targetRegions: ["Brazil / LATAM"],
        targetSeniority: ["Senior"],
        targetContracts: ["PJ", "CLT"],
        extractedSkills: ["TypeScript", "React", "Python", "PostgreSQL", "Docker", "Tailwind CSS"],
        updatedAt: "3d ago",
    },
];

const NEXT_PRIORITY: Record<KanbanPriority, KanbanPriority> = {
    low: "medium",
    medium: "high",
    high: "low",
};

export function cyclePreviewPriority(current: KanbanPriority): KanbanPriority {
    return NEXT_PRIORITY[current];
}

export function getNextPreviewTabId(currentTab: PreviewTabId, key: string): PreviewTabId | null {
    const index = PREVIEW_TABS.findIndex((tab) => tab.id === currentTab);
    if (index === -1) {
        return null;
    }
    if (key === "ArrowRight") {
        return PREVIEW_TABS[(index + 1) % PREVIEW_TABS.length].id;
    }
    if (key === "ArrowLeft") {
        return PREVIEW_TABS[(index - 1 + PREVIEW_TABS.length) % PREVIEW_TABS.length].id;
    }
    if (key === "Home") {
        return PREVIEW_TABS[0].id;
    }
    if (key === "End") {
        return PREVIEW_TABS[PREVIEW_TABS.length - 1].id;
    }
    return null;
}

export function filterRadarPreviewRoles(
    roles: RadarPreviewRole[],
    filter: RadarPreviewFilter,
    hiddenIds: ReadonlySet<string>,
): RadarPreviewRole[] {
    return roles.filter((role) => {
        if (hiddenIds.has(role.id)) {
            return false;
        }
        if (filter === "remote") {
            return role.workMode === "remote";
        }
        if (filter === "high_fit") {
            return role.fitScore >= 85;
        }
        if (filter === "unapplied") {
            return !role.tracked;
        }
        return true;
    });
}

export function getCopilotPreviewDraft(kind: CopilotArtifactKind): CopilotDraftPreview {
    return (
        COPILOT_DRAFTS_PREVIEW.find((draft) => draft.kind === kind) ?? COPILOT_DRAFTS_PREVIEW[0]
    );
}
