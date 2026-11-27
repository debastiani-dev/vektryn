import {
    BarChart3,
    ChevronDown,
    FileText,
    Kanban,
    LogOut,
    Radar,
    User,
    UserCog,
    Users,
} from "lucide-react";
import { type ReactNode, useEffect, useRef, useState } from "react";
import type { CurrentUser, LiveMatchAlert, UserProfileDetail } from "../../types/models";
import { Tooltip } from "../ui/Tooltip";
import { VektrynLogo } from "../ui/VektrynLogo";
import { AccountSettingsModal } from "./AccountSettingsModal";
import { LiveAlertBanner } from "./LiveAlertBanner";
import { NotificationCenter, type NotificationCenterProps } from "./NotificationCenter";
import { PipelineStatusPopover } from "./PipelineStatusPopover";
import { UserManagementModal } from "./UserManagementModal";

export type ActiveTab = "radar" | "tracker" | "analytics" | "resumes";

interface AppShellProps {
    activeTab: ActiveTab;
    onSelectTab: (tab: ActiveTab) => void;
    user: CurrentUser | null;
    settingsModalOpen: boolean;
    onOpenSettings: () => void;
    onCloseSettings: () => void;
    onUserProfileSaved: (profile: UserProfileDetail) => void;
    onAccountDeactivated: () => void;
    onLogout: () => void;
    sseConnected: boolean;
    alerts: LiveMatchAlert[];
    onDismissAlert: (eventId: string) => void;
    notificationCenter: NotificationCenterProps;
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

interface UserAccountMenuProps {
    user: CurrentUser;
    onOpenSettings: () => void;
    onOpenUserManagement: () => void;
    onLogout: () => void;
}

function UserAccountMenu({
    user,
    onOpenSettings,
    onOpenUserManagement,
    onLogout,
}: Readonly<UserAccountMenuProps>) {
    const [menuOpen, setMenuOpen] = useState(false);
    const menuRef = useRef<HTMLDivElement>(null);

    useEffect(() => {
        if (!menuOpen) {
            return;
        }
        function handlePointerDown(event: MouseEvent) {
            if (menuRef.current && !menuRef.current.contains(event.target as Node)) {
                setMenuOpen(false);
            }
        }
        function handleKeyDown(event: KeyboardEvent) {
            if (event.key === "Escape") {
                setMenuOpen(false);
            }
        }
        document.addEventListener("mousedown", handlePointerDown);
        globalThis.addEventListener("keydown", handleKeyDown);
        return () => {
            document.removeEventListener("mousedown", handlePointerDown);
            globalThis.removeEventListener("keydown", handleKeyDown);
        };
    }, [menuOpen]);

    const displayLabel = user.profile?.display_name || user.username;

    return (
        <div ref={menuRef} className="relative">
            <button
                type="button"
                aria-haspopup="menu"
                aria-expanded={menuOpen}
                onClick={() => setMenuOpen((prev) => !prev)}
                className="inline-flex items-center gap-2 rounded-full border border-zinc-800 bg-zinc-900/70 py-1.5 pr-2.5 pl-3 text-xs text-zinc-200 transition hover:border-zinc-700 hover:bg-zinc-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-500/70"
            >
                <User className="h-3.5 w-3.5 text-zinc-400" />
                <span className="max-w-32 truncate font-medium">{displayLabel}</span>
                <ChevronDown
                    className={`h-3.5 w-3.5 text-zinc-500 transition-transform ${
                        menuOpen ? "rotate-180" : ""
                    }`}
                />
            </button>

            {menuOpen && (
                <div
                    role="menu"
                    className="absolute right-0 mt-2 w-60 overflow-hidden rounded-xl border border-zinc-800 bg-zinc-950/95 p-1.5 shadow-2xl ring-1 ring-inset ring-white/[0.04] backdrop-blur-md"
                >
                    <div className="border-b border-zinc-800/80 px-3 py-2">
                        <div className="flex items-center gap-2">
                            <span className="truncate text-xs font-semibold text-zinc-100">
                                {displayLabel}
                            </span>
                            {user.is_staff && (
                                <span className="rounded-full bg-violet-500/15 px-1.5 py-0.5 text-[10px] font-medium text-violet-300 ring-1 ring-violet-500/30">
                                    Staff
                                </span>
                            )}
                        </div>
                        {user.profile?.display_name && (
                            <p className="mt-0.5 truncate font-mono text-[11px] text-zinc-500">
                                @{user.username}
                            </p>
                        )}
                        {user.email && (
                            <p className="mt-0.5 truncate text-[11px] text-zinc-500">
                                {user.email}
                            </p>
                        )}
                    </div>

                    <div className="space-y-0.5 py-1">
                        <button
                            type="button"
                            role="menuitem"
                            onClick={() => {
                                setMenuOpen(false);
                                onOpenSettings();
                            }}
                            className="flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-left text-xs font-medium text-zinc-200 transition hover:bg-zinc-900 hover:text-white"
                        >
                            <UserCog className="h-3.5 w-3.5 text-violet-400" />
                            <span>Account Settings</span>
                        </button>

                        {user.is_staff && (
                            <button
                                type="button"
                                role="menuitem"
                                onClick={() => {
                                    setMenuOpen(false);
                                    onOpenUserManagement();
                                }}
                                className="flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-left text-xs font-medium text-zinc-200 transition hover:bg-zinc-900 hover:text-white"
                            >
                                <Users className="h-3.5 w-3.5 text-violet-400" />
                                <span>Manage Users</span>
                            </button>
                        )}
                    </div>

                    <div className="border-t border-zinc-800/80 pt-1">
                        <button
                            type="button"
                            role="menuitem"
                            onClick={() => {
                                setMenuOpen(false);
                                onLogout();
                            }}
                            className="flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-left text-xs font-medium text-zinc-400 transition hover:bg-red-950/35 hover:text-red-300"
                        >
                            <LogOut className="h-3.5 w-3.5" />
                            <span>Sign Out</span>
                        </button>
                    </div>
                </div>
            )}
        </div>
    );
}

export function AppShell({
    activeTab,
    onSelectTab,
    user,
    settingsModalOpen,
    onOpenSettings,
    onCloseSettings,
    onUserProfileSaved,
    onAccountDeactivated,
    onLogout,
    sseConnected,
    alerts,
    onDismissAlert,
    notificationCenter,
    children,
}: Readonly<AppShellProps>) {
    const [userMgmtModalOpen, setUserMgmtModalOpen] = useState(false);

    const streamTooltip = sseConnected
        ? "Connected to real-time signed SSE match alert stream"
        : "Real-time SSE alert stream disconnected — retrying automatically";

    return (
        <div className="min-h-screen overflow-x-clip text-zinc-100">
            <header className="sticky top-0 z-30 border-b border-zinc-800/80 bg-zinc-950/80 backdrop-blur-md">
                <div className="mx-auto flex max-w-[1600px] flex-wrap items-center justify-between gap-4 px-4 py-4 sm:px-8 lg:px-10">
                    <div className="flex flex-wrap items-center gap-6 sm:gap-8">
                        <Tooltip
                            content="Vektryn — Job intelligence & career radar"
                            side="bottom"
                        >
                            <div className="flex items-center gap-3">
                                <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-zinc-900 ring-1 ring-zinc-800">
                                    <VektrynLogo className="h-7 w-7" />
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
                                            className={`inline-flex items-center gap-2.5 rounded-xl px-4 py-2 text-sm font-medium transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-500/70 focus-visible:ring-offset-2 focus-visible:ring-offset-zinc-950 ${
                                                active
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

                    <div className="flex flex-wrap items-center gap-2 sm:gap-3">
                        <PipelineStatusPopover isStaff={Boolean(user?.is_staff)} />

                        <Tooltip content={streamTooltip} side="bottom">
                            <div
                                className={`inline-flex items-center gap-2.5 rounded-full px-3.5 py-1.5 text-xs font-medium ring-1 ring-inset ${
                                    sseConnected
                                        ? "bg-emerald-950/35 text-emerald-300 ring-emerald-500/30"
                                        : "bg-zinc-900/80 text-zinc-400 ring-zinc-800"
                                }`}
                            >
                                <span className="relative flex h-2 w-2">
                                    {sseConnected && (
                                        <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75" />
                                    )}
                                    <span
                                        className={`relative inline-flex h-2 w-2 rounded-full ${
                                            sseConnected ? "bg-emerald-400" : "bg-zinc-600"
                                        }`}
                                    />
                                </span>
                                <span>{sseConnected ? "Live Stream" : "Stream Offline"}</span>
                            </div>
                        </Tooltip>

                        <NotificationCenter {...notificationCenter} />

                        {user && (
                            <UserAccountMenu
                                user={user}
                                onOpenSettings={onOpenSettings}
                                onOpenUserManagement={() => setUserMgmtModalOpen(true)}
                                onLogout={onLogout}
                            />
                        )}
                    </div>
                </div>
            </header>

            <LiveAlertBanner alerts={alerts} onDismiss={onDismissAlert} />

            <main className="mx-auto w-full min-w-0 max-w-[1600px] px-4 py-6 sm:px-8 sm:py-10 lg:px-10 lg:py-12">
                {children}
            </main>

            {user && (
                <AccountSettingsModal
                    open={settingsModalOpen}
                    user={user}
                    onClose={onCloseSettings}
                    onProfileSaved={onUserProfileSaved}
                    onAccountDeactivated={() => {
                        onCloseSettings();
                        onAccountDeactivated();
                    }}
                />
            )}

            {user?.is_staff && (
                <UserManagementModal
                    open={userMgmtModalOpen}
                    currentUser={user}
                    onClose={() => setUserMgmtModalOpen(false)}
                />
            )}
        </div>
    );
}
