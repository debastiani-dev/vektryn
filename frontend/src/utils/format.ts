import type { ContractType, SeniorityLevel, TechCategory } from "../types/models";

const CONTRACT_LABELS: Record<ContractType, string> = {
    clt: "CLT",
    pj: "PJ",
    b2b_contractor: "B2B Contractor",
    w2: "W2",
    c2c: "C2C",
    eor: "EOR",
    unknown: "Contract Unspecified",
};

const SENIORITY_LABELS: Record<SeniorityLevel, string> = {
    intern: "Intern",
    junior: "Junior",
    mid: "Mid-Level",
    senior: "Senior",
    staff: "Staff",
    principal: "Principal",
    lead: "Lead",
    manager: "Manager",
    unknown: "",
};

const CATEGORY_LABELS: Record<TechCategory, string> = {
    language: "Language",
    framework: "Framework",
    database: "Database",
    broker: "Broker",
    cloud: "Cloud",
    devops: "DevOps",
    ai_ml: "AI / ML",
    other: "Other",
};

const CATEGORY_BADGE_STYLES: Record<TechCategory, string> = {
    language: "bg-sky-500/12 text-sky-300 ring-1 ring-sky-500/25",
    framework: "bg-violet-500/12 text-violet-300 ring-1 ring-violet-500/25",
    database: "bg-emerald-500/12 text-emerald-300 ring-1 ring-emerald-500/25",
    broker: "bg-amber-500/12 text-amber-300 ring-1 ring-amber-500/25",
    cloud: "bg-cyan-500/12 text-cyan-300 ring-1 ring-cyan-500/25",
    devops: "bg-orange-500/12 text-orange-300 ring-1 ring-orange-500/25",
    ai_ml: "bg-fuchsia-500/12 text-fuchsia-300 ring-1 ring-fuchsia-500/25",
    other: "bg-zinc-800 text-zinc-300 ring-1 ring-zinc-700/70",
};

const CURRENCY_SYMBOLS: Record<string, string> = {
    USD: "$",
    EUR: "€",
    GBP: "£",
    BRL: "R$",
    CAD: "C$",
    AUD: "A$",
};

export const DEFAULT_MIN_ALERT_SCORE = 70;

export function isAlertMatch(
    score: number | null | undefined,
    minAlertScore = DEFAULT_MIN_ALERT_SCORE,
): boolean {
    return score !== null && score !== undefined && score >= minAlertScore;
}

export function scoreBadgeStyle(
    score: number | null | undefined,
    minAlertScore = DEFAULT_MIN_ALERT_SCORE,
): string {
    if (score === null || score === undefined) {
        return "bg-zinc-800/80 text-zinc-400 ring-1 ring-zinc-700/60";
    }
    if (score >= minAlertScore) {
        return "bg-violet-500/15 text-violet-300 ring-1 ring-violet-500/35";
    }
    if (score >= 55) {
        return "bg-emerald-500/15 text-emerald-300 ring-1 ring-emerald-500/35";
    }
    return "bg-amber-500/12 text-amber-300 ring-1 ring-amber-500/30";
}

export function scoreVisualTheme(
    score: number | null | undefined,
    minAlertScore = DEFAULT_MIN_ALERT_SCORE,
): {
    tile: string;
    value: string;
    bar: string;
    caption: "AI FIT" | "UNSCORED";
} {
    if (score === null || score === undefined) {
        return {
            tile: "border-zinc-800 bg-zinc-900/60 text-zinc-400",
            value: "text-zinc-400",
            bar: "bg-zinc-700",
            caption: "UNSCORED",
        };
    }
    if (score >= minAlertScore) {
        return {
            tile: "border-violet-500/35 bg-violet-950/25",
            value: "text-violet-300",
            bar: "bg-violet-400",
            caption: "AI FIT",
        };
    }
    if (score >= 55) {
        return {
            tile: "border-emerald-500/30 bg-emerald-950/20",
            value: "text-emerald-300",
            bar: "bg-emerald-400",
            caption: "AI FIT",
        };
    }
    return {
        tile: "border-amber-500/25 bg-amber-950/15",
        value: "text-amber-300",
        bar: "bg-amber-400/80",
        caption: "AI FIT",
    };
}

export function formatScoreLabel(score: number | null | undefined): string {
    return score !== null && score !== undefined ? `${Math.round(score)}% AI Fit` : "Not Scored";
}

export function formatVectorSimilarity(cosineSimilarity: number): string {
    const pct = Math.max(0, Math.min(100, Math.round(cosineSimilarity * 100)));
    return `${pct}% vector`;
}

export function formatContractType(contract: string): string {
    if (contract in CONTRACT_LABELS) {
        return CONTRACT_LABELS[contract as ContractType];
    }
    return contract
        .replace(/_/g, " ")
        .replace(/\b\w/g, (ch) => ch.toUpperCase());
}

export function formatSeniority(seniority: string): string {
    if (seniority in SENIORITY_LABELS) {
        return SENIORITY_LABELS[seniority as SeniorityLevel];
    }
    return seniority
        .replace(/_/g, " ")
        .replace(/\b\w/g, (ch) => ch.toUpperCase());
}

