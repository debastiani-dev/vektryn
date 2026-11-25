import {
    AlertCircle,
    CheckCircle2,
    Eye,
    EyeOff,
    KeyRound,
    Loader2,
    ShieldCheck,
    X,
} from "lucide-react";
import { type SubmitEvent, useCallback, useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { ApiError, vektrynApi } from "../../api/client";
import type { CurrentUser } from "../../types/models";

interface AccountSecurityModalProps {
    open: boolean;
    user: CurrentUser;
    onClose: () => void;
}

interface PasswordFieldErrors {
    current_password?: string[];
    new_password?: string[];
    confirm_password?: string[];
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
            {hasError && (
                <ul className="space-y-1 text-xs text-red-300">
                    {errors?.map((msg) => (
                        <li key={msg} className="flex items-start gap-1.5">
                            <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-red-400" />
                            <span>{msg}</span>
                        </li>
                    ))}
                </ul>
            )}
        </div>
    );
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

export function AccountSecurityModal({
    open,
    user,
    onClose,
}: Readonly<AccountSecurityModalProps>) {
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

    const resetSensitiveState = useCallback(() => {
        setCurrentPassword("");
        setNewPassword("");
        setConfirmPassword("");
        setShowCurrent(false);
        setShowNew(false);
        setShowConfirm(false);
    }, []);

    const handleClose = useCallback(() => {
        resetSensitiveState();
        setFieldErrors({});
        setGeneralError(null);
        setSuccessMessage(null);
        onClose();
    }, [onClose, resetSensitiveState]);

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

    const modalContent = (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
            <button
                type="button"
                tabIndex={-1}
                aria-label="Close account security modal backdrop"
                onClick={handleClose}
                className="fixed inset-0 bg-black/75 backdrop-blur-sm"
            />
            <dialog
                open
                aria-labelledby="account-security-modal-title"
                className="relative z-10 m-0 w-full max-w-md rounded-2xl border border-zinc-800 bg-zinc-950 p-6 text-zinc-100 shadow-2xl ring-1 ring-inset ring-white/[0.05]"
            >
                <div className="flex items-start justify-between gap-4 border-b border-zinc-800/80 pb-4">
                    <div className="flex items-center gap-3">
                        <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-violet-500/15 ring-1 ring-violet-500/35">
                            <ShieldCheck className="h-5 w-5 text-violet-300" />
                        </div>
                        <div>
                            <h2
                                id="account-security-modal-title"
                                className="text-base font-semibold text-zinc-100"
                            >
                                Account &amp; Security
                            </h2>
                            <p className="text-xs text-zinc-400">
                                {user.username}
                                {user.email ? ` · ${user.email}` : ""}
                            </p>
                        </div>
                    </div>
                    <button
                        type="button"
                        onClick={handleClose}
                        aria-label="Close account security modal"
                        className="rounded-lg p-1.5 text-zinc-400 transition hover:bg-zinc-900 hover:text-zinc-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-500/70"
                    >
                        <X className="h-4 w-4" />
                    </button>
                </div>

                <div className="mt-5 space-y-4">
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

                    <form onSubmit={(e) => void handleSubmit(e)} className="space-y-4">
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
                            Must be at least 8 characters, not too similar to your username or
                            email, not a common password, and not entirely numeric.
                        </p>

                        <div className="flex items-center justify-end gap-2.5 border-t border-zinc-800/80 pt-4">
                            <button
                                type="button"
                                onClick={handleClose}
                                className="rounded-xl border border-zinc-800 bg-zinc-900/80 px-4 py-2 text-xs font-medium text-zinc-300 transition hover:bg-zinc-800 hover:text-zinc-100"
                            >
                                {successMessage ? "Done" : "Cancel"}
                            </button>
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
                </div>
            </dialog>
        </div>
    );

    return createPortal(modalContent, document.body);
}
