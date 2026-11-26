import { ArrowRight, LogIn } from "lucide-react";

interface LandingHeroProps {
    isAuthenticated: boolean;
    onSignIn: () => void;
    onOpenWorkspace: () => void;
}

export function LandingHero({
    isAuthenticated,
    onSignIn,
    onOpenWorkspace,
}: Readonly<LandingHeroProps>) {
    const primaryAction = isAuthenticated ? onOpenWorkspace : onSignIn;
    const primaryLabel = isAuthenticated ? "Open Workspace" : "Sign In";

    return (
        <section
            id="top"
            className="relative mx-auto max-w-6xl px-4 pt-12 pb-8 sm:px-6 sm:pt-16 sm:pb-10"
        >
            <div
                aria-hidden="true"
                className="pointer-events-none absolute inset-x-0 -top-12 bottom-0 -z-10 bg-[linear-gradient(to_right,rgba(255,255,255,0.025)_1px,transparent_1px),linear-gradient(to_bottom,rgba(255,255,255,0.025)_1px,transparent_1px)] bg-[size:48px_48px] [mask-image:radial-gradient(ellipse_65%_65%_at_50%_20%,#000_55%,transparent_100%)]"
            />

            <div className="mx-auto max-w-3xl text-center">
                <div className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-zinc-900/75 px-3.5 py-1 text-xs font-medium text-zinc-300">
                    <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" aria-hidden="true" />
                    <span>Semantic Job Radar · Tech Market Intelligence</span>
                </div>

                <h1 className="mt-5 text-4xl font-semibold tracking-tight text-zinc-50 sm:text-5xl lg:text-[3.5rem] lg:leading-[1.08]">
                    High-signal job radar{" "}
                    <span className="bg-gradient-to-r from-violet-300 via-fuchsia-300 to-sky-300 bg-clip-text text-transparent">
                        built for software engineers.
                    </span>
                </h1>

                <p className="mx-auto mt-5 max-w-2xl text-base leading-relaxed text-zinc-400 sm:text-lg">
                    Ingests remote engineering roles across 14 sources, ranks every opening against
                    your resume with semantic search and Gemini, and drives your pipeline from gap
                    analysis to offer.
                </p>

                <div className="mt-7 flex flex-col items-stretch justify-center gap-3 sm:flex-row sm:items-center">
                    <button
                        type="button"
                        onClick={primaryAction}
                        className="inline-flex min-h-11 items-center justify-center gap-2 rounded-xl bg-violet-600 px-6 text-sm font-medium text-white shadow-lg shadow-violet-600/25 ring-1 ring-inset ring-white/15 transition hover:bg-violet-500 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-500/70"
                    >
                        {isAuthenticated ? (
                            <ArrowRight className="h-4 w-4" aria-hidden="true" />
                        ) : (
                            <LogIn className="h-4 w-4" aria-hidden="true" />
                        )}
                        <span>{primaryLabel}</span>
                    </button>

                    <a
                        href="#architecture"
                        className="inline-flex min-h-11 items-center justify-center gap-2 rounded-xl border border-white/10 bg-zinc-900/75 px-5 text-sm font-medium text-zinc-200 transition hover:border-zinc-700 hover:bg-zinc-900 hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-500/70"
                    >
                        <span>How It Works</span>
                        <ArrowRight className="h-4 w-4 text-zinc-400" aria-hidden="true" />
                    </a>
                </div>
            </div>
        </section>
    );
}
