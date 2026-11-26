import { ArrowRight, ExternalLink, LogIn, Menu, Radar, X } from "lucide-react";
import { useState } from "react";
import { VEKTRYN_GITHUB_URL } from "./landingPreviewData";

interface LandingNavbarProps {
    isAuthenticated: boolean;
    onSignIn: () => void;
    onOpenWorkspace: () => void;
}

const SECTION_LINKS = [
    { href: "#preview", label: "Preview" },
    { href: "#capabilities", label: "Capabilities" },
    { href: "#architecture", label: "Architecture" },
    { href: "#stack", label: "Stack" },
];

export function LandingNavbar({
    isAuthenticated,
    onSignIn,
    onOpenWorkspace,
}: Readonly<LandingNavbarProps>) {
    const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

    const handlePrimaryAction = () => {
        setMobileMenuOpen(false);
        if (isAuthenticated) {
            onOpenWorkspace();
        } else {
            onSignIn();
        }
    };

    const primaryLabel = isAuthenticated ? "Open Workspace" : "Sign In";

    return (
        <header className="sticky top-0 z-40 border-b border-zinc-800/75 bg-zinc-950/85 backdrop-blur-md">
            <div className="mx-auto flex max-w-6xl items-center justify-between gap-4 px-4 py-3 sm:px-6">
                <a
                    href="#top"
                    className="inline-flex min-h-11 items-center gap-2.5 rounded-lg pr-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-500/70"
                >
                    <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-gradient-to-br from-violet-500/25 to-fuchsia-500/15 ring-1 ring-violet-500/40 shadow-sm shadow-violet-500/15">
                        <Radar className="h-4 w-4 text-violet-300" aria-hidden="true" />
                    </span>
                    <span className="font-mono text-base font-semibold tracking-tight text-zinc-100">
                        vektryn
                    </span>
                </a>

                <nav aria-label="Landing page sections" className="hidden items-center gap-1 md:flex">
                    {SECTION_LINKS.map((link) => (
                        <a
                            key={link.href}
                            href={link.href}
                            className="inline-flex min-h-11 items-center rounded-lg px-3 text-sm font-medium text-zinc-400 transition hover:bg-zinc-900/80 hover:text-zinc-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-500/70"
                        >
                            {link.label}
                        </a>
                    ))}
                </nav>

                <div className="hidden items-center gap-2.5 md:flex">
                    <a
                        href={VEKTRYN_GITHUB_URL}
                        target="_blank"
                        rel="noreferrer"
                        className="inline-flex min-h-11 items-center gap-1.5 rounded-xl border border-zinc-800 bg-zinc-900/60 px-3.5 text-sm font-medium text-zinc-300 transition hover:border-zinc-700 hover:bg-zinc-900 hover:text-zinc-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-500/70"
                    >
                        <span>GitHub</span>
                        <ExternalLink className="h-3.5 w-3.5 text-zinc-400" aria-hidden="true" />
                    </a>
                    <button
                        type="button"
                        onClick={handlePrimaryAction}
                        className="inline-flex min-h-11 items-center gap-2 rounded-xl bg-violet-600 px-4 text-sm font-medium text-white shadow-sm shadow-violet-600/25 transition hover:bg-violet-500 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-500/70"
                    >
                        {isAuthenticated ? (
                            <ArrowRight className="h-4 w-4" aria-hidden="true" />
                        ) : (
                            <LogIn className="h-4 w-4" aria-hidden="true" />
                        )}
                        <span>{primaryLabel}</span>
                    </button>
                </div>

                <button
                    type="button"
                    aria-label={mobileMenuOpen ? "Close navigation menu" : "Open navigation menu"}
                    aria-expanded={mobileMenuOpen}
                    onClick={() => setMobileMenuOpen((prev) => !prev)}
                    className="inline-flex h-11 w-11 items-center justify-center rounded-xl border border-zinc-800 bg-zinc-900/70 text-zinc-300 transition hover:border-zinc-700 hover:text-zinc-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-500/70 md:hidden"
                >
                    {mobileMenuOpen ? (
                        <X className="h-5 w-5" aria-hidden="true" />
                    ) : (
                        <Menu className="h-5 w-5" aria-hidden="true" />
                    )}
                </button>
            </div>

            {mobileMenuOpen && (
                <div className="border-t border-zinc-800/80 bg-zinc-950/95 px-4 py-4 md:hidden">
                    <nav aria-label="Mobile navigation" className="flex flex-col gap-1">
                        {SECTION_LINKS.map((link) => (
                            <a
                                key={link.href}
                                href={link.href}
                                onClick={() => setMobileMenuOpen(false)}
                                className="inline-flex min-h-11 items-center rounded-xl px-3 text-sm font-medium text-zinc-300 transition hover:bg-zinc-900 hover:text-zinc-100"
                            >
                                {link.label}
                            </a>
                        ))}
                    </nav>
                    <div className="mt-3 flex flex-col gap-2 border-t border-zinc-800/80 pt-3">
                        <a
                            href={VEKTRYN_GITHUB_URL}
                            target="_blank"
                            rel="noreferrer"
                            className="inline-flex min-h-11 items-center justify-center gap-2 rounded-xl border border-zinc-800 bg-zinc-900/70 px-4 text-sm font-medium text-zinc-200 transition hover:border-zinc-700 hover:bg-zinc-900"
                        >
                            <span>View on GitHub</span>
                            <ExternalLink className="h-4 w-4 text-zinc-400" aria-hidden="true" />
                        </a>
                        <button
                            type="button"
                            onClick={handlePrimaryAction}
                            className="inline-flex min-h-11 items-center justify-center gap-2 rounded-xl bg-violet-600 px-4 text-sm font-medium text-white shadow-sm shadow-violet-600/25 transition hover:bg-violet-500"
                        >
                            {isAuthenticated ? (
                                <ArrowRight className="h-4 w-4" aria-hidden="true" />
                            ) : (
                                <LogIn className="h-4 w-4" aria-hidden="true" />
                            )}
                            <span>{primaryLabel}</span>
                        </button>
                    </div>
                </div>
            )}
        </header>
    );
}
