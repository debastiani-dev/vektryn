import { Lock, LogIn, Radar } from "lucide-react";
import { type FormEvent, useState } from "react";
import { vektrynApi } from "../../api/client";
import type { CurrentUser } from "../../types/models";

interface LoginViewProps {
    onAuthenticated: (user: CurrentUser) => void;
}

export function LoginView({ onAuthenticated }: Readonly<LoginViewProps>) {
    const [username, setUsername] = useState("");
    const [password, setPassword] = useState("");
    const [submitting, setSubmitting] = useState(false);
    const [error, setError] = useState<string | null>(null);

    async function handleSubmit(event: FormEvent<HTMLFormElement>) {
        event.preventDefault();
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
            const raw = err instanceof Error ? err.message : "";
            if (raw.includes("API 401") || raw.includes("API 400")) {
                setError("Invalid username or password.");
            } else {
                setError(raw || "Sign in failed. Please try again.");
            }
        } finally {
            setSubmitting(false);
        }
    }

    return (
        <div className="flex min-h-screen items-center justify-center px-6 py-12 text-zinc-100">
            <div className="w-full max-w-md space-y-6 rounded-2xl border border-zinc-800/90 bg-zinc-900/70 p-8 shadow-2xl ring-1 ring-inset ring-white/[0.04] backdrop-blur-md">
                <div className="flex flex-col items-center space-y-3 text-center">
                    <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-gradient-to-br from-violet-500/25 to-fuchsia-500/15 ring-1 ring-violet-500/40 shadow-sm shadow-violet-500/15">
                        <Radar className="h-6 w-6 text-violet-300" />
                    </div>
                    <div className="space-y-1">
                        <h1 className="font-mono text-2xl font-semibold tracking-tight text-zinc-100">
                            vektryn
                        </h1>
                        <p className="text-sm text-zinc-400">
                            Sign in with your Vektryn control-plane account
                        </p>
                    </div>
                </div>

                {error && (
                    <div className="rounded-xl border border-red-500/30 bg-red-950/25 px-4 py-3 text-sm text-red-300">
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
                            onChange={(e) => setUsername(e.target.value)}
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
                        disabled={submitting}
                        className="inline-flex w-full items-center justify-center gap-2 rounded-xl bg-violet-600 px-4 py-2.5 text-sm font-medium text-white shadow-sm shadow-violet-600/25 transition hover:bg-violet-500 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-500/70 disabled:opacity-60"
                    >
                        <LogIn className="h-4 w-4" />
                        {submitting ? "Signing in..." : "Sign In"}
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
