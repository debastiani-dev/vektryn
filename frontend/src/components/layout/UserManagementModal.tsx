import {
    AlertCircle,
    CheckCircle2,
    ChevronLeft,
    ChevronRight,
    Eye,
    EyeOff,
    Loader2,
    Pencil,
    RefreshCw,
    Search,
    Shield,
    UserCheck,
    UserPlus,
    Users,
    UserX,
    X,
} from "lucide-react";
import { type SubmitEvent, useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { ApiError, vektrynApi } from "../../api/client";
import type {
    CopilotTone,
    CurrentUser,
    PreferredCurrency,
    StaffManagedUser,
} from "../../types/models";
import { formatRelativeTime } from "../../utils/format";
import { Tooltip } from "../ui/Tooltip";

interface UserManagementModalProps {
    open: boolean;
    currentUser: CurrentUser;
    onClose: () => void;
}

type BooleanFilterValue = "" | "true" | "false";

const CURRENCY_OPTIONS: PreferredCurrency[] = ["USD", "BRL", "EUR", "GBP"];
const TONE_OPTIONS: CopilotTone[] = [
    "balanced",
    "concise",
    "executive",
    "technical",
    "conversational",
];

function replaceUserInList(
    list: StaffManagedUser[],
    updated: StaffManagedUser,
): StaffManagedUser[] {
    return list.map((u) => (u.id === updated.id ? updated : u));
}

function extractFirstError(err: unknown, fallback: string): string {
    if (err instanceof ApiError) {
        if (err.detail) return err.detail;
        const firstField = Object.values(err.fieldErrors)[0];
        if (firstField?.length) return firstField[0];
    }
    return fallback;
}

function CreateUserPanel({
    onCreated,
    onCancel,
}: Readonly<{
    onCreated: (created: StaffManagedUser) => void;
    onCancel: () => void;
}>) {
    const [username, setUsername] = useState("");
    const [email, setEmail] = useState("");
    const [displayName, setDisplayName] = useState("");
    const [password, setPassword] = useState("");
    const [showPassword, setShowPassword] = useState(false);
    const [isStaff, setIsStaff] = useState(false);
    const [submitting, setSubmitting] = useState(false);
    const [fieldErrors, setFieldErrors] = useState<Record<string, string[]>>({});
    const [generalError, setGeneralError] = useState<string | null>(null);

    async function handleSubmit(event: SubmitEvent<HTMLFormElement>) {
        event.preventDefault();
        setFieldErrors({});
        setGeneralError(null);
        setSubmitting(true);
        try {
            const created = await vektrynApi.createUser({
                username: username.trim(),
                email: email.trim(),
                password,
                is_staff: isStaff,
                profile: displayName.trim() ? { display_name: displayName.trim() } : undefined,
            });
            setPassword("");
            onCreated(created);
        } catch (err) {
            if (err instanceof ApiError) {
                if (Object.keys(err.fieldErrors).length > 0) {
                    setFieldErrors(err.fieldErrors);
                } else {
                    setGeneralError(err.detail || "Unable to create user.");
                }
            } else {
                setGeneralError("Unable to create user.");
            }
        } finally {
            setSubmitting(false);
        }
    }

    return (
        <form
            onSubmit={(e) => void handleSubmit(e)}
            className="space-y-3 rounded-xl border border-violet-500/30 bg-violet-950/15 p-4"
        >
            <div className="flex items-center justify-between">
                <h3 className="text-xs font-semibold uppercase tracking-wider text-violet-200">
                    Create New User
                </h3>
                <button
                    type="button"
                    onClick={onCancel}
                    className="text-xs text-zinc-400 transition hover:text-zinc-200"
                >
                    Cancel
                </button>
            </div>

            {generalError && (
                <div
                    role="alert"
                    className="flex items-center gap-2 rounded-lg border border-red-500/35 bg-red-950/35 px-3 py-2 text-xs text-red-200"
                >
                    <AlertCircle className="h-3.5 w-3.5 shrink-0 text-red-400" />
                    <span>{generalError}</span>
                </div>
            )}

            <div className="grid gap-3 sm:grid-cols-2">
                <div className="space-y-1">
                    <label
                        htmlFor="create-user-username"
                        className="block text-[11px] font-medium uppercase tracking-wider text-zinc-400"
                    >
                        Username *
                    </label>
                    <input
                        id="create-user-username"
                        type="text"
                        required
                        value={username}
                        disabled={submitting}
                        onChange={(e) => setUsername(e.target.value)}
                        placeholder="jdoe"
                        className="w-full rounded-lg border border-zinc-800 bg-zinc-950 px-3 py-2 text-xs text-zinc-100 focus:border-violet-500 focus:outline-none"
                    />
                    {fieldErrors.username?.map((msg) => (
                        <p key={msg} className="text-[11px] text-red-300">
                            {msg}
                        </p>
                    ))}
                </div>

                <div className="space-y-1">
                    <label
                        htmlFor="create-user-email"
                        className="block text-[11px] font-medium uppercase tracking-wider text-zinc-400"
                    >
                        Email
                    </label>
                    <input
                        id="create-user-email"
                        type="email"
                        value={email}
                        disabled={submitting}
                        onChange={(e) => setEmail(e.target.value)}
                        placeholder="jane@example.com"
                        className="w-full rounded-lg border border-zinc-800 bg-zinc-950 px-3 py-2 text-xs text-zinc-100 focus:border-violet-500 focus:outline-none"
                    />
                    {fieldErrors.email?.map((msg) => (
                        <p key={msg} className="text-[11px] text-red-300">
                            {msg}
                        </p>
                    ))}
                </div>

                <div className="space-y-1">
                    <label
                        htmlFor="create-user-display-name"
                        className="block text-[11px] font-medium uppercase tracking-wider text-zinc-400"
                    >
                        Display Name
                    </label>
                    <input
                        id="create-user-display-name"
                        type="text"
                        value={displayName}
                        disabled={submitting}
                        onChange={(e) => setDisplayName(e.target.value)}
                        placeholder="Jane Doe"
                        className="w-full rounded-lg border border-zinc-800 bg-zinc-950 px-3 py-2 text-xs text-zinc-100 focus:border-violet-500 focus:outline-none"
                    />
                </div>

                <div className="space-y-1">
                    <label
                        htmlFor="create-user-password"
                        className="block text-[11px] font-medium uppercase tracking-wider text-zinc-400"
                    >
                        Initial Password *
                    </label>
                    <div className="relative">
                        <input
                            id="create-user-password"
                            type={showPassword ? "text" : "password"}
                            required
                            autoComplete="new-password"
                            value={password}
                            disabled={submitting}
                            onChange={(e) => setPassword(e.target.value)}
                            placeholder="At least 8 characters"
                            className="w-full rounded-lg border border-zinc-800 bg-zinc-950 py-2 pr-9 pl-3 text-xs text-zinc-100 focus:border-violet-500 focus:outline-none"
                        />
                        <button
                            type="button"
                            onClick={() => setShowPassword((prev) => !prev)}
                            aria-label={showPassword ? "Hide password" : "Show password"}
                            className="absolute inset-y-0 right-2 inline-flex items-center px-1 text-zinc-500 hover:text-zinc-200"
                        >
                            {showPassword ? (
                                <EyeOff className="h-3.5 w-3.5" />
                            ) : (
                                <Eye className="h-3.5 w-3.5" />
                            )}
                        </button>
                    </div>
                    {fieldErrors.password?.map((msg) => (
                        <p key={msg} className="text-[11px] text-red-300">
                            {msg}
                        </p>
                    ))}
                </div>
            </div>

            <div className="flex flex-wrap items-center justify-between gap-3 pt-1">
                <label className="inline-flex items-center gap-2 text-xs text-zinc-300">
                    <input
                        type="checkbox"
                        checked={isStaff}
                        disabled={submitting}
                        onChange={(e) => setIsStaff(e.target.checked)}
                        className="h-3.5 w-3.5 rounded border-zinc-700 bg-zinc-900 accent-violet-500"
                    />
                    <span>Grant Staff privileges</span>
                </label>

                <button
                    type="submit"
                    disabled={submitting}
                    className="inline-flex items-center gap-1.5 rounded-lg bg-violet-600 px-3.5 py-1.5 text-xs font-medium text-white transition hover:bg-violet-500 disabled:opacity-60"
                >
                    {submitting ? (
                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    ) : (
                        <UserPlus className="h-3.5 w-3.5" />
                    )}
                    {submitting ? "Creating..." : "Create User"}
                </button>
            </div>
        </form>
    );
}

interface EditUserPanelProps {
    target: StaffManagedUser;
    isSelf: boolean;
    onSaved: (updated: StaffManagedUser) => void;
    onCancel: () => void;
}

function EditUserPanel({ target, isSelf, onSaved, onCancel }: Readonly<EditUserPanelProps>) {
    const [email, setEmail] = useState(target.email);
    const [displayName, setDisplayName] = useState(target.profile.display_name);
    const [timezone, setTimezone] = useState(target.profile.timezone);
    const [currency, setCurrency] = useState<PreferredCurrency>(target.profile.preferred_currency);
    const [tone, setTone] = useState<CopilotTone>(target.profile.default_copilot_tone);
    const [isStaff, setIsStaff] = useState(target.is_staff);
    const [saving, setSaving] = useState(false);
    const [error, setError] = useState<string | null>(null);

    async function handleSubmit(event: SubmitEvent<HTMLFormElement>) {
        event.preventDefault();
        setError(null);
        setSaving(true);
        try {
            const updated = await vektrynApi.updateUser(target.id, {
                email: email.trim(),
                is_staff: isSelf ? undefined : isStaff,
                profile: {
                    display_name: displayName.trim(),
                    timezone: timezone.trim(),
                    preferred_currency: currency,
                    default_copilot_tone: tone,
                },
            });
            onSaved(updated);
        } catch (err) {
            setError(extractFirstError(err, "Unable to update user."));
        } finally {
            setSaving(false);
        }
    }

    return (
        <form
            onSubmit={(e) => void handleSubmit(e)}
            className="mt-3 space-y-3 border-t border-zinc-800/80 pt-3"
        >
            {error && (
                <div
                    role="alert"
                    className="flex items-center gap-2 rounded-lg border border-red-500/35 bg-red-950/35 px-3 py-2 text-xs text-red-200"
                >
                    <AlertCircle className="h-3.5 w-3.5 shrink-0 text-red-400" />
                    <span>{error}</span>
                </div>
            )}

            <div className="grid gap-3 sm:grid-cols-3">
                <div className="space-y-1">
                    <label
                        htmlFor={`edit-display-${target.id}`}
                        className="block text-[11px] text-zinc-400"
                    >
                        Display Name
                    </label>
                    <input
                        id={`edit-display-${target.id}`}
                        type="text"
                        value={displayName}
                        disabled={saving}
                        onChange={(e) => setDisplayName(e.target.value)}
                        className="w-full rounded-lg border border-zinc-800 bg-zinc-950 px-2.5 py-1.5 text-xs text-zinc-100 focus:border-violet-500 focus:outline-none"
                    />
                </div>
                <div className="space-y-1">
                    <label
                        htmlFor={`edit-email-${target.id}`}
                        className="block text-[11px] text-zinc-400"
                    >
                        Email
                    </label>
                    <input
                        id={`edit-email-${target.id}`}
                        type="email"
                        value={email}
                        disabled={saving}
                        onChange={(e) => setEmail(e.target.value)}
                        className="w-full rounded-lg border border-zinc-800 bg-zinc-950 px-2.5 py-1.5 text-xs text-zinc-100 focus:border-violet-500 focus:outline-none"
                    />
                </div>
                <div className="space-y-1">
                    <label
                        htmlFor={`edit-tz-${target.id}`}
                        className="block text-[11px] text-zinc-400"
                    >
                        Timezone (IANA)
                    </label>
                    <input
                        id={`edit-tz-${target.id}`}
                        type="text"
                        value={timezone}
                        disabled={saving}
                        onChange={(e) => setTimezone(e.target.value)}
                        className="w-full rounded-lg border border-zinc-800 bg-zinc-950 px-2.5 py-1.5 text-xs text-zinc-100 focus:border-violet-500 focus:outline-none"
                    />
                </div>
                <div className="space-y-1">
                    <label
                        htmlFor={`edit-cur-${target.id}`}
                        className="block text-[11px] text-zinc-400"
                    >
                        Currency
                    </label>
                    <select
                        id={`edit-cur-${target.id}`}
                        value={currency}
                        disabled={saving}
                        onChange={(e) => setCurrency(e.target.value as PreferredCurrency)}
                        className="w-full rounded-lg border border-zinc-800 bg-zinc-950 px-2.5 py-1.5 text-xs text-zinc-100 focus:border-violet-500 focus:outline-none"
                    >
                        {CURRENCY_OPTIONS.map((cur) => (
                            <option key={cur} value={cur}>
                                {cur}
                            </option>
                        ))}
                    </select>
                </div>
                <div className="space-y-1">
                    <label
                        htmlFor={`edit-tone-${target.id}`}
                        className="block text-[11px] text-zinc-400"
                    >
                        Copilot Tone
                    </label>
                    <select
                        id={`edit-tone-${target.id}`}
                        value={tone}
                        disabled={saving}
                        onChange={(e) => setTone(e.target.value as CopilotTone)}
                        className="w-full rounded-lg border border-zinc-800 bg-zinc-950 px-2.5 py-1.5 text-xs text-zinc-100 focus:border-violet-500 focus:outline-none"
                    >
                        {TONE_OPTIONS.map((opt) => (
                            <option key={opt} value={opt}>
                                {opt}
                            </option>
                        ))}
                    </select>
                </div>
                <div className="flex items-end pb-1">
                    <Tooltip
                        content={
                            isSelf
                                ? "You cannot remove your own staff privileges."
                                : "Allow access to staff tools and user management."
                        }
                    >
                        <label className="inline-flex items-center gap-2 text-xs text-zinc-300">
                            <input
                                type="checkbox"
                                checked={isStaff}
                                disabled={saving || isSelf}
                                onChange={(e) => setIsStaff(e.target.checked)}
                                className="h-3.5 w-3.5 rounded border-zinc-700 bg-zinc-900 accent-violet-500 disabled:opacity-50"
                            />
                            <span>Staff role</span>
                        </label>
                    </Tooltip>
                </div>
            </div>

            <div className="flex items-center justify-end gap-2">
                <button
                    type="button"
                    disabled={saving}
                    onClick={onCancel}
                    className="rounded-lg border border-zinc-800 bg-zinc-900 px-3 py-1.5 text-xs font-medium text-zinc-300 transition hover:bg-zinc-800"
                >
                    Cancel
                </button>
                <button
                    type="submit"
                    disabled={saving}
                    className="inline-flex items-center gap-1.5 rounded-lg bg-violet-600 px-3 py-1.5 text-xs font-medium text-white transition hover:bg-violet-500 disabled:opacity-60"
                >
                    {saving && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
                    Save Changes
                </button>
            </div>
        </form>
    );
}

interface StaffUserRowProps {
    item: StaffManagedUser;
    currentUser: CurrentUser;
    editing: boolean;
    busy: boolean;
    onStartEdit: () => void;
    onCancelEdit: () => void;
    onSaved: (updated: StaffManagedUser) => void;
    onToggleActive: (target: StaffManagedUser) => void;
}

function renderToggleIcon(busy: boolean, isActive: boolean) {
    if (busy) {
        return <Loader2 className="h-3.5 w-3.5 animate-spin" />;
    }
    if (isActive) {
        return <UserX className="h-3.5 w-3.5" />;
    }
    return <UserCheck className="h-3.5 w-3.5" />;
}

function getToggleDisabledReason(
    isSelf: boolean,
    blockedBySuperuser: boolean,
): string | null {
    if (isSelf) {
        return "You cannot deactivate your own account from user management.";
    }
    if (blockedBySuperuser) {
        return "Only a superuser can modify or deactivate a superuser account.";
    }
    return null;
}

function StaffUserRow({
    item,
    currentUser,
    editing,
    busy,
    onStartEdit,
    onCancelEdit,
    onSaved,
    onToggleActive,
}: Readonly<StaffUserRowProps>) {
    const isSelf = String(item.id) === currentUser.id;
    const blockedBySuperuser = item.is_superuser && !currentUser.is_superuser;
    const toggleDisabledReason = getToggleDisabledReason(isSelf, blockedBySuperuser);
    const editDisabledReason = blockedBySuperuser
        ? "Only a superuser can edit a superuser account."
        : null;
    const lastSeen = item.last_login ? formatRelativeTime(item.last_login) : "Never";

    return (
        <div className="rounded-xl border border-zinc-800/90 bg-zinc-900/45 p-3.5">
            <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="min-w-0 space-y-1">
                    <div className="flex flex-wrap items-center gap-2">
                        <span className="font-medium text-sm text-zinc-100">
                            {item.profile.display_name || item.username}
                        </span>
                        <span className="font-mono text-xs text-zinc-500">@{item.username}</span>
                        {isSelf && (
                            <span className="rounded-full bg-zinc-800 px-2 py-0.5 text-[10px] font-medium text-zinc-300">
                                You
                            </span>
                        )}
                        <span
                            className={`rounded-full px-2 py-0.5 text-[10px] font-medium ring-1 ${
                                item.is_active
                                    ? "bg-emerald-500/10 text-emerald-300 ring-emerald-500/30"
                                    : "bg-zinc-800 text-zinc-400 ring-zinc-700"
                            }`}
                        >
                            {item.is_active ? "Active" : "Inactive"}
                        </span>
                        {item.is_superuser && (
                            <span className="inline-flex items-center gap-1 rounded-full bg-amber-500/15 px-2 py-0.5 text-[10px] font-medium text-amber-300 ring-1 ring-amber-500/30">
                                <Shield className="h-2.5 w-2.5" />
                                Superuser
                            </span>
                        )}
                        {item.is_staff && !item.is_superuser && (
                            <span className="rounded-full bg-violet-500/15 px-2 py-0.5 text-[10px] font-medium text-violet-300 ring-1 ring-violet-500/30">
                                Staff
                            </span>
                        )}
                    </div>
                    <p className="text-xs text-zinc-400">
                        {item.email || "No email"} · {item.profile.timezone} · Last login:{" "}
                        {lastSeen}
                    </p>
                </div>

                <div className="flex items-center gap-2">
                    <Tooltip content={editDisabledReason ?? "Edit user details and preferences"}>
                        <button
                            type="button"
                            disabled={Boolean(editDisabledReason) || busy}
                            onClick={editing ? onCancelEdit : onStartEdit}
                            className="inline-flex items-center gap-1.5 rounded-lg border border-zinc-800 bg-zinc-900 px-2.5 py-1.5 text-xs font-medium text-zinc-300 transition hover:bg-zinc-800 hover:text-zinc-100 disabled:cursor-not-allowed disabled:opacity-45"
                        >
                            <Pencil className="h-3.5 w-3.5" />
                            Edit
                        </button>
                    </Tooltip>

                    <Tooltip
                        content={
                            toggleDisabledReason ??
                            (item.is_active
                                ? "Soft-deactivate account and clear active sessions"
                                : "Reactivate account")
                        }
                    >
                        <button
                            type="button"
                            disabled={Boolean(toggleDisabledReason) || busy}
                            onClick={() => onToggleActive(item)}
                            className={`inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-xs font-medium transition disabled:cursor-not-allowed disabled:opacity-45 ${
                                item.is_active
                                    ? "border-red-500/30 bg-red-500/10 text-red-200 hover:bg-red-500/20"
                                    : "border-emerald-500/30 bg-emerald-500/10 text-emerald-200 hover:bg-emerald-500/20"
                            }`}
                        >
                            {renderToggleIcon(busy, item.is_active)}
                            {item.is_active ? "Deactivate" : "Reactivate"}
                        </button>
                    </Tooltip>
                </div>
            </div>

            {editing && (
                <EditUserPanel
                    target={item}
                    isSelf={isSelf}
                    onSaved={onSaved}
                    onCancel={onCancelEdit}
                />
            )}
        </div>
    );
}

export function UserManagementModal({
    open,
    currentUser,
    onClose,
}: Readonly<UserManagementModalProps>) {
    const [users, setUsers] = useState<StaffManagedUser[]>([]);
    const [totalCount, setTotalCount] = useState(0);
    const [page, setPage] = useState(1);
    const [hasNext, setHasNext] = useState(false);
    const [hasPrev, setHasPrev] = useState(false);
    const [searchInput, setSearchInput] = useState("");
    const [debouncedSearch, setDebouncedSearch] = useState("");
    const [statusFilter, setStatusFilter] = useState<BooleanFilterValue>("");
    const [roleFilter, setRoleFilter] = useState<BooleanFilterValue>("");
    const [loading, setLoading] = useState(false);
    const [refreshTick, setRefreshTick] = useState(0);
    const [showCreate, setShowCreate] = useState(false);
    const [editingId, setEditingId] = useState<number | null>(null);
    const [busyUserId, setBusyUserId] = useState<number | null>(null);
    const [errorBanner, setErrorBanner] = useState<string | null>(null);
    const [statusBanner, setStatusBanner] = useState<string | null>(null);

    useEffect(() => {
        const timer = globalThis.setTimeout(() => {
            setDebouncedSearch(searchInput);
            setPage(1);
        }, 250);
        return () => globalThis.clearTimeout(timer);
    }, [searchInput]);

    useEffect(() => {
        if (!open) return;
        let active = true;
        vektrynApi
            .listUsers({
                search: debouncedSearch,
                is_active: statusFilter || undefined,
                is_staff: roleFilter || undefined,
                page,
            })
            .then((res) => {
                if (!active) return;
                setUsers(res.results);
                setTotalCount(res.count);
                setHasNext(Boolean(res.next));
                setHasPrev(Boolean(res.previous));
                setErrorBanner(null);
            })
            .catch((err) => {
                if (!active) return;
                setErrorBanner(extractFirstError(err, "Failed to load users."));
            })
            .finally(() => {
                if (active) setLoading(false);
            });
        return () => {
            active = false;
        };
    }, [open, debouncedSearch, statusFilter, roleFilter, page, refreshTick]);

    function triggerRefresh() {
        setLoading(true);
        setRefreshTick((tick) => tick + 1);
    }

    useEffect(() => {
        if (!open) return;
        function onKeyDown(event: KeyboardEvent) {
            if (event.key === "Escape") {
                onClose();
            }
        }
        globalThis.addEventListener("keydown", onKeyDown);
        return () => globalThis.removeEventListener("keydown", onKeyDown);
    }, [open, onClose]);

    function handleUserSaved(updated: StaffManagedUser) {
        setUsers((prev) => replaceUserInList(prev, updated));
        setEditingId(null);
        setStatusBanner(`Updated @${updated.username}.`);
    }

    async function handleToggleActive(target: StaffManagedUser) {
        setBusyUserId(target.id);
        setErrorBanner(null);
        setStatusBanner(null);
        try {
            const updated = target.is_active
                ? await vektrynApi.deactivateUser(target.id)
                : await vektrynApi.updateUser(target.id, { is_active: true });
            setUsers((prev) => replaceUserInList(prev, updated));
            setStatusBanner(
                updated.is_active
                    ? `Reactivated @${updated.username}.`
                    : `Deactivated @${updated.username} and cleared active sessions.`,
            );
        } catch (err) {
            setErrorBanner(extractFirstError(err, "Action failed."));
        } finally {
            setBusyUserId(null);
        }
    }

    if (!open) {
        return null;
    }

    const modalContent = (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
            <button
                type="button"
                tabIndex={-1}
                aria-label="Close user management modal backdrop"
                onClick={onClose}
                className="fixed inset-0 bg-black/75 backdrop-blur-sm"
            />
            <dialog
                open
                aria-labelledby="user-management-modal-title"
                className="relative z-10 m-0 flex max-h-[90vh] w-full max-w-4xl flex-col overflow-hidden rounded-2xl border border-zinc-800 bg-zinc-950 p-0 text-zinc-100 shadow-2xl ring-1 ring-inset ring-white/[0.05]"
            >
                <div className="flex items-start justify-between gap-4 border-b border-zinc-800/80 px-6 py-5">
                    <div className="flex items-center gap-3">
                        <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-violet-500/15 ring-1 ring-violet-500/35">
                            <Users className="h-5 w-5 text-violet-300" />
                        </div>
                        <div>
                            <h2
                                id="user-management-modal-title"
                                className="text-base font-semibold text-zinc-100"
                            >
                                User Management
                            </h2>
                            <p className="text-xs text-zinc-400">
                                {totalCount} {totalCount === 1 ? "account" : "accounts"} ·
                                Soft-deactivation preserves user history
                            </p>
                        </div>
                    </div>

                    <div className="flex items-center gap-2">
                        <button
                            type="button"
                            onClick={() => setShowCreate((prev) => !prev)}
                            className="inline-flex items-center gap-1.5 rounded-xl bg-violet-600 px-3.5 py-2 text-xs font-medium text-white shadow-sm shadow-violet-600/20 transition hover:bg-violet-500"
                        >
                            <UserPlus className="h-3.5 w-3.5" />
                            Create User
                        </button>
                        <button
                            type="button"
                            onClick={triggerRefresh}
                            aria-label="Refresh user list"
                            className="rounded-lg border border-zinc-800 bg-zinc-900 p-2 text-zinc-400 transition hover:bg-zinc-800 hover:text-zinc-100"
                        >
                            <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
                        </button>
                        <button
                            type="button"
                            onClick={onClose}
                            aria-label="Close user management modal"
                            className="rounded-lg p-1.5 text-zinc-400 transition hover:bg-zinc-900 hover:text-zinc-100"
                        >
                            <X className="h-4 w-4" />
                        </button>
                    </div>
                </div>

                <div className="flex flex-wrap items-center gap-3 border-b border-zinc-800/80 bg-zinc-950/90 px-6 py-3.5">
                    <div className="relative min-w-[220px] flex-1">
                        <Search className="pointer-events-none absolute top-1/2 left-3 h-3.5 w-3.5 -translate-y-1/2 text-zinc-500" />
                        <input
                            type="search"
                            value={searchInput}
                            onChange={(e) => setSearchInput(e.target.value)}
                            placeholder="Search username, email, or display name..."
                            className="w-full rounded-lg border border-zinc-800 bg-zinc-900/70 py-1.5 pr-3 pl-8 text-xs text-zinc-100 placeholder:text-zinc-500 focus:border-violet-500 focus:outline-none"
                        />
                    </div>

                    <select
                        aria-label="Filter by account status"
                        value={statusFilter}
                        onChange={(e) => {
                            setStatusFilter(e.target.value as BooleanFilterValue);
                            setPage(1);
                        }}
                        className="rounded-lg border border-zinc-800 bg-zinc-900/70 px-2.5 py-1.5 text-xs text-zinc-200 focus:border-violet-500 focus:outline-none"
                    >
                        <option value="">All statuses</option>
                        <option value="true">Active only</option>
                        <option value="false">Inactive only</option>
                    </select>

                    <select
                        aria-label="Filter by role"
                        value={roleFilter}
                        onChange={(e) => {
                            setRoleFilter(e.target.value as BooleanFilterValue);
                            setPage(1);
                        }}
                        className="rounded-lg border border-zinc-800 bg-zinc-900/70 px-2.5 py-1.5 text-xs text-zinc-200 focus:border-violet-500 focus:outline-none"
                    >
                        <option value="">All roles</option>
                        <option value="true">Staff only</option>
                        <option value="false">Standard users</option>
                    </select>
                </div>

                <div className="flex-1 space-y-3 overflow-y-auto px-6 py-4">
                    {statusBanner && (
                        <output className="flex items-center gap-2 rounded-xl border border-emerald-500/35 bg-emerald-950/30 px-3.5 py-2.5 text-xs text-emerald-200">
                            <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-400" />
                            <span>{statusBanner}</span>
                        </output>
                    )}

                    {errorBanner && (
                        <div
                            role="alert"
                            className="flex items-center gap-2 rounded-xl border border-red-500/35 bg-red-950/30 px-3.5 py-2.5 text-xs text-red-200"
                        >
                            <AlertCircle className="h-4 w-4 shrink-0 text-red-400" />
                            <span>{errorBanner}</span>
                        </div>
                    )}

                    {showCreate && (
                        <CreateUserPanel
                            onCreated={(created) => {
                                setShowCreate(false);
                                setStatusBanner(`Created user @${created.username}.`);
                                triggerRefresh();
                            }}
                            onCancel={() => setShowCreate(false)}
                        />
                    )}

                    {loading && users.length === 0 && (
                        <div className="flex items-center justify-center gap-2 py-12 text-xs text-zinc-400">
                            <Loader2 className="h-4 w-4 animate-spin text-violet-400" />
                            Loading users...
                        </div>
                    )}

                    {!loading && users.length === 0 && (
                        <div className="rounded-xl border border-dashed border-zinc-800 py-10 text-center text-xs text-zinc-500">
                            No users match your current filters.
                        </div>
                    )}

                    {users.length > 0 && (
                        <div className="space-y-2.5">
                            {users.map((item) => (
                                <StaffUserRow
                                    key={item.id}
                                    item={item}
                                    currentUser={currentUser}
                                    editing={editingId === item.id}
                                    busy={busyUserId === item.id}
                                    onStartEdit={() => setEditingId(item.id)}
                                    onCancelEdit={() => setEditingId(null)}
                                    onSaved={handleUserSaved}
                                    onToggleActive={(target) => void handleToggleActive(target)}
                                />
                            ))}
                        </div>
                    )}
                </div>

                {(hasPrev || hasNext) && (
                    <div className="flex items-center justify-between border-t border-zinc-800/80 px-6 py-3 text-xs text-zinc-400">
                        <span>Page {page}</span>
                        <div className="flex items-center gap-2">
                            <button
                                type="button"
                                disabled={!hasPrev || loading}
                                onClick={() => setPage((p) => Math.max(1, p - 1))}
                                className="inline-flex items-center gap-1 rounded-lg border border-zinc-800 bg-zinc-900 px-3 py-1.5 text-zinc-200 transition hover:bg-zinc-800 disabled:opacity-40"
                            >
                                <ChevronLeft className="h-3.5 w-3.5" />
                                Previous
                            </button>
                            <button
                                type="button"
                                disabled={!hasNext || loading}
                                onClick={() => setPage((p) => p + 1)}
                                className="inline-flex items-center gap-1 rounded-lg border border-zinc-800 bg-zinc-900 px-3 py-1.5 text-zinc-200 transition hover:bg-zinc-800 disabled:opacity-40"
                            >
                                Next
                                <ChevronRight className="h-3.5 w-3.5" />
                            </button>
                        </div>
                    </div>
                )}
            </dialog>
        </div>
    );

    return createPortal(modalContent, document.body);
}
