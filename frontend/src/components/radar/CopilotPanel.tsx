import {
    AlertTriangle,
    Check,
    Copy,
    FileText,
    HelpCircle,
    KeyRound,
    ListChecks,
    Loader2,
    MessageSquareText,
    RefreshCw,
    Send,
    Sparkles,
    UserCog,
} from "lucide-react";
import { useEffect, useState, type ComponentType, type SyntheticEvent } from "react";
import { vektrynApi } from "../../api/client";
import type {
    CopilotTone,
    MatchArtifact,
    MatchArtifactKind,
    MatchScore,
} from "../../types/models";
import { formatRelativeTime } from "../../utils/format";
import { classifyCopilotError, type CopilotErrorInfo } from "../../utils/geminiModels";
import { MarkdownContent } from "../ui/MarkdownContent";
import { Tooltip } from "../ui/Tooltip";

interface CopilotPanelProps {
    match: MatchScore;
    defaultTone?: CopilotTone;
    hasGeminiApiKey?: boolean;
    onOpenAccountSettings?: () => void;
}

interface ArtifactKindOption {
    kind: MatchArtifactKind;
    label: string;
    shortLabel: string;
    description: string;
    icon: ComponentType<{ className?: string }>;
}

const ARTIFACT_KINDS: ArtifactKindOption[] = [
    {
        kind: "tailored_bullets",
        label: "Tailored Bullets",
        shortLabel: "Bullets",
        description:
            "Generate 4–6 resume bullets tailored to this role's priorities using only your verified background.",
        icon: ListChecks,
    },
    {
        kind: "cover_letter",
        label: "Cover Letter",
        shortLabel: "Cover Letter",
        description:
            "Draft a focused 3–4 paragraph cover letter linking your experience to the posting.",
        icon: FileText,
    },
    {
        kind: "recruiter_outreach",
        label: "Recruiter Outreach",
        shortLabel: "Outreach",
        description:
            "Create a concise LinkedIn DM and direct hiring-manager email ready to send.",
        icon: Send,
    },
    {
        kind: "interview_questions",
        label: "Interview Prep",
        shortLabel: "Interview",
        description:
            "Practice 5–6 questions the interviewer is likely to ask, with grounded answer angles.",
        icon: MessageSquareText,
    },
    {
        kind: "questions_to_ask",
        label: "Questions to Ask",
        shortLabel: "Ask Them",
        description:
            "Generate 5–6 high-signal, role-specific questions to ask the interviewer and what to listen for.",
        icon: HelpCircle,
    },
];

const TONE_OPTIONS: { value: CopilotTone; label: string }[] = [
    { value: "balanced", label: "Balanced" },
    { value: "concise", label: "Concise" },
    { value: "executive", label: "Executive" },
    { value: "technical", label: "Technical" },
    { value: "conversational", label: "Conversational" },
];

const MAX_GUIDANCE_LENGTH = 300;

function getKindDotColor(artifact: MatchArtifact | undefined): string | null {
    if (!artifact) return null;
    return artifact.is_stale ? "bg-amber-400" : "bg-emerald-400";
}

function getGenerateButtonLabel(
    generating: boolean,
    hasArtifact: boolean,
    isStale: boolean,
    kindLabel: string,
): string {
    if (generating) {
        return hasArtifact ? "Regenerating..." : "Generating...";
    }
    if (isStale) {
        return "Regenerate with Updated Resume";
    }
    if (hasArtifact) {
        return "Regenerate";
    }
    return `Generate ${kindLabel}`;
}

function renderActionIcon(generating: boolean, hasArtifact: boolean) {
    if (generating) {
        return <Loader2 className="h-3.5 w-3.5 animate-spin" />;
    }
    if (hasArtifact) {
        return <RefreshCw className="h-3.5 w-3.5" />;
    }
    return <Sparkles className="h-3.5 w-3.5" />;
}

