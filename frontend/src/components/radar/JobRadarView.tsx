import { BookmarkCheck, BookmarkPlus, ExternalLink, Search, SlidersHorizontal } from "lucide-react";
import { useEffect, useState } from "react";
import { vektrynApi } from "../../api/client";
import type { MatchScore } from "../../types/models";
import { GapAnalysisDrawer } from "./GapAnalysisDrawer";

function scoreBadgeStyle(score: number | null): string {
    if (score === null) return "bg-zinc-800 text-zinc-400";
    if (score >= 80) return "bg-emerald-500/15 text-emerald-300 ring-1 ring-emerald-500/30";
    if (score >= 70) return "bg-violet-500/15 text-violet-300 ring-1 ring-violet-500/30";
    return "bg-zinc-800 text-zinc-300";
}

function formatScoreLabel(score: number | null): string {
    return score !== null ? `${score}% Fit` : "Vector Only";
}

function extractJobPostingId(jobPosting: unknown): string | null {
    if (typeof jobPosting === "string" && jobPosting.length > 0) {
        return jobPosting;
    }
    if (typeof jobPosting === "object" && jobPosting !== null && "uuid" in jobPosting) {
        const uuid = (jobPosting as { uuid?: unknown }).uuid;
        return typeof uuid === "string" && uuid.length > 0 ? uuid : null;
    }
    return null;
}

