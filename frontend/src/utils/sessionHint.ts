const SESSION_HINT_KEY = "vektryn_session_hint";

export function hasSessionHint(): boolean {
    if (typeof globalThis.localStorage === "undefined") {
        return false;
    }
    try {
        return globalThis.localStorage.getItem(SESSION_HINT_KEY) === "1";
    } catch {
        return false;
    }
}

export function setSessionHint(): void {
    if (typeof globalThis.localStorage === "undefined") {
        return;
    }
    try {
        globalThis.localStorage.setItem(SESSION_HINT_KEY, "1");
    } catch {
        // Ignore storage write errors in restricted browser contexts.
    }
}

export function clearSessionHint(): void {
    if (typeof globalThis.localStorage === "undefined") {
        return;
    }
    try {
        globalThis.localStorage.removeItem(SESSION_HINT_KEY);
    } catch {
        // Ignore storage cleanup errors in restricted browser contexts.
    }
}