export function CopilotPanel({
    match,
    defaultTone = "balanced",
    hasGeminiApiKey = true,
    onOpenAccountSettings,
}: Readonly<CopilotPanelProps>) {
    const [selectedKind, setSelectedKind] = useState<MatchArtifactKind>("tailored_bullets");
    const [artifactsByKind, setArtifactsByKind] = useState<
        Partial<Record<MatchArtifactKind, MatchArtifact>>
    >({});
    const [lastSourceByKind, setLastSourceByKind] = useState<
        Partial<Record<MatchArtifactKind, "cached" | "fresh">>
    >({});
    const [loadingList, setLoadingList] = useState(true);
    const [generatingKind, setGeneratingKind] = useState<MatchArtifactKind | null>(null);
    const [tone, setTone] = useState<CopilotTone>(defaultTone);
    const [guidance, setGuidance] = useState("");
    const [errorInfo, setErrorInfo] = useState<CopilotErrorInfo | null>(null);
    const [copiedKind, setCopiedKind] = useState<MatchArtifactKind | null>(null);

    useEffect(() => {
        let active = true;
        vektrynApi
            .listMatchArtifacts(match.uuid)
            .then((res) => {
                if (!active) return;
                const mapped: Partial<Record<MatchArtifactKind, MatchArtifact>> = {};
                const sources: Partial<Record<MatchArtifactKind, "cached" | "fresh">> = {};
                for (const item of res.results) {
                    if (!mapped[item.kind]) {
                        mapped[item.kind] = item;
                        sources[item.kind] = "cached";
                    }
                }
                setArtifactsByKind(mapped);
                setLastSourceByKind(sources);
                setErrorInfo(null);
            })
            .catch((err) => {
                if (!active) return;
                setErrorInfo(classifyCopilotError(err));
            })
            .finally(() => {
                if (active) {
                    setLoadingList(false);
                }
            });

        return () => {
            active = false;
        };
    }, [match.uuid]);

    const currentKindMeta =
        ARTIFACT_KINDS.find((item) => item.kind === selectedKind) ?? ARTIFACT_KINDS[0];
    const currentArtifact = artifactsByKind[selectedKind];
    const currentSource = lastSourceByKind[selectedKind] ?? "cached";
    const isGeneratingCurrent = generatingKind === selectedKind;
    const isGeneratingAny = generatingKind !== null;

    async function handleGenerate(regenerate: boolean) {
        setErrorInfo(null);
        setGeneratingKind(selectedKind);
        try {
            const cleanGuidance = guidance.trim();
            const response = await vektrynApi.generateMatchArtifact(match.uuid, {
                kind: selectedKind,
                regenerate,
                tone,
                guidance: cleanGuidance || undefined,
            });
            const { cached, ...artifact } = response;
            setArtifactsByKind((prev) => ({
                ...prev,
                [selectedKind]: artifact,
            }));
            setLastSourceByKind((prev) => ({
                ...prev,
                [selectedKind]: cached ? "cached" : "fresh",
            }));
        } catch (err) {
            setErrorInfo(classifyCopilotError(err));
        } finally {
            setGeneratingKind(null);
        }
    }

    function handleFormSubmit(event: SyntheticEvent<HTMLFormElement>) {
        event.preventDefault();
        if (isGeneratingAny) return;
        const shouldRegenerate = Boolean(currentArtifact);
        void handleGenerate(shouldRegenerate);
    }

    async function handleCopy() {
        if (!currentArtifact) return;
        try {
            await navigator.clipboard.writeText(currentArtifact.content_markdown);
            setCopiedKind(selectedKind);
            window.setTimeout(() => {
                setCopiedKind((prev) => (prev === selectedKind ? null : prev));
            }, 2000);
        } catch {
            setErrorInfo({
                message: "Could not copy to clipboard. Please select and copy manually.",
                showSettingsAction: false,
            });
        }
    }

    const updatedLabel = currentArtifact
        ? formatRelativeTime(currentArtifact.modified_at)
        : null;
    const actionLabel = getGenerateButtonLabel(
        isGeneratingCurrent,
        Boolean(currentArtifact),
        Boolean(currentArtifact?.is_stale),
        currentKindMeta.label,
    );

    return (
        <div className="space-y-5">
            {!hasGeminiApiKey && (
                <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-amber-500/30 bg-amber-950/20 px-4 py-3 text-xs text-amber-200">
                    <div className="flex items-start gap-2.5">
                        <KeyRound className="mt-0.5 h-4 w-4 shrink-0 text-amber-400" />
                        <span>
                            Add your Google AI Studio Gemini API key to generate new AI Copilot
                            drafts. Previously cached drafts remain viewable below.
                        </span>
                    </div>
                    {onOpenAccountSettings && (
                        <button
                            type="button"
                            onClick={onOpenAccountSettings}
                            className="inline-flex shrink-0 items-center gap-1.5 rounded-lg bg-amber-500/20 px-3 py-1.5 text-xs font-semibold text-amber-100 ring-1 ring-amber-500/40 transition hover:bg-amber-500/30"
                        >
                            <UserCog className="h-3.5 w-3.5" />
                            <span>Open Account Settings</span>
                        </button>
                    )}
                </div>
            )}

            <div className="grid grid-cols-2 gap-2 sm:grid-cols-5">
                {ARTIFACT_KINDS.map((item) => {
                    const Icon = item.icon;
                    const isActive = item.kind === selectedKind;
                    const dotColor = getKindDotColor(artifactsByKind[item.kind]);
                    return (
                        <button
                            key={item.kind}
                            type="button"
                            onClick={() => {
                                setSelectedKind(item.kind);
                                setErrorInfo(null);
                            }}
                            className={`flex items-center justify-between gap-2 rounded-xl border px-3 py-2.5 text-left text-xs font-medium transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-500/70 ${
                                isActive
                                    ? "border-violet-500/50 bg-violet-500/15 text-violet-100 shadow-xs"
                                    : "border-zinc-800 bg-zinc-900/60 text-zinc-400 hover:border-zinc-700 hover:text-zinc-200"
                            }`}
                        >
                            <span className="flex min-w-0 items-center gap-2">
                                <Icon className="h-3.5 w-3.5 shrink-0 text-violet-400" />
                                <span className="truncate">{item.shortLabel}</span>
                            </span>
                            {dotColor && (
                                <span
                                    className={`h-2 w-2 shrink-0 rounded-full ${dotColor}`}
                                    aria-label={
                                        artifactsByKind[item.kind]?.is_stale
                                            ? "Cached draft is stale"
                                            : "Cached draft available"
                                    }
                                />
                            )}
                        </button>
                    );
                })}
            </div>

            <form
                onSubmit={handleFormSubmit}
                className="space-y-3 rounded-2xl border border-zinc-800/90 bg-zinc-900/45 p-4 ring-1 ring-inset ring-white/[0.03]"
            >
                <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="flex items-center gap-2">
                        <label
                            htmlFor="copilot-tone-select"
                            className="text-xs font-medium text-zinc-400"
                        >
                            Tone
                        </label>
                        <select
                            id="copilot-tone-select"
                            value={tone}
                            onChange={(e) => setTone(e.target.value as CopilotTone)}
                            disabled={isGeneratingAny}
                            className="rounded-lg border border-zinc-700/80 bg-zinc-950 px-2.5 py-1.5 text-xs text-zinc-200 focus:border-violet-500 focus:outline-none disabled:opacity-50"
                        >
                            {TONE_OPTIONS.map((opt) => (
                                <option key={opt.value} value={opt.value}>
                                    {opt.label}
                                </option>
                            ))}
                        </select>
                    </div>

                    <button
                        type="submit"
                        disabled={isGeneratingAny || loadingList}
                        className="inline-flex items-center gap-2 rounded-xl bg-violet-600 px-4 py-2 text-xs font-semibold text-white shadow-sm shadow-violet-600/20 transition hover:bg-violet-500 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-500/70 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                        {renderActionIcon(isGeneratingCurrent, Boolean(currentArtifact))}
                        {actionLabel}
                    </button>
                </div>

                <div>
                    <div className="mb-1 flex items-center justify-between">
                        <label
                            htmlFor="copilot-guidance-input"
                            className="text-xs text-zinc-400"
                        >
                            Optional focus or instructions
                        </label>
                        {guidance.length > 0 && (
                            <span className="font-mono text-[11px] text-zinc-500">
                                {guidance.length}/{MAX_GUIDANCE_LENGTH}
                            </span>
                        )}
                    </div>
                    <input
                        id="copilot-guidance-input"
                        type="text"
                        maxLength={MAX_GUIDANCE_LENGTH}
                        value={guidance}
                        onChange={(e) => setGuidance(e.target.value)}
                        disabled={isGeneratingAny}
                        placeholder="e.g. Emphasize distributed systems leadership or keep outreach under 3 sentences"
                        className="w-full rounded-xl border border-zinc-800 bg-zinc-950/90 px-3 py-2 text-xs text-zinc-200 placeholder:text-zinc-500 focus:border-violet-500/70 focus:outline-none disabled:opacity-50"
                    />
                </div>
            </form>

            {errorInfo && (
                <div
                    role="alert"
                    className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-rose-500/30 bg-rose-950/30 px-4 py-3 text-xs leading-relaxed text-rose-200"
                >
                    <div className="flex items-start gap-2.5">
                        <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-rose-400" />
                        <span>{errorInfo.message}</span>
                    </div>
                    {errorInfo.showSettingsAction && onOpenAccountSettings && (
                        <button
                            type="button"
                            onClick={onOpenAccountSettings}
                            className="inline-flex shrink-0 items-center gap-1.5 rounded-lg bg-rose-500/20 px-3 py-1.5 text-xs font-semibold text-rose-100 ring-1 ring-rose-500/40 transition hover:bg-rose-500/30"
                        >
                            <UserCog className="h-3.5 w-3.5" />
                            <span>Open Account Settings</span>
                        </button>
                    )}
                </div>
            )}

            {loadingList && (
                <div className="flex items-center justify-center gap-2 rounded-2xl border border-zinc-800/80 bg-zinc-900/40 py-14 text-xs text-zinc-400">
                    <Loader2 className="h-4 w-4 animate-spin text-violet-400" />
                    Loading cached drafts...
                </div>
            )}

            {!loadingList && currentArtifact && (
                <section className="space-y-4 rounded-2xl border border-zinc-800/90 bg-zinc-900/55 p-5 ring-1 ring-inset ring-white/[0.03] sm:p-6">
                    {currentArtifact.is_stale && (
                        <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-amber-500/30 bg-amber-950/30 px-3.5 py-2.5 text-xs text-amber-200">
                            <div className="flex items-center gap-2">
                                <AlertTriangle className="h-4 w-4 shrink-0 text-amber-400" />
                                <span>
                                    Your resume changed since this draft was generated.
                                </span>
                            </div>
                            <button
                                type="button"
                                disabled={isGeneratingAny}
                                onClick={() => void handleGenerate(true)}
                                className="inline-flex items-center gap-1.5 rounded-lg border border-amber-500/40 bg-amber-500/15 px-2.5 py-1 text-xs font-semibold text-amber-200 transition hover:bg-amber-500/25 disabled:opacity-50"
                            >
                                <RefreshCw className="h-3 w-3" />
                                Refresh now
                            </button>
                        </div>
                    )}

                    <div className="flex flex-wrap items-center justify-between gap-2 border-b border-zinc-800/80 pb-3">
                        <div className="flex flex-wrap items-center gap-2 text-xs">
                            <span className="font-semibold text-zinc-100">
                                {currentKindMeta.label}
                            </span>
                            {currentArtifact.model_name && (
                                <span className="rounded-md bg-zinc-800 px-2 py-0.5 font-mono text-[11px] text-zinc-300">
                                    {currentArtifact.model_name}
                                </span>
                            )}
                            <span
                                className={`rounded-md px-2 py-0.5 text-[11px] font-medium ${
                                    currentSource === "fresh"
                                        ? "bg-emerald-500/15 text-emerald-300"
                                        : "bg-zinc-800/80 text-zinc-400"
                                }`}
                            >
                                {currentSource === "fresh" ? "Just generated" : "Cached"}
                            </span>
                            {updatedLabel && (
                                <span className="text-[11px] text-zinc-500">
                                    Updated {updatedLabel}
                                </span>
                            )}
                        </div>

                        <Tooltip content="Copy Markdown to clipboard">
                            <button
                                type="button"
                                onClick={() => void handleCopy()}
                                className="inline-flex items-center gap-1.5 rounded-lg border border-zinc-700 bg-zinc-800 px-3 py-1.5 text-xs font-medium text-zinc-200 transition hover:bg-zinc-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-500/70"
                            >
                                {copiedKind === selectedKind ? (
                                    <>
                                        <Check className="h-3.5 w-3.5 text-emerald-400" />
                                        Copied
                                    </>
                                ) : (
                                    <>
                                        <Copy className="h-3.5 w-3.5 text-zinc-400" />
                                        Copy
                                    </>
                                )}
                            </button>
                        </Tooltip>
                    </div>

                    <MarkdownContent markdown={currentArtifact.content_markdown} />
                </section>
            )}

            {!loadingList && !currentArtifact && (
                <section className="flex flex-col items-center justify-center rounded-2xl border border-dashed border-zinc-800 bg-zinc-900/35 px-6 py-12 text-center">
                    <div className="mb-3 flex h-10 w-10 items-center justify-center rounded-xl bg-violet-500/15 text-violet-300 ring-1 ring-violet-500/30">
                        <currentKindMeta.icon className="h-5 w-5" />
                    </div>
                    <h3 className="text-sm font-semibold text-zinc-100">
                        {currentKindMeta.label}
                    </h3>
                    <p className="mt-1.5 max-w-md text-xs leading-relaxed text-zinc-400">
                        {currentKindMeta.description}
                    </p>
                    <p className="mt-2 text-[11px] text-zinc-500">
                        Generated strictly on demand and cached for your active resume.
                    </p>
                    <button
                        type="button"
                        disabled={isGeneratingAny}
                        onClick={() => void handleGenerate(false)}
                        className="mt-5 inline-flex items-center gap-2 rounded-xl bg-violet-600 px-4 py-2 text-xs font-semibold text-white shadow-sm shadow-violet-600/20 transition hover:bg-violet-500 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-500/70 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                        {isGeneratingCurrent ? (
                            <Loader2 className="h-3.5 w-3.5 animate-spin" />
                        ) : (
                            <Sparkles className="h-3.5 w-3.5" />
                        )}
                        {isGeneratingCurrent
                            ? "Generating..."
                            : `Generate ${currentKindMeta.label}`}
                    </button>
                </section>
            )}
        </div>
    );
}
