import {
    BookmarkPlus,
    CheckCircle2,
    ExternalLink,
    MessageSquareQuote,
    Sparkles,
    X,
    XCircle,
} from "lucide-react";
import type { MatchScore } from "../../types/models";

interface GapAnalysisDrawerProps {
    match: MatchScore | null;
    saving: boolean;
    saved: boolean;
    onClose: () => void;
    onSaveLead: (match: MatchScore) => void;
}

export function GapAnalysisDrawer({
    match,
    saving,
    saved,
    onClose,
    onSaveLead,
}: GapAnalysisDrawerProps) {
    if (!match) {
        return null;
    }

    const job = match.job_posting;

    return (
        <div className="fixed inset-0 z-40 flex justify-end bg-black/60 backdrop-blur-xs">
            <div className="flex h-full w-full max-w-2xl flex-col border-l border-zinc-800 bg-zinc-950 shadow-2xl">
                <div className="flex items-start justify-between border-b border-zinc-800 px-6 py-4">
                    <div className="space-y-1">
                        <div className="flex items-center gap-2">
                            <span className="rounded bg-violet-500/15 px-2 py-0.5 font-mono text-xs font-semibold text-violet-300">
                                Fit {match.fit_score ?? "N/A"}%
                            </span>
                            <span className="rounded bg-zinc-800 px-2 py-0.5 font-mono text-xs text-zinc-300">
                                Cosine {(match.cosine_similarity * 100).toFixed(1)}%
                            </span>
                            <span className="text-xs uppercase text-zinc-500">{job.ats_source}</span>
                        </div>
                        <h2 className="text-lg font-semibold text-zinc-100">{job.title}</h2>
                        <p className="text-sm text-zinc-400">
                            {job.company_name} · {job.location_raw || "Remote"} ·{" "}
                            <span className="uppercase">{job.contract_type}</span>
                        </p>
                    </div>

                    <button
                        type="button"
                        onClick={onClose}
                        aria-label="Close drawer"
                        className="rounded-lg p-1.5 text-zinc-400 hover:bg-zinc-900 hover:text-zinc-100"
                    >
                        <X className="h-5 w-5" />
                    </button>
                </div>

                <div className="flex-1 space-y-6 overflow-y-auto px-6 py-5">
                    {match.gap_summary && (
                        <section className="rounded-xl border border-zinc-800 bg-zinc-900/60 p-4">
                            <div className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-violet-300">
                                <Sparkles className="h-3.5 w-3.5" />
                                Fit Summary ({match.scoring_model || "gemini"})
                            </div>
                            <p className="text-sm leading-relaxed text-zinc-300">{match.gap_summary}</p>
                        </section>
                    )}

                    <div className="grid gap-4 sm:grid-cols-2">
                        <section className="rounded-xl border border-emerald-500/20 bg-emerald-950/10 p-4">
                            <h3 className="mb-3 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider text-emerald-300">
                                <CheckCircle2 className="h-4 w-4" />
                                Matched Skills ({match.matched_skills.length})
                            </h3>
                            <div className="flex flex-wrap gap-1.5">
                                {match.matched_skills.length > 0 ? (
                                    match.matched_skills.map((skill) => (
                                        <span
                                            key={skill}
                                            className="rounded-md bg-emerald-500/15 px-2 py-1 font-mono text-xs text-emerald-200"
                                        >
                                            {skill}
                                        </span>
                                    ))
                                ) : (
                                    <span className="text-xs text-zinc-500">No matched skills recorded</span>
                                )}
                            </div>
                        </section>

                        <section className="rounded-xl border border-amber-500/20 bg-amber-950/10 p-4">
                            <h3 className="mb-3 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider text-amber-300">
                                <XCircle className="h-4 w-4" />
                                Missing Keywords ({match.missing_keywords.length})
                            </h3>
                            <div className="flex flex-wrap gap-1.5">
                                {match.missing_keywords.length > 0 ? (
                                    match.missing_keywords.map((kw) => (
                                        <span
                                            key={kw}
                                            className="rounded-md bg-amber-500/15 px-2 py-1 font-mono text-xs text-amber-200"
                                        >
                                            {kw}
                                        </span>
                                    ))
                                ) : (
                                    <span className="text-xs text-zinc-500">No critical gaps flagged</span>
                                )}
                            </div>
                        </section>
                    </div>

                    <section className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-4">
                        <h3 className="mb-3 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider text-zinc-300">
                            <MessageSquareQuote className="h-4 w-4 text-violet-400" />
                            Interview Talking Points
                        </h3>
                        {match.talking_points.length > 0 ? (
                            <ul className="space-y-2 text-sm text-zinc-300">
                                {match.talking_points.map((point) => (
                                    <li key={point} className="flex gap-2.5">
                                        <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-violet-400" />
                                        <span>{point}</span>
                                    </li>
                                ))}
                            </ul>
                        ) : (
                            <p className="text-xs text-zinc-500">No talking points generated for this match.</p>
                        )}
                    </section>
                </div>

                <div className="flex items-center justify-between border-t border-zinc-800 bg-zinc-900/80 px-6 py-4">
                    <button
                        type="button"
                        disabled={saving || saved}
                        onClick={() => onSaveLead(match)}
                        className="inline-flex items-center gap-2 rounded-lg bg-zinc-800 px-4 py-2 text-sm font-medium text-zinc-100 hover:bg-zinc-700 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                        <BookmarkPlus className="h-4 w-4 text-violet-400" />
                        {saved ? "Saved in Pipeline" : saving ? "Saving..." : "Save to Tracker"}
                    </button>

                    <a
                        href={job.apply_url}
                        target="_blank"
                        rel="noreferrer"
                        className="inline-flex items-center gap-2 rounded-lg bg-violet-600 px-4 py-2 text-sm font-medium text-white hover:bg-violet-500"
                    >
                        Open Original Posting <ExternalLink className="h-4 w-4" />
                    </a>
                </div>
            </div>
        </div>
    );
}