export function JobRadarView() {
    const [matches, setMatches] = useState<MatchScore[]>([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [searchTerm, setSearchTerm] = useState("");
    const [minScore, setMinScore] = useState<number>(0);
    const [selectedMatch, setSelectedMatch] = useState<MatchScore | null>(null);
    const [savedLeadsByJobId, setSavedLeadsByJobId] = useState<Record<string, string>>({});
    const [savingJobId, setSavingJobId] = useState<string | null>(null);

    async function refreshSavedLeads() {
        const leadRes = await vektrynApi.listLeads();
        const nextMap: Record<string, string> = {};
        for (const lead of leadRes.results) {
            const jobId = extractJobPostingId(lead.job_posting);
            if (jobId && lead.uuid) {
                nextMap[jobId] = lead.uuid;
            }
        }
        setSavedLeadsByJobId(nextMap);
    }

    useEffect(() => {
        let cancelled = false;
        async function load() {
            setLoading(true);
            setError(null);
            try {
                const [matchRes, leadRes] = await Promise.all([
                    vektrynApi.listMatches(),
                    vektrynApi.listLeads(),
                ]);
                if (cancelled) return;
                setMatches(matchRes.results);
                const nextMap: Record<string, string> = {};
                for (const lead of leadRes.results) {
                    const jobId = extractJobPostingId(lead.job_posting);
                    if (jobId && lead.uuid) {
                        nextMap[jobId] = lead.uuid;
                    }
                }
                setSavedLeadsByJobId(nextMap);
            } catch (err) {
                if (!cancelled) {
                    setError(err instanceof Error ? err.message : "Failed to load matches");
                }
            } finally {
                if (!cancelled) setLoading(false);
            }
        }
        void load();
        return () => {
            cancelled = true;
        };
    }, []);

    async function handleToggleSaveLead(match: MatchScore) {
        const jobId = match.job_posting.uuid;
        const existingLeadUuid = savedLeadsByJobId[jobId];
        setSavingJobId(jobId);
        setError(null);

        try {
            if (existingLeadUuid) {
                await vektrynApi.deleteLead(existingLeadUuid);
                setSavedLeadsByJobId((prev) => {
                    const copy = { ...prev };
                    delete copy[jobId];
                    return copy;
                });
            } else {
                const created = await vektrynApi.createLead({
                    job_posting: jobId,
                    resume_profile: match.resume_profile,
                    status: "saved",
                });
                setSavedLeadsByJobId((prev) => ({
                    ...prev,
                    [jobId]: created.uuid,
                }));
            }
        } catch (err) {
            const message = err instanceof Error ? err.message : String(err);
            const normalized = message.toLowerCase();

            if (!existingLeadUuid && (message.includes("API 400") || message.includes("API 409") || normalized.includes("already exists") || normalized.includes("unique"))) {
                await refreshSavedLeads();
            } else if (existingLeadUuid && message.includes("API 404")) {
                setSavedLeadsByJobId((prev) => {
                    const copy = { ...prev };
                    delete copy[jobId];
                    return copy;
                });
            } else {
                setError(message || "Failed to update saved lead");
            }
        } finally {
            setSavingJobId(null);
        }
    }

    const filtered = matches.filter((m) => {
        if (minScore > 0 && (m.fit_score ?? 0) < minScore) return false;
        if (!searchTerm.trim()) return true;
        const q = searchTerm.toLowerCase();
        return (
            m.job_posting.title.toLowerCase().includes(q) ||
            m.job_posting.company_name.toLowerCase().includes(q) ||
            m.job_posting.tech_stack.some((t) => t.toLowerCase().includes(q))
        );
    });

    function renderResults() {
        if (loading) {
            return <div className="py-16 text-center text-sm text-zinc-500">Loading semantic matches...</div>;
        }
        if (filtered.length === 0) {
            return (
                <div className="rounded-xl border border-zinc-800 bg-zinc-900/40 py-14 text-center text-sm text-zinc-400">
                    No matching roles found for the current filters.
                </div>
            );
        }

        return (
            <div className="grid gap-3">
                {filtered.map((match) => {
                    const job = match.job_posting;
                    const isSaved = Boolean(savedLeadsByJobId[job.uuid]);
                    const isBusy = savingJobId === job.uuid;
                    const actionLabel = isBusy
                        ? isSaved
                            ? "Removing..."
                            : "Saving..."
                        : isSaved
                            ? "Saved"
                            : "Save";

                    return (
                        <article
                            key={match.uuid}
                            className="group rounded-xl border border-zinc-800 bg-zinc-900/60 p-4 transition hover:border-violet-500/40 hover:bg-zinc-900"
                        >
                            <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                                <div className="space-y-1.5">
                                    <div className="flex flex-wrap items-center gap-2">
                                        <span
                                            className={`rounded-md px-2 py-0.5 font-mono text-xs font-semibold ${scoreBadgeStyle(
                                                match.fit_score,
                                            )}`}
                                        >
                                            {formatScoreLabel(match.fit_score)}
                                        </span>
                                        <span className="font-mono text-xs text-zinc-400">
                                            {(match.cosine_similarity * 100).toFixed(0)}% sim
                                        </span>
                                        <span className="rounded bg-zinc-800 px-1.5 py-0.5 text-[11px] uppercase text-zinc-400">
                                            {job.contract_type}
                                        </span>
                                        <span className="text-xs text-zinc-500">{job.ats_source}</span>
                                    </div>

                                    <h3>
                                        <button
                                            type="button"
                                            onClick={() => setSelectedMatch(match)}
                                            className="text-left text-base font-semibold text-zinc-100 hover:text-violet-300 focus:text-violet-300 focus:outline-none"
                                        >
                                            {job.title}
                                        </button>
                                    </h3>
                                    <p className="text-sm text-zinc-400">
                                        {job.company_name} · {job.location_raw || "Remote"}
                                    </p>

                                    <div className="flex flex-wrap gap-1.5 pt-1">
                                        {job.tech_stack.slice(0, 8).map((tag) => (
                                            <span
                                                key={tag}
                                                className="rounded bg-zinc-800/90 px-2 py-0.5 font-mono text-xs text-zinc-300"
                                            >
                                                {tag}
                                            </span>
                                        ))}
                                    </div>
                                </div>

                                <div className="flex shrink-0 items-center gap-2">
                                    <button
                                        type="button"
                                        onClick={() => setSelectedMatch(match)}
                                        className="rounded-lg border border-zinc-800 bg-zinc-900 px-3 py-1.5 text-xs font-medium text-zinc-300 hover:border-zinc-700 hover:text-zinc-100"
                                    >
                                        Gap Details
                                    </button>

                                    <button
                                        type="button"
                                        disabled={isBusy}
                                        onClick={() => void handleToggleSaveLead(match)}
                                        title={isSaved ? "Click to unsave from pipeline" : "Save to pipeline"}
                                        className={`inline-flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-xs font-medium disabled:opacity-60 ${isSaved
                                                ? "border-emerald-500/30 bg-emerald-950/30 text-emerald-200 hover:border-red-500/40 hover:bg-red-950/30 hover:text-red-200"
                                                : "border-zinc-700 bg-zinc-800/80 text-zinc-200 hover:bg-zinc-700"
                                            }`}
                                    >
                                        {isSaved ? (
                                            <>
                                                <BookmarkCheck className="h-3.5 w-3.5 text-emerald-400" />
                                                {actionLabel}
                                            </>
                                        ) : (
                                            <>
                                                <BookmarkPlus className="h-3.5 w-3.5 text-violet-400" />
                                                {actionLabel}
                                            </>
                                        )}
                                    </button>

                                    <a
                                        href={job.apply_url}
                                        target="_blank"
                                        rel="noreferrer"
                                        className="inline-flex items-center gap-1 rounded-lg bg-violet-600/90 px-3 py-1.5 text-xs font-medium text-white hover:bg-violet-500"
                                    >
                                        Apply <ExternalLink className="h-3.5 w-3.5" />
                                    </a>
                                </div>
                            </div>
                        </article>
                    );
                })}
            </div>
        );
    }

    return (
        <div className="space-y-5">
            <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                <div className="relative flex-1 max-w-md">
                    <Search className="pointer-events-none absolute top-2.5 left-3 h-4 w-4 text-zinc-500" />
                    <input
                        type="text"
                        value={searchTerm}
                        onChange={(e) => setSearchTerm(e.target.value)}
                        placeholder="Filter by role, company, or stack (e.g. django, kafka)..."
                        className="w-full rounded-lg border border-zinc-800 bg-zinc-900 py-2 pr-3 pl-9 text-sm text-zinc-100 placeholder:text-zinc-500 focus:border-violet-500 focus:outline-none"
                    />
                </div>

                <div className="flex items-center gap-2 text-sm">
                    <SlidersHorizontal className="h-4 w-4 text-zinc-400" />
                    <label htmlFor="min-fit" className="text-zinc-400">
                        Min Fit:
                    </label>
                    <select
                        id="min-fit"
                        value={minScore}
                        onChange={(e) => setMinScore(Number(e.target.value))}
                        className="rounded-lg border border-zinc-800 bg-zinc-900 px-2.5 py-1.5 text-sm text-zinc-100 focus:border-violet-500 focus:outline-none"
                    >
                        <option value={0}>All scored roles</option>
                        <option value={70}>70%+ (Alert threshold)</option>
                        <option value={80}>80%+ (Strong match)</option>
                    </select>
                </div>
            </div>

            {error && (
                <div className="rounded-xl border border-red-500/30 bg-red-950/20 p-4 text-sm text-red-300">
                    {error}
                </div>
            )}

            {renderResults()}

            <GapAnalysisDrawer
                match={selectedMatch}
                saving={selectedMatch ? savingJobId === selectedMatch.job_posting.uuid : false}
                saved={selectedMatch ? Boolean(savedLeadsByJobId[selectedMatch.job_posting.uuid]) : false}
                onClose={() => setSelectedMatch(null)}
                onSaveLead={(m) => void handleToggleSaveLead(m)}
            />
        </div>
    );
}