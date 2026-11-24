import { BarChart3, FileText, Kanban, LogOut, Radar, User } from "lucide-react";
import type { ReactNode } from "react";
import type { CurrentUser, LiveMatchAlert } from "../../types/models";
import { Tooltip } from "../ui/Tooltip";
import { LiveAlertBanner } from "./LiveAlertBanner";

export type ActiveTab = "radar" | "tracker" | "analytics" | "resumes";

interface AppShellProps {
    activeTab: ActiveTab;
    onSelectTab: (tab: ActiveTab) => void;
    user: CurrentUser | null;
    onLogout: () => void;
    sseConnected: boolean;
    alerts: LiveMatchAlert[];
    onDismissAlert: (eventId: string) => void;
    children: ReactNode;
}

const NAV_ITEMS: Array<{
    id: ActiveTab;
    label: string;
    tooltip: string;
    icon: typeof Radar;
}> = [
    {
        id: "radar",
        label: "Job Radar",
        tooltip: "Browse AI-scored and vector-matched job postings",
        icon: Radar,
    },
    {
        id: "tracker",
        label: "Pipeline Tracker",
        tooltip: "Track saved applications across interview stages",
        icon: Kanban,
    },
    {
        id: "analytics",
        label: "Stack Trends",
        tooltip: "Explore daily technology demand and median compensation",
        icon: BarChart3,
    },
    {
        id: "resumes",
        label: "Resumes",
        tooltip: "Upload resumes and configure target seniority, contract, and region filters",
        icon: FileText,
    },
];

export function AppShell({
    activeTab,
    onSelectTab,
    user,
    onLogout,
    sseConnected,
    alerts,
    onDismissAlert,
    children,
}: Readonly<AppShellProps>) {
    const streamTooltip = sseConnected
        ? "Connected to real-time signed SSE match alert stream"
        : "Real-time SSE alert stream disconnected — retrying automatically";

    return (
        <div className="min-h-screen text-zinc-100">
            <header className="sticky top-0 z-30 border-b border-zinc-800/80 bg-zinc-950/80 backdrop-blur-md">
                <div className="mx-auto flex max-w-[1600px] flex-wrap items-center justify-between gap-4 px-6 py-4 sm:px-8 lg:px-10">
                    <div className="flex flex-wrap items-center gap-6 sm:gap-8">
                        <Tooltip
                            content="Vektryn — Job intelligence & career radar"
                            side="bottom"
                        >
                            <div className="flex items-center gap-3">
                                <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-gradient-to-br from-violet-500/25 to-fuchsia-500/15 ring-1 ring-violet-500/40 shadow-sm shadow-violet-500/10">
                                    <Radar className="h-5 w-5 text-violet-300" />
                                </div>
                                <span className="font-mono text-lg font-semibold tracking-tight text-zinc-100">
                                    vektryn
                                </span>
                            </div>
                        </Tooltip>

                        <nav aria-label="Primary" className="flex flex-wrap items-center gap-2">
                            {NAV_ITEMS.map(({ id, label, tooltip, icon: Icon }) => {
                                const active = activeTab === id;
                                return (
                                    <Tooltip key={id} content={tooltip} side="bottom">
                                        <button
                                            type="button"
                                            aria-current={active ? "page" : undefined}
                                            onClick={() => onSelectTab(id)}
                                            className={`inline-flex items-center gap-2.5 rounded-xl px-4 py-2 text-sm font-medium transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-500/70 focus-visible:ring-offset-2 focus-visible:ring-offset-zinc-950 ${active
                                                    ? "bg-zinc-900 text-zinc-100 ring-1 ring-violet-500/40 shadow-sm shadow-violet-500/10"
                                                    : "text-zinc-400 hover:bg-zinc-900/70 hover:text-zinc-200"
                                                }`}
                                        >
                                            <Icon
                                                className={`h-4 w-4 ${active ? "text-violet-400" : "text-zinc-500"}`}
                                            />
                                            {label}
                                        </button>
                                    </Tooltip>
                                );
                            })}
                        </nav>
                    </div>

                    <div className="flex items-center gap-3">
                        <Tooltip content={streamTooltip} side="bottom">
                            <div
                                className={`inline-flex items-center gap-2.5 rounded-full px-3.5 py-1.5 text-xs font-medium ring-1 ring-inset ${sseConnected
                                        ? "bg-emerald-950/35 text-emerald-300 ring-emerald-500/30"
                                        : "bg-zinc-900/80 text-zinc-400 ring-zinc-800"
                                    }`}
                            >
                                <span className="relative flex h-2 w-2">
                                    {sseConnected && (
                                        <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75" />
                                    )}
                                    <span
                                        className={`relative inline-flex h-2 w-2 rounded-full ${sseConnected ? "bg-emerald-400" : "bg-zinc-600"
                                            }`}
                                    />
                                </span>
                                <span>{sseConnected ? "Live Stream" : "Stream Offline"}</span>
                            </div>
                        </Tooltip>

                        {user && (
                            <div className="flex items-center gap-1.5 rounded-full border border-zinc-800 bg-zinc-900/70 py-1 pr-1.5 pl-3 text-xs text-zinc-300">
                                <User className="h-3.5 w-3.5 text-zinc-500" />
                                <span className="max-w-28 truncate font-medium">
                                    {user.username}
                                </span>
                                <Tooltip content="Sign out of Vektryn" side="bottom">
                                    <button
                                        type="button"
                                        onClick={onLogout}
                                        aria-label="Sign out"
                                        className="rounded-full p-1 text-zinc-400 transition hover:bg-zinc-800 hover:text-zinc-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-500/70"
                                    >
                                        <LogOut className="h-3.5 w-3.5" />
                                    </button>
                                </Tooltip>
                            </div>
                        )}
                    </div>
                </div>
            </header>

            <LiveAlertBanner alerts={alerts} onDismiss={onDismissAlert} />

            <main className="mx-auto max-w-[1600px] px-6 py-8 sm:px-8 sm:py-10 lg:px-10 lg:py-12">
                {children}
            </main>
        </div>
    );
}
