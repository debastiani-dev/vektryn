import { ArrowRight, Compass, Kanban, Search, Sparkles } from "lucide-react";

const COPILOT_ARTIFACTS = [
    "Tailored Bullets",
    "Cover Letter",
    "Recruiter Note",
    "Interview Prep",
];

const PIPELINE_STEPS = [
    { label: "Saved", dot: "bg-violet-400" },
    { label: "Applied", dot: "bg-sky-400" },
    { label: "Screening", dot: "bg-amber-400" },
    { label: "Interviewing", dot: "bg-indigo-400" },
    { label: "Offer", dot: "bg-emerald-400" },
];

export function LandingCapabilities() {
    return (
        <section id="capabilities" className="scroll-mt-20 py-16 sm:py-24">
            <div className="mx-auto max-w-6xl px-4 sm:px-6">
                <div className="max-w-2xl">
                    <p className="font-mono text-xs font-medium uppercase tracking-widest text-violet-400">
                        Core Capabilities
                    </p>
                    <h2 className="mt-2 text-2xl font-semibold tracking-tight text-zinc-100 sm:text-3xl">
                        Built for focused, high-signal job searches
                    </h2>
                </div>

                {/* Asymmetric Bento Grid */}
                <div className="mt-10 grid grid-cols-1 gap-4 lg:grid-cols-12">
                    {/* Bento 1: Two-Stage Semantic Scoring (Wide) */}
                    <article className="flex flex-col justify-between rounded-2xl border border-white/[0.08] bg-gradient-to-b from-zinc-900/75 to-zinc-900/40 p-6 ring-1 ring-inset ring-white/[0.02] lg:col-span-7">
                        <div>
                            <div className="flex items-center gap-2.5 text-violet-300">
                                <Compass className="h-4 w-4" aria-hidden="true" />
                                <span className="font-mono text-xs uppercase tracking-wider">
                                    Two-Stage Scoring
                                </span>
                            </div>
                            <h3 className="mt-3 text-lg font-semibold text-zinc-100">
                                Multi-resume multilingual routing before Gemini analysis
                            </h3>
                            <p className="mt-2 max-w-xl text-sm leading-relaxed text-zinc-400">
                                Keep multiple active resumes across any language. Stage 1 applies
                                work-mode &amp; language routing plus{" "}
                                <span className="font-mono text-zinc-200">pgvector</span> similarity
                                to pick one winning resume before Gemini scores fit and gaps.
                            </p>
                        </div>

                        <div className="mt-6 flex flex-wrap items-center gap-2 rounded-xl border border-zinc-800/90 bg-zinc-950/80 p-3.5 font-mono text-xs">
                            <span className="rounded-lg border border-zinc-800 bg-zinc-900 px-2.5 py-1 text-zinc-300">
                                Multi-Resume
                            </span>
                            <ArrowRight className="h-3.5 w-3.5 text-zinc-600" aria-hidden="true" />
                            <span className="rounded-lg border border-zinc-800 bg-zinc-900 px-2.5 py-1 text-zinc-300">
                                pgvector 86%
                            </span>
                            <ArrowRight className="h-3.5 w-3.5 text-zinc-600" aria-hidden="true" />
                            <span className="rounded-lg bg-violet-500/15 px-2.5 py-1 font-semibold text-violet-300 ring-1 ring-violet-500/35">
                                AI FIT 92%
                            </span>
                            <span className="ml-auto hidden rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-2 py-0.5 text-[11px] text-emerald-200 sm:inline">
                                6 matched · 2 gaps
                            </span>
                        </div>
                    </article>

                    {/* Bento 2: Hybrid Search & Triage */}
                    <article className="flex flex-col justify-between rounded-2xl border border-white/[0.08] bg-gradient-to-b from-zinc-900/75 to-zinc-900/40 p-6 ring-1 ring-inset ring-white/[0.02] lg:col-span-5">
                        <div>
                            <div className="flex items-center gap-2.5 text-violet-300">
                                <Search className="h-4 w-4" aria-hidden="true" />
                                <span className="font-mono text-xs uppercase tracking-wider">
                                    Hybrid Search &amp; Triage
                                </span>
                            </div>
                            <h3 className="mt-3 text-lg font-semibold text-zinc-100">
                                Keyword precision meets semantic recall
                            </h3>
                            <p className="mt-2 text-sm leading-relaxed text-zinc-400">
                                Reciprocal Rank Fusion merges full-text and vector search with
                                cross-source near-duplicate merging (promoting Direct ATS links),
                                repost detection and filtering, work-mode &amp; language filters,
                                saved presets, company muting, and manual URL imports.
                            </p>
                        </div>

                        <div className="mt-6 flex flex-wrap items-center gap-2 rounded-xl border border-zinc-800/90 bg-zinc-950/80 p-3.5 font-mono text-[11px]">
                            <span className="rounded-md bg-violet-500/15 px-2 py-1 text-violet-300 ring-1 ring-violet-500/30">
                                Hybrid RRF
                            </span>
                            <span className="rounded-md border border-zinc-800 bg-zinc-900 px-2 py-1 text-zinc-300">
                                Cross-Source Dedup
                            </span>
                            <span className="rounded-md border border-zinc-800 bg-zinc-900 px-2 py-1 text-zinc-300">
                                Work &amp; Language
                            </span>
                            <span className="rounded-md border border-zinc-800 bg-zinc-900 px-2 py-1 text-zinc-300">
                                Saved Presets
                            </span>
                            <span className="rounded-md border border-zinc-800 bg-zinc-900 px-2 py-1 text-zinc-300">
                                Manual Import
                            </span>
                        </div>
                    </article>

                    {/* Bento 3: AI Application Copilot */}
                    <article className="flex flex-col justify-between rounded-2xl border border-white/[0.08] bg-gradient-to-b from-zinc-900/75 to-zinc-900/40 p-6 ring-1 ring-inset ring-white/[0.02] lg:col-span-5">
                        <div>
                            <div className="flex items-center gap-2.5 text-violet-300">
                                <Sparkles className="h-4 w-4" aria-hidden="true" />
                                <span className="font-mono text-xs uppercase tracking-wider">
                                    AI Application Copilot
                                </span>
                            </div>
                            <h3 className="mt-3 text-lg font-semibold text-zinc-100">
                                From gap breakdown to tailored drafts
                            </h3>
                            <p className="mt-2 text-sm leading-relaxed text-zinc-400">
                                Generate role-specific Markdown artifacts in the posting&apos;s
                                language—grounded in your resume, match analysis, and preferred
                                tone, and cached per role for instant reuse.
                            </p>
                        </div>

                        <div className="mt-6 grid grid-cols-2 gap-2">
                            {COPILOT_ARTIFACTS.map((artifact) => (
                                <span
                                    key={artifact}
                                    className="rounded-xl border border-zinc-800/90 bg-zinc-950/80 px-3 py-2 text-xs font-medium text-zinc-300"
                                >
                                    {artifact}
                                </span>
                            ))}
                        </div>
                    </article>

                    {/* Bento 4: Pipeline Tracker & Personal Analytics (Wide) */}
                    <article className="flex flex-col justify-between rounded-2xl border border-white/[0.08] bg-gradient-to-b from-zinc-900/75 to-zinc-900/40 p-6 ring-1 ring-inset ring-white/[0.02] lg:col-span-7">
                        <div>
                            <div className="flex items-center gap-2.5 text-violet-300">
                                <Kanban className="h-4 w-4" aria-hidden="true" />
                                <span className="font-mono text-xs uppercase tracking-wider">
                                    Tracker &amp; Market Intelligence
                                </span>
                            </div>
                            <h3 className="mt-3 text-lg font-semibold text-zinc-100">
                                Manage applications alongside live market trends
                            </h3>
                            <p className="mt-2 max-w-xl text-sm leading-relaxed text-zinc-400">
                                Track leads across Kanban stages with overdue follow-up highlights,
                                closed-job notifications, and CSV/JSON exports—paired with tech-stack
                                demand, median USD compensation, and your personal conversion funnel.
                            </p>
                        </div>

                        <div className="mt-6 flex flex-wrap items-center gap-2 rounded-xl border border-zinc-800/90 bg-zinc-950/80 p-3.5">
                            {PIPELINE_STEPS.map((step, index) => (
                                <div key={step.label} className="flex items-center gap-2">
                                    <span className="inline-flex items-center gap-1.5 rounded-lg border border-zinc-800 bg-zinc-900 px-2.5 py-1 text-xs font-medium text-zinc-200">
                                        <span className={`h-1.5 w-1.5 rounded-full ${step.dot}`} />
                                        <span>{step.label}</span>
                                    </span>
                                    {index < PIPELINE_STEPS.length - 1 && (
                                        <ArrowRight
                                            className="h-3 w-3 text-zinc-600"
                                            aria-hidden="true"
                                        />
                                    )}
                                </div>
                            ))}
                        </div>
                    </article>
                </div>
            </div>
        </section>
    );
}