export function formatAtsSource(source: string): string {
    if (!source) return "";
    return source
        .replace(/[_-]+/g, " ")
        .replace(/\b\w/g, (ch) => ch.toUpperCase());
}

export function formatCategoryLabel(category: string): string {
    if (category in CATEGORY_LABELS) {
        return CATEGORY_LABELS[category as TechCategory];
    }
    return category
        .replace(/_/g, " ")
        .replace(/\b\w/g, (ch) => ch.toUpperCase());
}

export function categoryBadgeStyle(category: string): string {
    if (category in CATEGORY_BADGE_STYLES) {
        return CATEGORY_BADGE_STYLES[category as TechCategory];
    }
    return CATEGORY_BADGE_STYLES.other;
}

function formatCompactMoney(amount: number): string {
    if (amount >= 1000) {
        const k = amount / 1000;
        return Number.isInteger(k) ? `${k}k` : `${k.toFixed(1).replace(/\.0$/, "")}k`;
    }
    return String(Math.round(amount));
}

function formatSalaryPeriod(period: string | null): string {
    if (!period) return "";
    const normalized = period.toLowerCase();
    if (normalized.includes("year") || normalized === "annual" || normalized === "yr") return "/yr";
    if (normalized.includes("month") || normalized === "mo") return "/mo";
    if (normalized.includes("hour") || normalized === "hr") return "/hr";
    return `/${period}`;
}

export function formatSalaryRange(
    minRaw: string | null,
    maxRaw: string | null,
    currency: string | null,
    period: string | null,
): string | null {
    const min = minRaw ? Number(minRaw) : Number.NaN;
    const max = maxRaw ? Number(maxRaw) : Number.NaN;
    const hasMin = Number.isFinite(min) && min > 0;
    const hasMax = Number.isFinite(max) && max > 0;

    if (!hasMin && !hasMax) return null;

    const code = (currency || "USD").toUpperCase();
    const symbol = CURRENCY_SYMBOLS[code] ?? `${code} `;
    const suffix = formatSalaryPeriod(period);

    if (hasMin && hasMax && Math.round(min) !== Math.round(max)) {
        return `${symbol}${formatCompactMoney(min)}–${symbol}${formatCompactMoney(max)}${suffix}`;
    }
    const single = hasMin ? min : max;
    return `${symbol}${formatCompactMoney(single)}${suffix}`;
}

export function formatUsdAnnual(raw: string | null): string {
    if (!raw) return "—";
    const value = Number(raw);
    if (!Number.isFinite(value) || value <= 0) return "—";
    return `$${Math.round(value / 1000)}k/yr`;
}

export function formatRelativeTime(iso: string | null): string | null {
    if (!iso) return null;
    const timestamp = Date.parse(iso);
    if (Number.isNaN(timestamp)) return null;

    const diffMs = Date.now() - timestamp;
    if (diffMs < 0) return "Upcoming";

    const minutes = Math.floor(diffMs / 60_000);
    if (minutes < 1) return "Just now";
    if (minutes < 60) return `${minutes}m ago`;

    const hours = Math.floor(minutes / 60);
    if (hours < 24) return `${hours}h ago`;

    const days = Math.floor(hours / 24);
    if (days < 14) return `${days}d ago`;

    const weeks = Math.floor(days / 7);
    if (weeks < 8) return `${weeks}w ago`;

    return new Date(timestamp).toLocaleDateString("en-US", {
        month: "short",
        day: "numeric",
    });
}

const REGION_LABELS: Record<string, string> = {
    global: "Global",
    worldwide: "Worldwide",
    latam: "LATAM",
    brazil: "Brazil",
    us: "US",
    usa: "US",
    eu: "EU",
    emea: "EMEA",
    apac: "APAC",
    uk: "UK",
    canada: "Canada",
    americas: "Americas",
    north_america: "North America",
    south_america: "South America",
};

export function formatRegionEligibility(region: string): string {
    const key = region.trim().toLowerCase();
    if (key in REGION_LABELS) {
        return REGION_LABELS[key];
    }
    return region
        .replace(/[_-]+/g, " ")
        .replace(/\b\w/g, (ch) => ch.toUpperCase());
}

export function formatExactDate(iso: string | null): string | null {
    if (!iso) return null;
    const timestamp = Date.parse(iso);
    if (Number.isNaN(timestamp)) return null;
    return new Date(timestamp).toLocaleDateString("en-US", {
        year: "numeric",
        month: "short",
        day: "numeric",
    });
}

export function isMailtoUrl(url: string | null | undefined): boolean {
    return typeof url === "string" && url.trim().toLowerCase().startsWith("mailto:");
}

export function extractMailtoAddress(url: string): string {
    return url.trim().slice(7).split("?")[0].trim();
}

export function formatApplyLinkLabel(
    url: string | null | undefined,
    defaultLabel = "Apply",
): string {
    return isMailtoUrl(url) ? "Apply via Email" : defaultLabel;
}

export function formatApplyLinkTooltip(
    url: string | null | undefined,
    defaultTooltip = "Open original job posting in a new tab",
): string {
    if (isMailtoUrl(url) && url) {
        const email = extractMailtoAddress(url);
        return email ? `Send application email to ${email}` : "Apply via email";
    }
    return defaultTooltip;
}
