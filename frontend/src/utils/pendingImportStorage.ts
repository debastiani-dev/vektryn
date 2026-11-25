export const PENDING_IMPORT_STORAGE_KEY = "vektryn.pending_manual_import.v1";
export const PENDING_IMPORT_STORAGE_TTL_MS = 24 * 60 * 60 * 1000;

export interface PersistedPendingImport {
    externalId: string;
    title: string;
    company: string;
    startedAt: number;
}

function getLocalStorage(): Storage | null {
    try {
        if (typeof globalThis.localStorage === "undefined") {
            return null;
        }
        return globalThis.localStorage;
    } catch {
        return null;
    }
}

function isValidPersistedImport(value: unknown): value is PersistedPendingImport {
    if (typeof value !== "object" || value === null) {
        return false;
    }
    const candidate = value as Record<string, unknown>;
    return (
        typeof candidate.externalId === "string" &&
        candidate.externalId.length > 0 &&
        typeof candidate.title === "string" &&
        typeof candidate.company === "string" &&
        typeof candidate.startedAt === "number" &&
        Number.isFinite(candidate.startedAt) &&
        candidate.startedAt > 0
    );
}

function readStoredPendingImport(storage: Storage): PersistedPendingImport | null {
    const raw = storage.getItem(PENDING_IMPORT_STORAGE_KEY);
    if (!raw) {
        return null;
    }
    const parsed: unknown = JSON.parse(raw);
    if (!isValidPersistedImport(parsed)) {
        storage.removeItem(PENDING_IMPORT_STORAGE_KEY);
        return null;
    }
    return parsed;
}

export function loadPendingImport(nowMs: number = Date.now()): PersistedPendingImport | null {
    const storage = getLocalStorage();
    if (!storage) {
        return null;
    }
    try {
        const parsed = readStoredPendingImport(storage);
        if (!parsed) {
            return null;
        }
        if (nowMs - parsed.startedAt > PENDING_IMPORT_STORAGE_TTL_MS) {
            storage.removeItem(PENDING_IMPORT_STORAGE_KEY);
            return null;
        }
        return parsed;
    } catch {
        try {
            storage.removeItem(PENDING_IMPORT_STORAGE_KEY);
        } catch {
            // Ignore storage cleanup failures
        }
        return null;
    }
}

export function savePendingImport(entry: PersistedPendingImport): void {
    const storage = getLocalStorage();
    if (!storage) {
        return;
    }
    try {
        storage.setItem(PENDING_IMPORT_STORAGE_KEY, JSON.stringify(entry));
    } catch {
        // Ignore storage quota or private-mode errors
    }
}

export function clearPendingImport(externalId?: string): void {
    const storage = getLocalStorage();
    if (!storage) {
        return;
    }
    try {
        if (externalId) {
            const existing = readStoredPendingImport(storage);
            if (existing && existing.externalId !== externalId) {
                return;
            }
        }
        storage.removeItem(PENDING_IMPORT_STORAGE_KEY);
    } catch {
        // Ignore storage cleanup failures
    }
}
