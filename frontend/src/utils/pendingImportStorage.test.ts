import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
    clearPendingImport,
    loadPendingImport,
    PENDING_IMPORT_STORAGE_KEY,
    PENDING_IMPORT_STORAGE_TTL_MS,
    savePendingImport,
} from "./pendingImportStorage";

function createMemoryStorage(): Storage {
    const store = new Map<string, string>();
    return {
        get length() {
            return store.size;
        },
        clear() {
            store.clear();
        },
        getItem(key: string) {
            return store.get(key) ?? null;
        },
        key(index: number) {
            return Array.from(store.keys())[index] ?? null;
        },
        removeItem(key: string) {
            store.delete(key);
        },
        setItem(key: string, value: string) {
            store.set(key, value);
        },
    };
}

describe("pendingImportStorage", () => {
    let storage: Storage;

    beforeEach(() => {
        storage = createMemoryStorage();
        vi.stubGlobal("localStorage", storage);
    });

    afterEach(() => {
        vi.unstubAllGlobals();
    });

    it("saves and restores a valid pending import", () => {
        const entry = {
            externalId: "manual-123",
            title: "Senior Backend Engineer",
            company: "Acme Corp",
            startedAt: 1_700_000_000_000,
        };
        savePendingImport(entry);

        expect(loadPendingImport(1_700_000_050_000)).toEqual(entry);
    });

    it("prunes entries older than the 24-hour storage TTL", () => {
        const startedAt = 1_700_000_000_000;
        savePendingImport({
            externalId: "manual-old",
            title: "Staff Engineer",
            company: "Legacy Co",
            startedAt,
        });

        expect(loadPendingImport(startedAt + PENDING_IMPORT_STORAGE_TTL_MS + 1)).toBeNull();
        expect(storage.getItem(PENDING_IMPORT_STORAGE_KEY)).toBeNull();
    });

    it("clears corrupted JSON safely", () => {
        storage.setItem(PENDING_IMPORT_STORAGE_KEY, "{not-json");

        expect(loadPendingImport()).toBeNull();
        expect(storage.getItem(PENDING_IMPORT_STORAGE_KEY)).toBeNull();
    });

    it("only clears matching externalId when externalId guard is passed", () => {
        const entry = {
            externalId: "manual-new",
            title: "Platform Engineer",
            company: "Vektryn",
            startedAt: 1_700_000_000_000,
        };
        savePendingImport(entry);

        clearPendingImport("manual-other");
        expect(loadPendingImport(1_700_000_001_000)).toEqual(entry);

        clearPendingImport("manual-new");
        expect(loadPendingImport(1_700_000_001_000)).toBeNull();
    });

    it("clears unconditionally when called without an externalId", () => {
        savePendingImport({
            externalId: "manual-abc",
            title: "ML Engineer",
            company: "Lab",
            startedAt: 1_700_000_000_000,
        });

        clearPendingImport();
        expect(storage.getItem(PENDING_IMPORT_STORAGE_KEY)).toBeNull();
    });
});
