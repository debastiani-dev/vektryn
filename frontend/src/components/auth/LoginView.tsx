import { ArrowLeft, Clock, Info, Lock, LogIn, ShieldAlert } from "lucide-react";
import { type MouseEvent, type SubmitEvent, useEffect, useState } from "react";
import { ApiError, vektrynApi } from "../../api/client";
import type { CurrentUser } from "../../types/models";
import { VektrynLogo } from "../ui/VektrynLogo";

interface LoginViewProps {
    onAuthenticated: (user: CurrentUser) => void;
    onBackToHome?: () => void;
    sessionNotice?: string | null;
}

function formatCooldown(totalSeconds: number): string {
    const safe = Math.max(0, Math.ceil(totalSeconds));
    const minutes = Math.floor(safe / 60);
    const seconds = safe % 60;
    if (minutes === 0) {
        return `${seconds}s`;
    }
    return `${minutes}m ${String(seconds).padStart(2, "0")}s`;
}

export function LoginView({
    onAuthenticated,
    onBackToHome,
    sessionNotice = null,
}: Readonly<LoginViewProps>) {
    const [username, setUsername] = useState("");
    const [password, setPassword] = useState("");
    const [submitting, setSubmitting] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [cooldownSeconds, setCooldownSeconds] = useState(0);

    useEffect(() => {
        if (cooldownSeconds <= 0) {
            return;
        }
        const timer = globalThis.setInterval(() => {
            setCooldownSeconds((prev) => (prev <= 1 ? 0 : prev - 1));
        }, 1000);
        return () => globalThis.clearInterval(timer);
    }, [cooldownSeconds]);

    function handleUsernameChange(nextValue: string) {
        setUsername(nextValue);
        if (cooldownSeconds > 0) {
            setCooldownSeconds(0);
            setError(null);
        }
    }

    async function handleSubmit(event: SubmitEvent<HTMLFormElement>) {
        event.preventDefault();
        if (cooldownSeconds > 0) {
            return;
        }
        if (!username.trim() || !password) {
            setError("Enter both username and password.");
            return;
        }
        setSubmitting(true);
        setError(null);
        try {
            await vektrynApi.ensureCsrf();
            const user = await vektrynApi.login(username.trim(), password);
            onAuthenticated(user);
        } catch (err) {
            if (err instanceof ApiError) {
                if (err.status === 429) {
                    setCooldownSeconds(err.retryAfterSeconds ?? 60);
                    setError(
                        err.detail || "Too many failed login attempts. Please wait before retrying.",
                    );
                } else if (err.status === 401) {
                    setError("Invalid username or password.");
                } else if (err.status === 400) {
                    setError(err.detail || "Enter both username and password.");
                } else {
                    setError(err.detail || "Sign in failed. Please try again.");
                }
            } else {
                setError("Sign in failed. Please try again.");
            }
        } finally {
            setSubmitting(false);
        }
    }

    const isLockedOut = cooldownSeconds > 0;
    let submitLabel = "Sign In";
    if (isLockedOut) {
        submitLabel = `Locked (${formatCooldown(cooldownSeconds)})`;
    } else if (submitting) {
        submitLabel = "Signing in...";
    }

    function handleBackClick(event: MouseEvent<HTMLAnchorElement>) {
        if (
            !onBackToHome ||
            event.metaKey ||
            event.ctrlKey ||
            event.shiftKey ||
            event.altKey ||
            event.button !== 0
        ) {
            return;
        }
        event.preventDefault();
        onBackToHome();
    }

    return (
        <div className="flex min-h-screen items-center justify-center px-6 py-12 text-zinc-100">
            <div className="w-full max-w-md space-y-6 rounded-2xl border border-zinc-800/90 bg-zinc-900/70 p-8 shadow-2xl ring-1 ring-inset ring-white/[0.04] backdrop-blur-md">
                {onBackToHome && (
                    <div>
                        <a
                            href="/"
                            onClick={handleBackClick}
                            className="inline-flex min-h-9 items-center gap-1.5 rounded-lg text-xs font-medium text-zinc-400 transition hover:text-zinc-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-500/70"
                        >
                            <ArrowLeft className="h-3.5 w-3.5" aria-hidden="true" />
                            <span>Back to Vektryn</span>
                        </a>
                    </div>
                )}

                <div className="flex flex-col items-center space-y-3 text-center">
                    <VektrynLogo className="h-11 w-11" />
                    <div className="space-y-1">
                        <h1 className="font-mono text-2xl font-semibold tracking-tight text-zinc-100">
                            vektryn
                        </h1>
                        <p className="text-sm text-zinc-400">
                            Sign in with your Vektryn control-plane account
                        </p>
                    </div>
                </div>

                {sessionNotice && !error && !isLockedOut && (
                    <output className="flex items-start gap-2.5 rounded-xl border border-sky-500/35 bg-sky-950/30 px-4 py-3 text-xs text-sky-200">
                        <Info className="mt-0.5 h-4 w-4 shrink-0 text-sky-400" />
                        <span>{sessionNotice}</span>
                    </output>
                )}

                {isLockedOut && (
                    <div
                        role="alert"
                        className="flex items-start gap-3 rounded-xl border border-amber-500/35 bg-amber-950/30 px-4 py-3 text-sm text-amber-200"
                    >
                        <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0 text-amber-400" />
                        <div className="space-y-1">
                            <p className="font-medium text-amber-100">
                                Too many failed sign-in attempts
                            </p>
                            <p className="flex items-center gap-1.5 text-xs text-amber-300/90">
                                <Clock className="h-3.5 w-3.5" />
                                <span>
                                    Try again in{" "}
                                    <span className="font-mono font-semibold text-amber-100">
                                        {formatCooldown(cooldownSeconds)}
                                    </span>
                                </span>
                            </p>
                        </div>
                    </div>
                )}

                {!isLockedOut && error && (
                    <div
                        role="alert"
                        className="rounded-xl border border-red-500/30 bg-red-950/25 px-4 py-3 text-sm text-red-300"
                    >
                        {error}
                    </div>
                )}

                <form onSubmit={(e) => void handleSubmit(e)} className="space-y-4">
                    <div className="space-y-1.5">
                        <label
                            htmlFor="login-username"
                            className="block text-xs font-medium uppercase tracking-wider text-zinc-400"
                        >
                            Username
                        </label>
                        <input
                            id="login-username"
                            type="text"
                            autoComplete="username"
                            value={username}
                            onChange={(e) => handleUsernameChange(e.target.value)}
                            placeholder="admin"
                            className="w-full rounded-xl border border-zinc-800 bg-zinc-950/80 px-4 py-2.5 text-sm text-zinc-100 placeholder:text-zinc-600 transition focus:border-violet-500 focus:outline-none focus:ring-2 focus:ring-violet-500/25"
                        />
                    </div>

                    <div className="space-y-1.5">
                        <label
                            htmlFor="login-password"
                            className="block text-xs font-medium uppercase tracking-wider text-zinc-400"
                        >
                            Password
                        </label>
                        <input
                            id="login-password"
                            type="password"
                            autoComplete="current-password"
                            value={password}
                            onChange={(e) => setPassword(e.target.value)}
                            placeholder="••••••••"
                            className="w-full rounded-xl border border-zinc-800 bg-zinc-950/80 px-4 py-2.5 text-sm text-zinc-100 placeholder:text-zinc-600 transition focus:border-violet-500 focus:outline-none focus:ring-2 focus:ring-violet-500/25"
                        />
                    </div>

                    <button
                        type="submit"
                        disabled={submitting || isLockedOut}
                        className="inline-flex w-full items-center justify-center gap-2 rounded-xl bg-violet-600 px-4 py-2.5 text-sm font-medium text-white shadow-sm shadow-violet-600/25 transition hover:bg-violet-500 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-500/70 disabled:cursor-not-allowed disabled:opacity-60"
                    >
                        <LogIn className="h-4 w-4" />
                        {submitLabel}
                    </button>
                </form>

                <div className="flex items-center justify-center gap-1.5 border-t border-zinc-800/80 pt-4 text-xs text-zinc-500">
                    <Lock className="h-3.5 w-3.5" />
                    <span>Session-authenticated with signed per-user SSE alerts</span>
                </div>
            </div>
        </div>
    );
}

export default LoginView;
