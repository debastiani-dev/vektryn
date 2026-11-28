import { ArrowRight, ExternalLink, LogIn } from "lucide-react";
import { VektrynLogo } from "../ui/VektrynLogo";
import { VEKTRYN_GITHUB_URL } from "./landingPreviewData";

interface LandingFooterProps {
    isAuthenticated: boolean;
    onSignIn: () => void;
    onOpenWorkspace: () => void;
}

export function LandingFooter({
    isAuthenticated,
    onSignIn,
    onOpenWorkspace,
}: Readonly<LandingFooterProps>) {
    const primaryAction = isAuthenticated ? onOpenWorkspace : onSignIn;
    const primaryLabel = isAuthenticated ? "Open Workspace" : "Sign In to Vektryn";

    return (
        <footer>
            <div className="mx-auto max-w-6xl px-4 py-14 sm:px-6 sm:py-16">
                <div className="rounded-2xl border border-violet-500/30 bg-gradient-to-br from-violet-950/35 via-zinc-900/80 to-zinc-950 p-6 text-center ring-1 ring-inset ring-white/[0.04] sm:p-10">
                    <h2 className="text-2xl font-semibold tracking-tight text-zinc-100 sm:text-3xl">
                        Ready to inspect your semantic job radar?
                    </h2>
                    <p className="mx-auto mt-3 max-w-lg text-balance text-sm leading-relaxed text-zinc-400">
                        Sign in to open your live workspace, or explore the full monorepo source on
                        GitHub.
                    </p>
                    <div className="mt-6 flex flex-col items-stretch justify-center gap-3 sm:flex-row sm:items-center">
                        <button
                            type="button"
                            onClick={primaryAction}
                            className="inline-flex min-h-12 items-center justify-center gap-2 rounded-xl bg-violet-600 px-6 text-sm font-medium text-white shadow-lg shadow-violet-600/25 transition hover:bg-violet-500 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-500/70"
                        >
                            {isAuthenticated ? (
                                <ArrowRight className="h-4 w-4" aria-hidden="true" />
                            ) : (
                                <LogIn className="h-4 w-4" aria-hidden="true" />
                            )}
                            <span>{primaryLabel}</span>
                        </button>
                        <a
                            href={VEKTRYN_GITHUB_URL}
                            target="_blank"
                            rel="noreferrer"
                            className="inline-flex min-h-12 items-center justify-center gap-2 rounded-xl border border-zinc-700 bg-zinc-900/70 px-6 text-sm font-medium text-zinc-200 transition hover:border-zinc-600 hover:bg-zinc-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-500/70"
                        >
                            <span>View on GitHub</span>
                            <ExternalLink className="h-4 w-4 text-zinc-400" aria-hidden="true" />
                        </a>
                    </div>
                </div>

                <div className="mt-10 flex flex-col gap-6 border-t border-zinc-800/80 pt-8 sm:flex-row sm:items-center sm:justify-between">
                    <div className="space-y-1.5">
                        <div className="flex items-center gap-2">
                            <VektrynLogo className="h-5 w-5" />
                            <span className="font-mono text-sm font-semibold text-zinc-100">
                                vektryn
                            </span>
                        </div>
                        <p className="text-xs text-zinc-500">
                            <span className="font-mono text-zinc-400">Vekt-</span> (vector matching)
                            + <span className="font-mono text-zinc-400">-ryn</span> (fast-flowing
                            channel)
                        </p>
                        <p className="text-xs text-zinc-500">
                            System Architecture &amp; Development by{" "}
                            <a
                                href="https://debastiani.dev"
                                target="_blank"
                                rel="noreferrer"
                                className="text-zinc-300 underline decoration-zinc-700 underline-offset-4 transition hover:text-violet-300"
                            >
                                debastiani.dev
                            </a>
                        </p>
                    </div>

                    <div className="flex flex-wrap items-center gap-x-5 gap-y-2 text-xs text-zinc-400">
                        <a href="#preview" className="transition hover:text-zinc-100">
                            Preview
                        </a>
                        <a href="#capabilities" className="transition hover:text-zinc-100">
                            Capabilities
                        </a>
                        <a href="#architecture" className="transition hover:text-zinc-100">
                            Architecture
                        </a>
                        <a href="#stack" className="transition hover:text-zinc-100">
                            Stack
                        </a>
                    </div>
                </div>
            </div>
        </footer>
    );
}
