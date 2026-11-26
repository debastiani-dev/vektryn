export type PreviewTabId = "radar" | "copilot" | "tracker" | "analytics";
export type RadarPreviewFilter = "all" | "high_fit" | "global" | "unapplied";
export type CopilotPreviewMode = "gap" | "copilot";
export type CopilotArtifactKind = "tailored_bullets" | "cover_letter" | "recruiter_outreach";
export type KanbanPriority = "low" | "medium" | "high";

export interface PreviewTabMeta {
    id: PreviewTabId;
    label: string;
    shortLabel: string;
}

export interface RadarPreviewRole {
    id: string;
    title: string;
    company: string;
    location: string;
    source: string;
    seniority: string;
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
}

export interface PipelineWorkerPreview {
    name: string;
    processed: number;
    heartbeat: string;
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
    { id: "radar", label: "Job Radar", shortLabel: "Radar" },
    { id: "copilot", label: "Gap & Copilot", shortLabel: "Copilot" },
    { id: "tracker", label: "Pipeline Tracker", shortLabel: "Tracker" },
    { id: "analytics", label: "Analytics & Ops", shortLabel: "Analytics" },
];

export const RADAR_PREVIEW_FILTERS: Array<{ id: RadarPreviewFilter; label: string }> = [
    { id: "all", label: "All Roles" },
    { id: "high_fit", label: "High Fit >= 85" },
    { id: "global", label: "Global Remote" },
    { id: "unapplied", label: "Unapplied Only" },
];

export const RADAR_PREVIEW_ROLES: RadarPreviewRole[] = [
    {
        id: "role-1",
        title: "Senior Backend Engineer — Distributed Systems",
        company: "Linearity Labs",
        location: "Remote · Global",
        source: "Ashby",
        seniority: "Senior",
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
        seniority: "Staff",
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
        location: "Remote · Americas / EU",
        source: "Lever",
        seniority: "Senior",
        postedAge: "1d ago",
        region: "Global Remote",
        contract: "B2B Contractor",
        salary: "$130k – $155k",
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
    source: "Ashby",
    contract: "B2B Contractor",
    salary: "$145k – $175k",
    fitScore: 92,
    vectorPercent: 86,
    scoringModel: "gemini-2.5-flash",
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
        label: "Recruiter Outreach",
        tone: "Concise",
        heading: "Direct Hiring Manager / Recruiter Note",
        lines: [
            "Hi [Name] — saw your Senior Backend Engineer opening at Linearity Labs. My core stack matches closely (Python, Django, Kafka event pipelines, PostgreSQL, GCP/Terraform).",
            "Happy to share a brief system design overview and my resume if you're still reviewing candidates this week.",
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
                salary: "$130k – $155k",
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
                fitScore: 94,
                priority: "high",
            },
        ],
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

export const SKILL_GAP_BARS_PREVIEW: SkillGapBar[] = [
    { skill: "Kubernetes", mentions: 14 },
    { skill: "gRPC", mentions: 11 },
    { skill: "Go", mentions: 9 },
    { skill: "ClickHouse", mentions: 6 },
];

export const PIPELINE_WORKERS_PREVIEW: PipelineWorkerPreview[] = [
    { name: "enrichment-worker", processed: 418, heartbeat: "12s ago" },
    { name: "matcher-worker", processed: 392, heartbeat: "9s ago" },
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
        if (filter === "high_fit") {
            return role.fitScore >= 85;
        }
        if (filter === "global") {
            return role.region === "Global Remote";
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
