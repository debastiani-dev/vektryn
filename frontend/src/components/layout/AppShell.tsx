import { BarChart3, Kanban, Radar, Radio } from "lucide-react";
import type { ReactNode } from "react";
import type { LiveMatchAlert } from "../../types/models";
import { LiveAlertBanner } from "./LiveAlertBanner";

export type ActiveTab = "radar" | "tracker" | "analytics";

interface AppShellProps {
    activeTab: ActiveTab;
    onSelectTab: (tab: ActiveTab) => void;
    sseConnected: boolean;
    alerts: LiveMatchAlert[];
    onDismissAlert: (eventId: string) => void;
    children: ReactNode;
}

const NAV_ITEMS: Array<{ id: ActiveTab; label: string; icon: typeof Radar }> = [
    { id: "radar", label: "Job Radar", icon: Radar },
    { id: "tracker", label: "Pipeline Tracker", icon: Kanban },
    { id: "analytics", label: "Stack Trends", icon: BarChart3 },
];

export function AppShell({
    activeTab,
    onSelectTab,
    sseConnected,
    alerts,
    onDismissAlert,
    children,
}: AppShellProps) {
    return (
        <div className="min-h-screen bg-zinc-950 text-zinc-100">
            <header className="sticky top-0 z-30 border-b border-zinc-800 bg-zinc-950/90 backdrop-blur">
                <div className="mx-auto flex max-w-7xl items-center justify-between px-4 py-3.5 sm:px-6">
                    <div className="flex items-center gap-6">
                        <div className="flex items-center gap-2.5">
                            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-violet-600/20 ring-1 ring-violet-500/40">
                                <Radar className="h-4 w-4 text-violet-400" />
                            </div>
                            <span className="font-mono text-base font-semibold tracking-tight text-zinc-100">
                                vektryn
                            </span>
                        </div>

                        <nav className="flex items-center gap-1">
                            {NAV_ITEMS.map(({ id, label, icon: Icon }) => {
                                const active = activeTab === id;
                                return (
                                    <button
                                        key={id}
                                        type="button"
                                        onClick={() => onSelectTab(id)}
                                        className={`inline-flex items-center gap-2 rounded-lg px-3 py-1.5 text-sm font-medium transition ${active
                                                ? "bg-zinc-800 text-zinc-100"
                                                : "text-zinc-400 hover:bg-zinc-900 hover:text-zinc-200"
                                            }`}
                                    >
                                        <Icon className="h-4 w-4" />
                                        {label}
                                    </button>
                                );
                            })}
                        </nav>
                    </div>

                    <div className="flex items-center gap-2 rounded-full border border-zinc-800 bg-zinc-900/70 px-3 py-1 text-xs">
                        <Radio
                            className={`h-3.5 w-3.5 ${sseConnected ? "animate-pulse text-emerald-400" : "text-zinc-500"
                                }`}
                        />
                        <span className={sseConnected ? "text-emerald-300" : "text-zinc-400"}>
                            {sseConnected ? "Live Stream" : "Stream Offline"}
                        </span>
                    </div>
                </div>
            </header>

            <LiveAlertBanner alerts={alerts} onDismiss={onDismissAlert} />

            <main className="mx-auto max-w-7xl px-4 py-6 sm:px-6">{children}</main>
        </div>
    );
}