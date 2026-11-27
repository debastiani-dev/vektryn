import { useCallback, useEffect, useState } from "react";

export interface TransitionLoaderState {
    phase: "idle" | "showing" | "exiting";
    label: string;
    token: number;
}

interface UseTransitionLoaderOptions {
    initialLabel?: string | null;
    holdMs?: number;
    fadeMs?: number;
}

export function useTransitionLoader({
    initialLabel = null,
    holdMs = 1800,
    fadeMs = 350,
}: UseTransitionLoaderOptions = {}) {
    const [state, setState] = useState<TransitionLoaderState>(() =>
        initialLabel
            ? { phase: "showing", label: initialLabel, token: 1 }
            : { phase: "idle", label: "", token: 0 },
    );

    const triggerLoader = useCallback((label: string) => {
        setState((prev) => ({ phase: "showing", label, token: prev.token + 1 }));
    }, []);

    useEffect(() => {
        if (state.phase === "idle") {
            return;
        }
        if (state.phase === "showing") {
            const holdTimer = globalThis.setTimeout(() => {
                setState((prev) =>
                    prev.token === state.token ? { ...prev, phase: "exiting" } : prev,
                );
            }, holdMs);
            return () => globalThis.clearTimeout(holdTimer);
        }
        const fadeTimer = globalThis.setTimeout(() => {
            setState((prev) => (prev.token === state.token ? { ...prev, phase: "idle" } : prev));
        }, fadeMs);
        return () => globalThis.clearTimeout(fadeTimer);
    }, [state.phase, state.token, holdMs, fadeMs]);

    return { loader: state, triggerLoader };
}
