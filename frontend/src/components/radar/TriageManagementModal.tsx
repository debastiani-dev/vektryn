import { Ban, Building2, EyeOff, Loader2, Plus, RotateCcw, X } from "lucide-react";
import { type SyntheticEvent, useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { vektrynApi } from "../../api/client";
import type { DismissedJob, MutedCompany } from "../../types/models";
import { formatAtsSource, formatRelativeTime } from "../../utils/format";

type TriageTab = "dismissed" | "muted";

interface TriageManagementModalProps {
    open: boolean;
    hideDismissed: boolean;
    hideMuted: boolean;
    onClose: () => void;
    onToggleHideDismissed: () => void;
    onToggleHideMuted: () => void;
    onSyncCounts: (counts: { dismissedCount: number; mutedCount: number }) => void;
    onTriageMutated: (counts: { dismissedCount?: number; mutedCount?: number }) => void;
}

function DismissedRolesList({
    items,
    loading,
    loadingMore,
    hasMore,
    busyUuid,
    onRestore,
    onLoadMore,
}: Readonly<{
    items: ReadonlyArray<DismissedJob>;
    loading: boolean;
    loadingMore: boolean;
    hasMore: boolean;
    busyUuid: string | null;
    onRestore: (item: DismissedJob) => void;
    onLoadMore: () => void;
}>) {
    if (loading) {
        return (
            <div className="flex items-center justify-center py-12 text-sm text-zinc-400">
                <Loader2 className="mr-2 h-4 w-4 animate-spin text-violet-400" />
                Loading hidden roles...
            </div>
        );
    }

    if (items.length === 0) {
        return (
            <div className="rounded-xl border border-zinc-800/80 bg-zinc-900/40 px-5 py-10 text-center">
                <EyeOff className="mx-auto h-5 w-5 text-zinc-500" />
                <p className="mt-2.5 text-sm font-medium text-zinc-200">No hidden roles</p>
                <p className="mt-1 text-xs text-zinc-400">
                    Use the Hide button on any Job Radar card to remove irrelevant roles from your
                    feed.
                </p>
            </div>
        );
    }

    return (
        <div className="space-y-2.5">
            {items.map((item) => {
                const isBusy = busyUuid === item.uuid;
                const hiddenAgo = formatRelativeTime(item.created_at);
                return (
                    <div
                        key={item.uuid}
                        className="flex items-center justify-between gap-3 rounded-xl border border-zinc-800/80 bg-zinc-900/55 px-4 py-3"
                    >
                        <div className="min-w-0 flex-1">
                            <p className="truncate text-sm font-medium text-zinc-100">
                                {item.job_title}
                            </p>
                            <div className="mt-0.5 flex flex-wrap items-center gap-x-2.5 gap-y-0.5 text-xs text-zinc-400">
                                <span className="inline-flex items-center gap-1">
                                    <Building2 className="h-3 w-3 text-zinc-500" />
                                    {item.company_name}
                                </span>
                                {item.ats_source && (
                                    <span className="text-zinc-500">
                                        {formatAtsSource(item.ats_source)}
                                    </span>
                                )}
                                {hiddenAgo && (
                                    <span className="text-zinc-500">Hidden {hiddenAgo}</span>
                                )}
                            </div>
                        </div>
                        <button
                            type="button"
                            disabled={isBusy}
                            onClick={() => onRestore(item)}
                            className="inline-flex shrink-0 items-center gap-1.5 rounded-lg border border-zinc-700 bg-zinc-800/80 px-3 py-1.5 text-xs font-medium text-zinc-200 transition hover:border-violet-500/40 hover:bg-violet-500/15 hover:text-violet-200 disabled:opacity-50"
                        >
                            {isBusy ? (
                                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                            ) : (
                                <RotateCcw className="h-3.5 w-3.5" />
                            )}
                            Restore
                        </button>
                    </div>
                );
            })}

            {hasMore && (
                <div className="pt-1 text-center">
                    <button
                        type="button"
                        disabled={loadingMore}
                        onClick={onLoadMore}
                        className="inline-flex items-center gap-1.5 rounded-xl border border-zinc-700 bg-zinc-900 px-4 py-2 text-xs font-medium text-zinc-200 transition hover:border-zinc-600 hover:bg-zinc-800 disabled:opacity-50"
                    >
                        {loadingMore && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
                        Load more hidden roles
                    </button>
                </div>
            )}
        </div>
    );
}

function MutedCompaniesBody({
    items,
    loading,
    loadingMore,
    hasMore,
    busyUuid,
    onUnmute,
    onLoadMore,
}: Readonly<{
    items: ReadonlyArray<MutedCompany>;
    loading: boolean;
    loadingMore: boolean;
    hasMore: boolean;
    busyUuid: string | null;
    onUnmute: (item: MutedCompany) => void;
    onLoadMore: () => void;
}>) {
    if (loading) {
        return (
            <div className="flex items-center justify-center py-10 text-sm text-zinc-400">
                <Loader2 className="mr-2 h-4 w-4 animate-spin text-violet-400" />
                Loading muted companies...
            </div>
        );
    }

    if (items.length === 0) {
        return (
            <div className="rounded-xl border border-zinc-800/80 bg-zinc-900/40 px-5 py-10 text-center">
                <Ban className="mx-auto h-5 w-5 text-zinc-500" />
                <p className="mt-2.5 text-sm font-medium text-zinc-200">No muted companies</p>
                <p className="mt-1 text-xs text-zinc-400">
                    Muted companies are automatically hidden across current and future collector
                    syncs.
                </p>
            </div>
        );
    }

    return (
        <div className="space-y-2.5">
            {items.map((item) => {
                const isBusy = busyUuid === item.uuid;
                const mutedAgo = formatRelativeTime(item.created_at);
                return (
                    <div
                        key={item.uuid}
                        className="flex items-center justify-between gap-3 rounded-xl border border-zinc-800/80 bg-zinc-900/55 px-4 py-3"
                    >
                        <div className="min-w-0 flex-1">
                            <p className="truncate text-sm font-medium text-zinc-100">
                                {item.company_name_display}
                            </p>
                            {mutedAgo && (
                                <p className="mt-0.5 text-xs text-zinc-500">Muted {mutedAgo}</p>
                            )}
                        </div>
                        <button
                            type="button"
                            disabled={isBusy}
                            onClick={() => onUnmute(item)}
                            className="inline-flex shrink-0 items-center gap-1.5 rounded-lg border border-zinc-700 bg-zinc-800/80 px-3 py-1.5 text-xs font-medium text-zinc-200 transition hover:border-violet-500/40 hover:bg-violet-500/15 hover:text-violet-200 disabled:opacity-50"
                        >
                            {isBusy ? (
                                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                            ) : (
                                <RotateCcw className="h-3.5 w-3.5" />
                            )}
                            Unmute
                        </button>
                    </div>
                );
            })}

            {hasMore && (
                <div className="pt-1 text-center">
                    <button
                        type="button"
                        disabled={loadingMore}
                        onClick={onLoadMore}
                        className="inline-flex items-center gap-1.5 rounded-xl border border-zinc-700 bg-zinc-900 px-4 py-2 text-xs font-medium text-zinc-200 transition hover:border-zinc-600 hover:bg-zinc-800 disabled:opacity-50"
                    >
                        {loadingMore && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
                        Load more muted companies
                    </button>
                </div>
            )}
        </div>
    );
}

function MutedCompaniesList({
    items,
    loading,
    loadingMore,
    hasMore,
    busyUuid,
    companyInput,
    mutingCompany,
    onCompanyInputChange,
    onMuteSubmit,
    onUnmute,
    onLoadMore,
}: Readonly<{
    items: ReadonlyArray<MutedCompany>;
    loading: boolean;
    loadingMore: boolean;
    hasMore: boolean;
    busyUuid: string | null;
    companyInput: string;
    mutingCompany: boolean;
    onCompanyInputChange: (value: string) => void;
    onMuteSubmit: (event: SyntheticEvent<HTMLFormElement>) => void;
    onUnmute: (item: MutedCompany) => void;
    onLoadMore: () => void;
}>) {
    return (
        <div className="space-y-4">
            <form onSubmit={onMuteSubmit} className="flex gap-2">
                <input
                    type="text"
                    value={companyInput}
                    onChange={(e) => onCompanyInputChange(e.target.value)}
                    placeholder="Mute a company or agency (e.g. Acme Staffing)..."
                    aria-label="Company name to mute"
                    maxLength={180}
                    className="h-9 min-w-0 flex-1 rounded-xl border border-zinc-800 bg-zinc-950/80 px-3 text-sm text-zinc-100 placeholder:text-zinc-500 focus:border-violet-500 focus:outline-none focus:ring-2 focus:ring-violet-500/25"
                />
                <button
                    type="submit"
                    disabled={mutingCompany || !companyInput.trim()}
                    className="inline-flex h-9 shrink-0 items-center gap-1.5 rounded-xl bg-violet-600 px-3.5 text-xs font-medium text-white transition hover:bg-violet-500 disabled:opacity-50"
                >
                    {mutingCompany ? (
                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    ) : (
                        <Plus className="h-3.5 w-3.5" />
                    )}
                    Mute
                </button>
            </form>

            <MutedCompaniesBody
                items={items}
                loading={loading}
                loadingMore={loadingMore}
                hasMore={hasMore}
                busyUuid={busyUuid}
                onUnmute={onUnmute}
                onLoadMore={onLoadMore}
            />
        </div>
    );
}

export function TriageManagementModal({
    open,
    hideDismissed,
    hideMuted,
    onClose,
    onToggleHideDismissed,
    onToggleHideMuted,
    onSyncCounts,
    onTriageMutated,
}: Readonly<TriageManagementModalProps>) {
    const [activeTab, setActiveTab] = useState<TriageTab>("dismissed");
    const [dismissed, setDismissed] = useState<DismissedJob[]>([]);
    const [dismissedCount, setDismissedCount] = useState(0);
    const [dismissedPage, setDismissedPage] = useState(1);
    const [dismissedHasMore, setDismissedHasMore] = useState(false);

    const [muted, setMuted] = useState<MutedCompany[]>([]);
    const [mutedCount, setMutedCount] = useState(0);
    const [mutedPage, setMutedPage] = useState(1);
    const [mutedHasMore, setMutedHasMore] = useState(false);

    const [loading, setLoading] = useState(false);
    const [loadingMore, setLoadingMore] = useState(false);
    const [busyUuid, setBusyUuid] = useState<string | null>(null);
    const [companyInput, setCompanyInput] = useState("");
    const [mutingCompany, setMutingCompany] = useState(false);
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        if (!open) return;
        let cancelled = false;
        async function fetchInitialLists() {
            setLoading(true);
            setError(null);
            try {
                const [dismissedRes, mutedRes] = await Promise.all([
                    vektrynApi.listDismissedJobs(1),
                    vektrynApi.listMutedCompanies(1),
                ]);
                if (cancelled) return;
                setDismissed(dismissedRes.results);
                setDismissedCount(dismissedRes.count);
                setDismissedPage(1);
                setDismissedHasMore(Boolean(dismissedRes.next));

                setMuted(mutedRes.results);
                setMutedCount(mutedRes.count);
                setMutedPage(1);
                setMutedHasMore(Boolean(mutedRes.next));
                onSyncCounts({
                    dismissedCount: dismissedRes.count,
                    mutedCount: mutedRes.count,
                });
            } catch (err) {
                if (!cancelled) {
                    setError(err instanceof Error ? err.message : "Failed to load triage lists");
                }
            } finally {
                if (!cancelled) {
                    setLoading(false);
                }
            }
        }
        void fetchInitialLists();
        return () => {
            cancelled = true;
        };
    }, [open, onSyncCounts]);

    useEffect(() => {
        if (!open) return;
        function handleKeyDown(event: KeyboardEvent) {
            if (event.key === "Escape") {
                onClose();
            }
        }
        window.addEventListener("keydown", handleKeyDown);
        return () => window.removeEventListener("keydown", handleKeyDown);
    }, [open, onClose]);

    if (!open) {
        return null;
    }

    async function handleLoadMoreDismissed() {
        const nextPage = dismissedPage + 1;
        setLoadingMore(true);
        setError(null);
        try {
            const res = await vektrynApi.listDismissedJobs(nextPage);
            setDismissed((prev) => [...prev, ...res.results]);
            setDismissedCount(res.count);
            setDismissedPage(nextPage);
            setDismissedHasMore(Boolean(res.next));
        } catch (err) {
            setError(err instanceof Error ? err.message : "Failed to load more hidden roles");
        } finally {
            setLoadingMore(false);
        }
    }

    async function handleLoadMoreMuted() {
        const nextPage = mutedPage + 1;
        setLoadingMore(true);
        setError(null);
        try {
            const res = await vektrynApi.listMutedCompanies(nextPage);
            setMuted((prev) => [...prev, ...res.results]);
            setMutedCount(res.count);
            setMutedPage(nextPage);
            setMutedHasMore(Boolean(res.next));
        } catch (err) {
            setError(err instanceof Error ? err.message : "Failed to load more muted companies");
        } finally {
            setLoadingMore(false);
        }
    }

    async function handleRestoreRole(item: DismissedJob) {
        setBusyUuid(item.uuid);
        setError(null);
        try {
            await vektrynApi.restoreDismissedJob(item.uuid);
            const nextCount = Math.max(0, dismissedCount - 1);
            setDismissed((prev) => prev.filter((row) => row.uuid !== item.uuid));
            setDismissedCount(nextCount);
            onTriageMutated({ dismissedCount: nextCount });
        } catch (err) {
            setError(err instanceof Error ? err.message : "Failed to restore role");
        } finally {
            setBusyUuid(null);
        }
    }

    async function handleUnmuteCompany(item: MutedCompany) {
        setBusyUuid(item.uuid);
        setError(null);
        try {
            await vektrynApi.unmuteCompany(item.uuid);
            const nextCount = Math.max(0, mutedCount - 1);
            setMuted((prev) => prev.filter((row) => row.uuid !== item.uuid));
            setMutedCount(nextCount);
            onTriageMutated({ mutedCount: nextCount });
        } catch (err) {
            setError(err instanceof Error ? err.message : "Failed to unmute company");
        } finally {
            setBusyUuid(null);
        }
    }

    async function handleMuteSubmit(event: SyntheticEvent<HTMLFormElement>) {
        event.preventDefault();
        const trimmed = companyInput.trim();
        if (!trimmed) return;
        setMutingCompany(true);
        setError(null);
        try {
            const created = await vektrynApi.muteCompany(trimmed);
            setCompanyInput("");
            const alreadyListed = muted.some((row) => row.uuid === created.uuid);
            if (!alreadyListed) {
                const nextCount = mutedCount + 1;
                setMuted((prev) => [created, ...prev]);
                setMutedCount(nextCount);
                onTriageMutated({ mutedCount: nextCount });
            } else {
                onTriageMutated({ mutedCount });
            }
        } catch (err) {
            setError(err instanceof Error ? err.message : "Failed to mute company");
        } finally {
            setMutingCompany(false);
        }
    }

    const modalContent = (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
            <button
                type="button"
                aria-label="Close Hidden and Muted manager"
                onClick={onClose}
                className="fixed inset-0 bg-zinc-950/75 backdrop-blur-sm"
            />
            <dialog
                open
                aria-label="Hidden roles and muted companies"
                className="relative z-10 m-0 flex max-h-[85vh] w-full max-w-xl flex-col overflow-hidden rounded-2xl border border-zinc-800 bg-zinc-950 text-zinc-100 shadow-2xl shadow-black/60"
            >
                <div className="flex items-center justify-between border-b border-zinc-800/90 px-6 py-4">
                    <div>
                        <h2 className="text-base font-semibold text-zinc-100">
                            Hidden &amp; Muted
                        </h2>
                        <p className="text-xs text-zinc-400">
                            Manage hidden job postings, muted companies, and feed visibility.
                        </p>
                    </div>
                    <button
                        type="button"
                        onClick={onClose}
                        aria-label="Close modal"
                        className="rounded-lg p-1.5 text-zinc-400 transition hover:bg-zinc-800 hover:text-zinc-100"
                    >
                        <X className="h-4 w-4" />
                    </button>
                </div>

                <div className="flex flex-wrap items-center gap-2 border-b border-zinc-800/70 bg-zinc-900/35 px-6 py-3">
                    <span className="text-[11px] font-medium uppercase tracking-wider text-zinc-500">
                        Feed visibility:
                    </span>
                    <button
                        type="button"
                        aria-pressed={hideDismissed}
                        onClick={onToggleHideDismissed}
                        className={`inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1 text-xs font-medium transition ${
                            hideDismissed
                                ? "border-violet-500/40 bg-violet-500/15 text-violet-200"
                                : "border-amber-500/40 bg-amber-500/15 text-amber-200"
                        }`}
                    >
                        <EyeOff className="h-3 w-3" />
                        {hideDismissed ? "Hiding dismissed roles" : "Showing dismissed roles"}
                    </button>
                    <button
                        type="button"
                        aria-pressed={hideMuted}
                        onClick={onToggleHideMuted}
                        className={`inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1 text-xs font-medium transition ${
                            hideMuted
                                ? "border-violet-500/40 bg-violet-500/15 text-violet-200"
                                : "border-amber-500/40 bg-amber-500/15 text-amber-200"
                        }`}
                    >
                        <Ban className="h-3 w-3" />
                        {hideMuted ? "Hiding muted companies" : "Showing muted companies"}
                    </button>
                </div>

                <div className="flex border-b border-zinc-800/80 px-6">
                    <button
                        type="button"
                        onClick={() => setActiveTab("dismissed")}
                        className={`-mb-px inline-flex items-center gap-2 border-b-2 px-3 py-3 text-xs font-semibold transition ${
                            activeTab === "dismissed"
                                ? "border-violet-400 text-violet-200"
                                : "border-transparent text-zinc-400 hover:text-zinc-200"
                        }`}
                    >
                        <EyeOff className="h-3.5 w-3.5" />
                        Hidden Roles
                        <span className="rounded-md bg-zinc-800 px-1.5 py-0.5 font-mono text-[11px] tabular-nums text-zinc-300">
                            {dismissedCount}
                        </span>
                    </button>
                    <button
                        type="button"
                        onClick={() => setActiveTab("muted")}
                        className={`-mb-px inline-flex items-center gap-2 border-b-2 px-3 py-3 text-xs font-semibold transition ${
                            activeTab === "muted"
                                ? "border-violet-400 text-violet-200"
                                : "border-transparent text-zinc-400 hover:text-zinc-200"
                        }`}
                    >
                        <Ban className="h-3.5 w-3.5" />
                        Muted Companies
                        <span className="rounded-md bg-zinc-800 px-1.5 py-0.5 font-mono text-[11px] tabular-nums text-zinc-300">
                            {mutedCount}
                        </span>
                    </button>
                </div>

                <div className="flex-1 overflow-y-auto px-6 py-4">
                    {error && (
                        <div className="mb-3 rounded-xl border border-red-500/30 bg-red-950/30 px-3.5 py-2.5 text-xs text-red-300">
                            {error}
                        </div>
                    )}

                    {activeTab === "dismissed" ? (
                        <DismissedRolesList
                            items={dismissed}
                            loading={loading}
                            loadingMore={loadingMore}
                            hasMore={dismissedHasMore}
                            busyUuid={busyUuid}
                            onRestore={(item) => void handleRestoreRole(item)}
                            onLoadMore={() => void handleLoadMoreDismissed()}
                        />
                    ) : (
                        <MutedCompaniesList
                            items={muted}
                            loading={loading}
                            loadingMore={loadingMore}
                            hasMore={mutedHasMore}
                            busyUuid={busyUuid}
                            companyInput={companyInput}
                            mutingCompany={mutingCompany}
                            onCompanyInputChange={setCompanyInput}
                            onMuteSubmit={(e) => void handleMuteSubmit(e)}
                            onUnmute={(item) => void handleUnmuteCompany(item)}
                            onLoadMore={() => void handleLoadMoreMuted()}
                        />
                    )}
                </div>
            </dialog>
        </div>
    );

    return createPortal(modalContent, document.body);
}
