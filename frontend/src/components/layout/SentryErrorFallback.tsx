import { AlertTriangle, RotateCw } from "lucide-react";

export function SentryErrorFallback() {
    return (
        <div className="flex min-h-screen items-center justify-center bg-zinc-950 px-6 text-zinc-100">
            <div className="w-full max-w-md rounded-2xl border border-zinc-800 bg-zinc-900/90 p-6 shadow-2xl">
                <div className="flex items-center gap-3">
                    <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border border-amber-500/30 bg-amber-500/10 text-amber-400">
                        <AlertTriangle className="h-5 w-5" aria-hidden="true" />
                    </div>
                    <div>
                        <h1 className="text-base font-semibold tracking-tight text-zinc-100">
                            Something went wrong
                        </h1>
                        <p className="text-xs text-zinc-400">
                            Vektryn ran into an unexpected rendering error.
                        </p>
                    </div>
                </div>
                <p className="mt-4 text-sm leading-relaxed text-zinc-400">
                    Your data is safe. Reload the page to recover your session.
                </p>
                <button
                    type="button"
                    onClick={() => window.location.reload()}
                    className="mt-5 inline-flex w-full items-center justify-center gap-2 rounded-lg bg-violet-600 px-4 py-2.5 text-sm font-medium text-white transition hover:bg-violet-500"
                >
                    <RotateCw className="h-4 w-4" aria-hidden="true" />
                    Reload Vektryn
                </button>
            </div>
        </div>
    );
}
