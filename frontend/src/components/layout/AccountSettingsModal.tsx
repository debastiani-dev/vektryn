import {
    AlertCircle,
    AlertTriangle,
    CheckCircle2,
    Eye,
    EyeOff,
    Globe,
    KeyRound,
    Link2,
    Loader2,
    ShieldCheck,
    UserCog,
    X,
} from "lucide-react";
import { type SubmitEvent, useCallback, useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { ApiError, vektrynApi } from "../../api/client";
import type {
    CopilotTone,
    CurrentUser,
    PreferredCurrency,
    UserProfileDetail,
} from "../../types/models";

interface AccountSettingsModalProps {
    open: boolean;
    user: CurrentUser;
    onClose: () => void;
    onProfileSaved: (profile: UserProfileDetail) => void;
    onAccountDeactivated: () => void;
}

type SettingsTab = "profile" | "security";

const CURRENCY_OPTIONS: { value: PreferredCurrency; label: string }[] = [
    { value: "USD", label: "USD — US Dollar" },
    { value: "BRL", label: "BRL — Brazilian Real" },
    { value: "EUR", label: "EUR — Euro" },
    { value: "GBP", label: "GBP — British Pound" },
];

const TONE_OPTIONS: { value: CopilotTone; label: string }[] = [
    { value: "balanced", label: "Balanced" },
    { value: "concise", label: "Concise" },
    { value: "executive", label: "Executive" },
    { value: "technical", label: "Technical" },
    { value: "conversational", label: "Conversational" },
];

const COMMON_TIMEZONES = [
    "UTC",
    "America/Sao_Paulo",
    "America/New_York",
    "America/Chicago",
    "America/Denver",
    "America/Los_Angeles",
    "America/Toronto",
    "America/Mexico_City",
    "America/Argentina/Buenos_Aires",
    "America/Bogota",
    "Europe/London",
    "Europe/Lisbon",
    "Europe/Madrid",
    "Europe/Berlin",
    "Europe/Amsterdam",
    "Europe/Paris",
    "Asia/Tokyo",
    "Asia/Singapore",
    "Australia/Sydney",
];

function FieldErrorList({ errors }: Readonly<{ errors?: string[] }>) {
    if (!errors?.length) {
        return null;
    }
    return (
        <ul className="space-y-1 text-xs text-red-300">
            {errors.map((msg) => (
                <li key={msg} className="flex items-start gap-1.5">
                    <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-red-400" />
                    <span>{msg}</span>
                </li>
            ))}
        </ul>
    );
}

interface PasswordInputFieldProps {
    id: string;
    label: string;
    autoComplete: string;
    value: string;
    visible: boolean;
    disabled: boolean;
    errors?: string[];
    placeholder: string;
    onChange: (value: string) => void;
    onToggleVisibility: () => void;
}

function PasswordInputField({
    id,
    label,
    autoComplete,
    value,
    visible,
    disabled,
    errors,
    placeholder,
    onChange,
    onToggleVisibility,
}: Readonly<PasswordInputFieldProps>) {
    const hasError = Boolean(errors?.length);
    return (
        <div className="space-y-1.5">
            <label
                htmlFor={id}
                className="block text-xs font-medium uppercase tracking-wider text-zinc-400"
            >
                {label}
            </label>
            <div className="relative">
                <input
                    id={id}
                    type={visible ? "text" : "password"}
                    autoComplete={autoComplete}
                    value={value}
                    disabled={disabled}
                    onChange={(e) => onChange(e.target.value)}
                    placeholder={placeholder}
                    aria-invalid={hasError}
                    className={`w-full rounded-xl border bg-zinc-950/90 py-2.5 pr-10 pl-3.5 text-sm text-zinc-100 placeholder:text-zinc-600 transition focus:outline-none focus:ring-2 disabled:opacity-60 ${
                        hasError
                            ? "border-red-500/60 focus:border-red-400 focus:ring-red-500/20"
                            : "border-zinc-800 focus:border-violet-500 focus:ring-violet-500/25"
                    }`}
                />
                <button
                    type="button"
                    onClick={onToggleVisibility}
                    disabled={disabled}
                    aria-label={visible ? `Hide ${label.toLowerCase()}` : `Show ${label.toLowerCase()}`}
                    className="absolute inset-y-0 right-2 inline-flex items-center px-1.5 text-zinc-500 transition hover:text-zinc-200 focus-visible:outline-none focus-visible:text-violet-300"
                >
                    {visible ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                </button>
            </div>
            <FieldErrorList errors={errors} />
        </div>
    );
}

interface ProfilePreferencesTabProps {
    user: CurrentUser;
    onProfileSaved: (profile: UserProfileDetail) => void;
}

function ProfilePreferencesTab({
    user,
    onProfileSaved,
}: Readonly<ProfilePreferencesTabProps>) {
    const [loading, setLoading] = useState(true);
    const [saving, setSaving] = useState(false);
    const [displayName, setDisplayName] = useState(user.profile?.display_name ?? "");
    const [email, setEmail] = useState(user.email ?? "");
    const [timezone, setTimezone] = useState(user.profile?.timezone ?? "UTC");
    const [currency, setCurrency] = useState<PreferredCurrency>(
        user.profile?.preferred_currency ?? "USD",
    );
    const [copilotTone, setCopilotTone] = useState<CopilotTone>(
        user.profile?.default_copilot_tone ?? "balanced",
    );
    const [linkedinUrl, setLinkedinUrl] = useState("");
    const [githubUrl, setGithubUrl] = useState("");
    const [portfolioUrl, setPortfolioUrl] = useState("");
    const [fieldErrors, setFieldErrors] = useState<Record<string, string[]>>({});
    const [generalError, setGeneralError] = useState<string | null>(null);
    const [savedBanner, setSavedBanner] = useState<string | null>(null);

    useEffect(() => {
        let active = true;
        vektrynApi
            .getUserProfile()
            .then((profile) => {
                if (!active) return;
                setDisplayName(profile.display_name);
                setEmail(profile.email);
                setTimezone(profile.timezone);
                setCurrency(profile.preferred_currency);
                setCopilotTone(profile.default_copilot_tone);
                setLinkedinUrl(profile.linkedin_url);
                setGithubUrl(profile.github_url);
                setPortfolioUrl(profile.portfolio_url);
            })
            .catch((err) => {
                if (!active) return;
                const detail = err instanceof ApiError ? err.detail : null;
                setGeneralError(detail || "Failed to load profile settings.");
            })
            .finally(() => {
                if (active) setLoading(false);
            });
        return () => {
            active = false;
        };
    }, []);

    function handleUseBrowserTimezone() {
        const detected = Intl.DateTimeFormat().resolvedOptions().timeZone;
        if (detected) {
            setTimezone(detected);
        }
    }

    async function handleSubmit(event: SubmitEvent<HTMLFormElement>) {
        event.preventDefault();
        setSaving(true);
        setFieldErrors({});
        setGeneralError(null);
        setSavedBanner(null);
        try {
            const updated = await vektrynApi.updateUserProfile({
                display_name: displayName.trim(),
                email: email.trim(),
                timezone: timezone.trim(),
                preferred_currency: currency,
                default_copilot_tone: copilotTone,
                linkedin_url: linkedinUrl.trim(),
                github_url: githubUrl.trim(),
                portfolio_url: portfolioUrl.trim(),
            });
            setDisplayName(updated.display_name);
            setEmail(updated.email);
            setTimezone(updated.timezone);
            setCurrency(updated.preferred_currency);
            setCopilotTone(updated.default_copilot_tone);
            setLinkedinUrl(updated.linkedin_url);
            setGithubUrl(updated.github_url);
            setPortfolioUrl(updated.portfolio_url);
            onProfileSaved(updated);
            setSavedBanner(
                "Profile and preferences saved. Future AI Copilot drafts will use your updated identity, links, and default tone.",
            );
        } catch (err) {
            if (err instanceof ApiError) {
                if (Object.keys(err.fieldErrors).length > 0) {
                    setFieldErrors(err.fieldErrors);
                } else {
                    setGeneralError(err.detail || "Unable to save profile settings.");
                }
            } else {
                setGeneralError("Unable to save profile settings.");
            }
        } finally {
            setSaving(false);
        }
    }

    if (loading) {
        return (
            <div className="flex items-center justify-center gap-2 py-12 text-xs text-zinc-400">
                <Loader2 className="h-4 w-4 animate-spin text-violet-400" />
                Loading profile settings...
            </div>
        );
    }

    return (
        <form onSubmit={(e) => void handleSubmit(e)} className="space-y-4">
            {savedBanner && (
                <output className="flex items-start gap-2.5 rounded-xl border border-emerald-500/35 bg-emerald-950/30 px-3.5 py-3 text-xs text-emerald-200">
                    <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald-400" />
                    <span>{savedBanner}</span>
                </output>
            )}

            {generalError && (
                <div
                    role="alert"
                    className="flex items-start gap-2.5 rounded-xl border border-red-500/35 bg-red-950/30 px-3.5 py-3 text-xs text-red-200"
                >
                    <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-red-400" />
                    <span>{generalError}</span>
                </div>
            )}

            <div className="grid gap-4 sm:grid-cols-2">
                <div className="space-y-1.5">
                    <label
                        htmlFor="profile-display-name"
                        className="block text-xs font-medium uppercase tracking-wider text-zinc-400"
                    >
                        Display Name
                    </label>
                    <input
                        id="profile-display-name"
                        type="text"
                        maxLength={120}
                        value={displayName}
                        disabled={saving}
                        onChange={(e) => setDisplayName(e.target.value)}
                        placeholder="Jane Doe"
                        className="w-full rounded-xl border border-zinc-800 bg-zinc-950/90 px-3.5 py-2 text-sm text-zinc-100 placeholder:text-zinc-600 focus:border-violet-500 focus:outline-none focus:ring-2 focus:ring-violet-500/25"
                    />
                    <FieldErrorList errors={fieldErrors.display_name} />
                </div>

                <div className="space-y-1.5">
                    <label
                        htmlFor="profile-email"
                        className="block text-xs font-medium uppercase tracking-wider text-zinc-400"
                    >
                        Email
                    </label>
                    <input
                        id="profile-email"
                        type="email"
                        maxLength={254}
                        value={email}
                        disabled={saving}
                        onChange={(e) => setEmail(e.target.value)}
                        placeholder="you@example.com"
                        className="w-full rounded-xl border border-zinc-800 bg-zinc-950/90 px-3.5 py-2 text-sm text-zinc-100 placeholder:text-zinc-600 focus:border-violet-500 focus:outline-none focus:ring-2 focus:ring-violet-500/25"
                    />
                    <FieldErrorList errors={fieldErrors.email} />
                </div>
            </div>

            <div className="grid gap-4 sm:grid-cols-3">
                <div className="space-y-1.5 sm:col-span-1">
                    <div className="flex items-center justify-between gap-1">
                        <label
                            htmlFor="profile-timezone"
                            className="block text-xs font-medium uppercase tracking-wider text-zinc-400"
                        >
                            Timezone
                        </label>
                        <button
                            type="button"
                            onClick={handleUseBrowserTimezone}
                            disabled={saving}
                            className="inline-flex items-center gap-1 text-[11px] font-medium text-violet-300 transition hover:text-violet-200"
                        >
                            <Globe className="h-3 w-3" />
                            Auto
                        </button>
                    </div>
                    <input
                        id="profile-timezone"
                        type="text"
                        list="vektryn-iana-timezones"
                        value={timezone}
                        disabled={saving}
                        onChange={(e) => setTimezone(e.target.value)}
                        placeholder="America/Sao_Paulo"
                        className="w-full rounded-xl border border-zinc-800 bg-zinc-950/90 px-3 py-2 text-xs text-zinc-100 placeholder:text-zinc-600 focus:border-violet-500 focus:outline-none focus:ring-2 focus:ring-violet-500/25"
                    />
                    <datalist id="vektryn-iana-timezones">
                        {COMMON_TIMEZONES.map((tz) => (
                            <option key={tz} value={tz} />
                        ))}
                    </datalist>
                    <FieldErrorList errors={fieldErrors.timezone} />
                </div>

                <div className="space-y-1.5">
                    <label
                        htmlFor="profile-currency"
                        className="block text-xs font-medium uppercase tracking-wider text-zinc-400"
                    >
                        Currency
                    </label>
                    <select
                        id="profile-currency"
                        value={currency}
                        disabled={saving}
                        onChange={(e) => setCurrency(e.target.value as PreferredCurrency)}
                        className="w-full rounded-xl border border-zinc-800 bg-zinc-950/90 px-3 py-2 text-xs text-zinc-100 focus:border-violet-500 focus:outline-none focus:ring-2 focus:ring-violet-500/25"
                    >
                        {CURRENCY_OPTIONS.map((opt) => (
                            <option key={opt.value} value={opt.value}>
                                {opt.label}
                            </option>
                        ))}
                    </select>
                    <FieldErrorList errors={fieldErrors.preferred_currency} />
                </div>

                <div className="space-y-1.5">
                    <label
                        htmlFor="profile-copilot-tone"
                        className="block text-xs font-medium uppercase tracking-wider text-zinc-400"
                    >
                        Copilot Tone
                    </label>
                    <select
                        id="profile-copilot-tone"
                        value={copilotTone}
                        disabled={saving}
                        onChange={(e) => setCopilotTone(e.target.value as CopilotTone)}
                        className="w-full rounded-xl border border-zinc-800 bg-zinc-950/90 px-3 py-2 text-xs text-zinc-100 focus:border-violet-500 focus:outline-none focus:ring-2 focus:ring-violet-500/25"
                    >
                        {TONE_OPTIONS.map((opt) => (
                            <option key={opt.value} value={opt.value}>
                                {opt.label}
                            </option>
                        ))}
                    </select>
                    <FieldErrorList errors={fieldErrors.default_copilot_tone} />
                </div>
            </div>

            <div className="space-y-3 rounded-xl border border-zinc-800/80 bg-zinc-900/40 p-3.5">
                <div className="flex items-center gap-2 text-xs font-medium text-zinc-300">
                    <Link2 className="h-3.5 w-3.5 text-violet-400" />
                    <span>Public Profile Links</span>
                    <span className="text-[11px] font-normal text-zinc-500">
                        (used to ground AI Copilot drafts)
                    </span>
                </div>

                <div className="space-y-3">
                    <div className="space-y-1">
                        <label
                            htmlFor="profile-linkedin"
                            className="block text-[11px] font-medium uppercase tracking-wider text-zinc-400"
                        >
                            LinkedIn URL
                        </label>
                        <input
                            id="profile-linkedin"
                            type="url"
                            maxLength={300}
                            value={linkedinUrl}
                            disabled={saving}
                            onChange={(e) => setLinkedinUrl(e.target.value)}
                            placeholder="https://linkedin.com/in/your-handle"
                            className="w-full rounded-lg border border-zinc-800 bg-zinc-950/90 px-3 py-2 text-xs text-zinc-100 placeholder:text-zinc-600 focus:border-violet-500 focus:outline-none"
                        />
                        <FieldErrorList errors={fieldErrors.linkedin_url} />
                    </div>

                    <div className="space-y-1">
                        <label
                            htmlFor="profile-github"
                            className="block text-[11px] font-medium uppercase tracking-wider text-zinc-400"
                        >
                            GitHub URL
                        </label>
                        <input
                            id="profile-github"
                            type="url"
                            maxLength={300}
                            value={githubUrl}
                            disabled={saving}
                            onChange={(e) => setGithubUrl(e.target.value)}
                            placeholder="https://github.com/your-handle"
                            className="w-full rounded-lg border border-zinc-800 bg-zinc-950/90 px-3 py-2 text-xs text-zinc-100 placeholder:text-zinc-600 focus:border-violet-500 focus:outline-none"
                        />
                        <FieldErrorList errors={fieldErrors.github_url} />
                    </div>

                    <div className="space-y-1">
                        <label
                            htmlFor="profile-portfolio"
                            className="block text-[11px] font-medium uppercase tracking-wider text-zinc-400"
                        >
                            Portfolio URL
                        </label>
                        <input
                            id="profile-portfolio"
                            type="url"
                            maxLength={300}
                            value={portfolioUrl}
                            disabled={saving}
                            onChange={(e) => setPortfolioUrl(e.target.value)}
                            placeholder="https://your-site.dev"
                            className="w-full rounded-lg border border-zinc-800 bg-zinc-950/90 px-3 py-2 text-xs text-zinc-100 placeholder:text-zinc-600 focus:border-violet-500 focus:outline-none"
                        />
                        <FieldErrorList errors={fieldErrors.portfolio_url} />
                    </div>
                </div>
            </div>

            <div className="flex justify-end pt-1">
                <button
                    type="submit"
                    disabled={saving}
                    className="inline-flex items-center gap-2 rounded-xl bg-violet-600 px-4 py-2 text-xs font-medium text-white shadow-sm shadow-violet-600/25 transition hover:bg-violet-500 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-500/70 disabled:cursor-not-allowed disabled:opacity-60"
                >
                    {saving ? (
                        <>
                            <Loader2 className="h-3.5 w-3.5 animate-spin" />
                            Saving...
                        </>
                    ) : (
                        "Save Profile"
                    )}
                </button>
            </div>
        </form>
    );
}

interface PasswordFieldErrors {
    current_password?: string[];
    new_password?: string[];
    confirm_password?: string[];
}

function validatePasswordDraft(
    currentPassword: string,
    newPassword: string,
    confirmPassword: string,
): PasswordFieldErrors {
    const errors: PasswordFieldErrors = {};
    if (!currentPassword) {
        errors.current_password = ["Enter your current password."];
    }
    if (!newPassword) {
        errors.new_password = ["Enter a new password."];
    } else if (newPassword.length < 8) {
        errors.new_password = ["Password must be at least 8 characters long."];
    } else if (currentPassword && newPassword === currentPassword) {
        errors.new_password = ["New password must be different from your current password."];
    }
    if (!confirmPassword) {
        errors.confirm_password = ["Confirm your new password."];
    } else if (newPassword && confirmPassword !== newPassword) {
        errors.confirm_password = ["New passwords do not match."];
    }
    return errors;
}

function ChangePasswordSection() {
    const [currentPassword, setCurrentPassword] = useState("");
    const [newPassword, setNewPassword] = useState("");
    const [confirmPassword, setConfirmPassword] = useState("");
    const [showCurrent, setShowCurrent] = useState(false);
    const [showNew, setShowNew] = useState(false);
    const [showConfirm, setShowConfirm] = useState(false);
    const [submitting, setSubmitting] = useState(false);
    const [fieldErrors, setFieldErrors] = useState<PasswordFieldErrors>({});
    const [generalError, setGeneralError] = useState<string | null>(null);
    const [successMessage, setSuccessMessage] = useState<string | null>(null);

    function resetSensitiveState() {
        setCurrentPassword("");
        setNewPassword("");
        setConfirmPassword("");
        setShowCurrent(false);
        setShowNew(false);
        setShowConfirm(false);
    }

    async function handleSubmit(event: SubmitEvent<HTMLFormElement>) {
        event.preventDefault();
        setGeneralError(null);
        setSuccessMessage(null);

        const clientErrors = validatePasswordDraft(currentPassword, newPassword, confirmPassword);
        if (Object.keys(clientErrors).length > 0) {
            setFieldErrors(clientErrors);
            return;
        }

        setFieldErrors({});
        setSubmitting(true);
        try {
            await vektrynApi.changePassword({
                current_password: currentPassword,
                new_password: newPassword,
                confirm_password: confirmPassword,
            });
            resetSensitiveState();
            setSuccessMessage(
                "Password updated. Your active session stays signed in and any other sessions have been signed out.",
            );
        } catch (err) {
            if (err instanceof ApiError) {
                const serverFields: PasswordFieldErrors = {
                    current_password: err.fieldErrors.current_password,
                    new_password: err.fieldErrors.new_password,
                    confirm_password: err.fieldErrors.confirm_password,
                };
                const hasFieldErrors = Boolean(
                    serverFields.current_password?.length ||
                        serverFields.new_password?.length ||
                        serverFields.confirm_password?.length,
                );
                if (hasFieldErrors) {
                    setFieldErrors(serverFields);
                } else {
                    setGeneralError(
                        err.detail || "Unable to update password. Check your inputs and try again.",
                    );
                }
            } else {
                setGeneralError("Unable to update password. Please try again.");
            }
        } finally {
            setSubmitting(false);
        }
    }

    return (
        <section className="space-y-4">
            <div className="flex items-center gap-2 text-xs font-medium uppercase tracking-wider text-zinc-400">
                <KeyRound className="h-3.5 w-3.5 text-violet-400" />
                <span>Change Password</span>
            </div>

            {successMessage && (
                <output className="flex items-start gap-2.5 rounded-xl border border-emerald-500/35 bg-emerald-950/30 px-3.5 py-3 text-xs text-emerald-200">
                    <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald-400" />
                    <span>{successMessage}</span>
                </output>
            )}

            {generalError && (
                <div
                    role="alert"
                    className="flex items-start gap-2.5 rounded-xl border border-red-500/35 bg-red-950/30 px-3.5 py-3 text-xs text-red-200"
                >
                    <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-red-400" />
                    <span>{generalError}</span>
                </div>
            )}

            <form onSubmit={(e) => void handleSubmit(e)} className="space-y-3.5">
                <PasswordInputField
                    id="account-current-password"
                    label="Current Password"
                    autoComplete="current-password"
                    value={currentPassword}
                    visible={showCurrent}
                    disabled={submitting}
                    errors={fieldErrors.current_password}
                    placeholder="Enter current password"
                    onChange={setCurrentPassword}
                    onToggleVisibility={() => setShowCurrent((prev) => !prev)}
                />

                <PasswordInputField
                    id="account-new-password"
                    label="New Password"
                    autoComplete="new-password"
                    value={newPassword}
                    visible={showNew}
                    disabled={submitting}
                    errors={fieldErrors.new_password}
                    placeholder="At least 8 characters"
                    onChange={setNewPassword}
                    onToggleVisibility={() => setShowNew((prev) => !prev)}
                />

                <PasswordInputField
                    id="account-confirm-password"
                    label="Confirm New Password"
                    autoComplete="new-password"
                    value={confirmPassword}
                    visible={showConfirm}
                    disabled={submitting}
                    errors={fieldErrors.confirm_password}
                    placeholder="Re-enter new password"
                    onChange={setConfirmPassword}
                    onToggleVisibility={() => setShowConfirm((prev) => !prev)}
                />

                <p className="rounded-xl border border-zinc-800/80 bg-zinc-900/50 px-3.5 py-2.5 text-[11px] leading-relaxed text-zinc-400">
                    Must be at least 8 characters, not too similar to your username or email, not a
                    common password, and not entirely numeric.
                </p>

                <div className="flex justify-end">
                    <button
                        type="submit"
                        disabled={submitting}
                        className="inline-flex items-center gap-2 rounded-xl bg-violet-600 px-4 py-2 text-xs font-medium text-white shadow-sm shadow-violet-600/25 transition hover:bg-violet-500 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-500/70 disabled:cursor-not-allowed disabled:opacity-60"
                    >
                        {submitting ? (
                            <>
                                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                                Updating...
                            </>
                        ) : (
                            "Update Password"
                        )}
                    </button>
                </div>
            </form>
        </section>
    );
}

function DeactivateAccountSection({
    onAccountDeactivated,
}: Readonly<{ onAccountDeactivated: () => void }>) {
    const [expanded, setExpanded] = useState(false);
    const [password, setPassword] = useState("");
    const [showPassword, setShowPassword] = useState(false);
    const [submitting, setSubmitting] = useState(false);
    const [passwordErrors, setPasswordErrors] = useState<string[] | undefined>(undefined);
    const [generalError, setGeneralError] = useState<string | null>(null);

    async function handleDeactivate(event: SubmitEvent<HTMLFormElement>) {
        event.preventDefault();
        setPasswordErrors(undefined);
        setGeneralError(null);
        if (!password) {
            setPasswordErrors(["Enter your current password to confirm deactivation."]);
            return;
        }
        setSubmitting(true);
        try {
            await vektrynApi.deactivateAccount(password);
            setPassword("");
            setShowPassword(false);
            onAccountDeactivated();
        } catch (err) {
            if (err instanceof ApiError) {
                if (err.fieldErrors.current_password?.length) {
                    setPasswordErrors(err.fieldErrors.current_password);
                } else {
                    setGeneralError(err.detail || "Unable to deactivate account.");
                }
            } else {
                setGeneralError("Unable to deactivate account.");
            }
        } finally {
            setSubmitting(false);
        }
    }

    return (
        <section className="space-y-3 rounded-xl border border-red-500/25 bg-red-950/15 p-4">
            <div className="flex items-start justify-between gap-3">
                <div className="space-y-1">
                    <div className="flex items-center gap-2 text-xs font-semibold text-red-200">
                        <AlertTriangle className="h-4 w-4 text-red-400" />
                        <span>Deactivate Account</span>
                    </div>
                    <p className="text-[11px] leading-relaxed text-zinc-400">
                        Signs out all active sessions and disables login. Your resumes, match
                        scores, leads, and notifications are preserved and a staff admin can
                        reactivate your account later.
                    </p>
                </div>
                {!expanded && (
                    <button
                        type="button"
                        onClick={() => setExpanded(true)}
                        className="shrink-0 rounded-lg border border-red-500/35 bg-red-500/10 px-3 py-1.5 text-xs font-medium text-red-200 transition hover:bg-red-500/20"
                    >
                        Deactivate...
                    </button>
                )}
            </div>

            {expanded && (
                <form
                    onSubmit={(e) => void handleDeactivate(e)}
                    className="space-y-3 border-t border-red-500/20 pt-3"
                >
                    {generalError && (
                        <div
                            role="alert"
                            className="flex items-start gap-2 rounded-lg border border-red-500/35 bg-red-950/40 px-3 py-2 text-xs text-red-200"
                        >
                            <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-red-400" />
                            <span>{generalError}</span>
                        </div>
                    )}

                    <PasswordInputField
                        id="deactivate-confirm-password"
                        label="Confirm Current Password"
                        autoComplete="current-password"
                        value={password}
                        visible={showPassword}
                        disabled={submitting}
                        errors={passwordErrors}
                        placeholder="Enter current password to deactivate"
                        onChange={setPassword}
                        onToggleVisibility={() => setShowPassword((prev) => !prev)}
                    />

                    <div className="flex items-center justify-end gap-2">
                        <button
                            type="button"
                            disabled={submitting}
                            onClick={() => {
                                setExpanded(false);
                                setPassword("");
                                setPasswordErrors(undefined);
                                setGeneralError(null);
                            }}
                            className="rounded-lg border border-zinc-800 bg-zinc-900 px-3 py-1.5 text-xs font-medium text-zinc-300 transition hover:bg-zinc-800"
                        >
                            Cancel
                        </button>
                        <button
                            type="submit"
                            disabled={submitting}
                            className="inline-flex items-center gap-1.5 rounded-lg bg-red-600 px-3.5 py-1.5 text-xs font-medium text-white transition hover:bg-red-500 disabled:cursor-not-allowed disabled:opacity-60"
                        >
                            {submitting ? (
                                <>
                                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                                    Deactivating...
                                </>
                            ) : (
                                "Confirm Deactivation"
                            )}
                        </button>
                    </div>
                </form>
            )}
        </section>
    );
}

export function AccountSettingsModal({
    open,
    user,
    onClose,
    onProfileSaved,
    onAccountDeactivated,
}: Readonly<AccountSettingsModalProps>) {
    const [activeTab, setActiveTab] = useState<SettingsTab>("profile");

    const handleClose = useCallback(() => {
        setActiveTab("profile");
        onClose();
    }, [onClose]);

    useEffect(() => {
        if (!open) {
            return;
        }
        function onKeyDown(event: KeyboardEvent) {
            if (event.key === "Escape") {
                handleClose();
            }
        }
        globalThis.addEventListener("keydown", onKeyDown);
        return () => globalThis.removeEventListener("keydown", onKeyDown);
    }, [open, handleClose]);

    if (!open) {
        return null;
    }

    const displayLabel = user.profile?.display_name || user.username;

    const modalContent = (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
            <button
                type="button"
                tabIndex={-1}
                aria-label="Close account settings modal backdrop"
                onClick={handleClose}
                className="fixed inset-0 bg-black/75 backdrop-blur-sm"
            />
            <dialog
                open
                aria-labelledby="account-settings-modal-title"
                className="relative z-10 m-0 flex max-h-[90vh] w-full max-w-xl flex-col overflow-hidden rounded-2xl border border-zinc-800 bg-zinc-950 p-0 text-zinc-100 shadow-2xl ring-1 ring-inset ring-white/[0.05]"
            >
                <div className="flex items-start justify-between gap-4 border-b border-zinc-800/80 px-6 py-5">
                    <div className="flex items-center gap-3">
                        <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-violet-500/15 ring-1 ring-violet-500/35">
                            <UserCog className="h-5 w-5 text-violet-300" />
                        </div>
                        <div>
                            <h2
                                id="account-settings-modal-title"
                                className="text-base font-semibold text-zinc-100"
                            >
                                Account Settings
                            </h2>
                            <p className="text-xs text-zinc-400">
                                {displayLabel}
                                {user.email ? ` · ${user.email}` : ""}
                            </p>
                        </div>
                    </div>
                    <button
                        type="button"
                        onClick={handleClose}
                        aria-label="Close account settings modal"
                        className="rounded-lg p-1.5 text-zinc-400 transition hover:bg-zinc-900 hover:text-zinc-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-500/70"
                    >
                        <X className="h-4 w-4" />
                    </button>
                </div>

                <div
                    role="tablist"
                    aria-label="Account settings sections"
                    className="flex items-center gap-1 border-b border-zinc-800/80 px-6"
                >
                    <button
                        type="button"
                        role="tab"
                        aria-selected={activeTab === "profile"}
                        onClick={() => setActiveTab("profile")}
                        className={`relative inline-flex items-center gap-1.5 px-3 py-3 text-xs font-semibold transition ${
                            activeTab === "profile"
                                ? "text-zinc-100"
                                : "text-zinc-400 hover:text-zinc-200"
                        }`}
                    >
                        <UserCog className="h-3.5 w-3.5 text-violet-400" />
                        Profile &amp; Preferences
                        {activeTab === "profile" && (
                            <span className="absolute inset-x-0 bottom-0 h-0.5 rounded-full bg-violet-500" />
                        )}
                    </button>
                    <button
                        type="button"
                        role="tab"
                        aria-selected={activeTab === "security"}
                        onClick={() => setActiveTab("security")}
                        className={`relative inline-flex items-center gap-1.5 px-3 py-3 text-xs font-semibold transition ${
                            activeTab === "security"
                                ? "text-zinc-100"
                                : "text-zinc-400 hover:text-zinc-200"
                        }`}
                    >
                        <ShieldCheck className="h-3.5 w-3.5 text-violet-400" />
                        Security
                        {activeTab === "security" && (
                            <span className="absolute inset-x-0 bottom-0 h-0.5 rounded-full bg-violet-500" />
                        )}
                    </button>
                </div>

                <div className="flex-1 overflow-y-auto px-6 py-5">
                    {activeTab === "profile" ? (
                        <ProfilePreferencesTab user={user} onProfileSaved={onProfileSaved} />
                    ) : (
                        <div className="space-y-6">
                            <ChangePasswordSection />
                            <DeactivateAccountSection
                                onAccountDeactivated={onAccountDeactivated}
                            />
                        </div>
                    )}
                </div>
            </dialog>
        </div>
    );

    return createPortal(modalContent, document.body);
}
