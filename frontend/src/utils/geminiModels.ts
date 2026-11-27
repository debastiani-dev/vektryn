import { ApiError } from "../api/client";
import type { PreferredGeminiModel } from "../types/models";

export const GOOGLE_AI_STUDIO_KEY_URL = "https://aistudio.google.com/apikey";

export interface GeminiModelOption {
    value: PreferredGeminiModel;
    label: string;
    tier: "auto" | "free" | "paid";
    tierBadge: string;
    description: string;
}

export const GEMINI_MODEL_OPTIONS: GeminiModelOption[] = [
    {
        value: "auto",
        label: "Auto (Recommended)",
        tier: "auto",
        tierBadge: "Smart Free Ladder",
        description:
            "Uses Gemini 4 Hydrogen for Copilot drafts and Gemini 3.5 Flash-Lite for high-volume matching, with automatic fallback.",
    },
    {
        value: "gemini-4-carbon",
        label: "Gemini 4 Carbon",
        tier: "paid",
        tierBadge: "Paid",
        description: "Flagship reasoning model (requires paid Google AI Studio billing).",
    },
    {
        value: "gemini-4-neon",
        label: "Gemini 4 Neon",
        tier: "paid",
        tierBadge: "Paid",
        description: "High-capability balanced model (requires paid Google AI Studio billing).",
    },
    {
        value: "gemini-4-argon",
        label: "Gemini 4 Argon",
        tier: "paid",
        tierBadge: "Paid",
        description: "Fast premium tier model (requires paid Google AI Studio billing).",
    },
    {
        value: "gemini-4-hydrogen",
        label: "Gemini 4 Hydrogen",
        tier: "free",
        tierBadge: "Free",
        description: "Best free-tier quality for AI Copilot drafts and gap evaluations.",
    },
    {
        value: "gemini-3.8-flash",
        label: "Gemini 3.8 Flash",
        tier: "free",
        tierBadge: "Free",
        description: "Fast free-tier model with generous quota for scoring and drafting.",
    },
    {
        value: "gemini-3.5-flash-lite",
        label: "Gemini 3.5 Flash-Lite",
        tier: "free",
        tierBadge: "Free",
        description: "Ultra-fast, lowest-quota model ideal for large job scoring batches.",
    },
];

export function formatGeminiKeyBadge(hasKey: boolean, last4?: string): string {
    if (!hasKey) {
        return "Not configured";
    }
    const suffix = (last4 ?? "").trim();
    return suffix ? `Configured ••••${suffix}` : "Configured";
}

export function findGeminiModelOption(model: PreferredGeminiModel): GeminiModelOption {
    return GEMINI_MODEL_OPTIONS.find((opt) => opt.value === model) ?? GEMINI_MODEL_OPTIONS[0];
}

export interface CopilotErrorInfo {
    message: string;
    showSettingsAction: boolean;
}

function classifyByokCopilotError(err: ApiError): CopilotErrorInfo | null {
    if (err.code === "byok_missing") {
        return {
            message:
                err.detail ||
                "Add your Google AI Studio Gemini API key in Account Settings to generate AI Copilot drafts.",
            showSettingsAction: true,
        };
    }
    if (err.code === "byok_invalid") {
        return {
            message:
                err.detail ||
                "Your Gemini API key was rejected by Google AI Studio. Update it in Account Settings.",
            showSettingsAction: true,
        };
    }
    if (err.code === "byok_quota_exhausted") {
        const fallbackMessage = err.paymentRequired
            ? "Your Google AI Studio prepayment credits are depleted. Top up credits or update your key in Account Settings."
            : "All eligible Gemini models hit quota limits. Wait for cooldowns to clear or adjust your model preference in Account Settings.";
        return {
            message: err.detail || fallbackMessage,
            showSettingsAction: true,
        };
    }
    return null;
}

export function classifyCopilotError(err: unknown): CopilotErrorInfo {
    if (!(err instanceof ApiError)) {
        return {
            message: "Failed to communicate with AI Copilot. Please try again.",
            showSettingsAction: false,
        };
    }
    const byokError = classifyByokCopilotError(err);
    if (byokError) {
        return byokError;
    }
    if (err.status === 429) {
        const message = err.retryAfterSeconds
            ? `Rate limit reached. Please wait ${err.retryAfterSeconds}s before generating another draft.`
            : err.detail || "Rate limit reached. Please wait a moment before trying again.";
        return { message, showSettingsAction: false };
    }
    if (err.status === 503) {
        return {
            message:
                err.detail ||
                "AI Copilot is temporarily unavailable. Please try again in a moment.",
            showSettingsAction: false,
        };
    }
    return {
        message: err.detail || "Failed to communicate with AI Copilot. Please try again.",
        showSettingsAction: false,
    };
}
