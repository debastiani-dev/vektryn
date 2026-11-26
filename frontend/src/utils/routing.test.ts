import { afterEach, describe, expect, it, vi } from "vitest";
import { isRouteTransition, normalizeRoute, shouldHydrateSessionOnBoot } from "./routing";
import { clearSessionHint, hasSessionHint, setSessionHint } from "./sessionHint";

function installMemoryStorage() {
    const store = new Map<string, string>();
    const storage: Storage = {
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
    vi.stubGlobal("localStorage", storage);
    return store;
}

describe("routing and session-hint utilities", () => {
    afterEach(() => {
        vi.unstubAllGlobals();
        vi.restoreAllMocks();
    });

    it("normalizes /, /login, /app, trailing slashes, and unknown paths", () => {
        expect(normalizeRoute("/")).toBe("/");
        expect(normalizeRoute("/login")).toBe("/login");
        expect(normalizeRoute("/login/")).toBe("/login");
        expect(normalizeRoute("/app")).toBe("/app");
        expect(normalizeRoute("/app///")).toBe("/app");
        expect(normalizeRoute("/unknown/path")).toBe("/");
        expect(normalizeRoute("")).toBe("/");
    });

    it("enforces zero-cold-start boot hydration rules", () => {
        expect(shouldHydrateSessionOnBoot("/", false)).toBe(false);
        expect(shouldHydrateSessionOnBoot(normalizeRoute("/bogus"), false)).toBe(false);
        expect(shouldHydrateSessionOnBoot("/", true)).toBe(true);
        expect(shouldHydrateSessionOnBoot("/login", false)).toBe(true);
        expect(shouldHydrateSessionOnBoot("/app", false)).toBe(true);
    });

    it("distinguishes hash-only popstate events from actual route transitions", () => {
        expect(isRouteTransition("/", "/")).toBe(false);
        expect(isRouteTransition("/", "/unknown")).toBe(false);
        expect(isRouteTransition("/", "/login")).toBe(true);
        expect(isRouteTransition("/login", "/app")).toBe(true);
        expect(isRouteTransition("/app", "/")).toBe(true);
    });

    it("persists and clears vektryn_session_hint safely in localStorage", () => {
        installMemoryStorage();
        expect(hasSessionHint()).toBe(false);

        setSessionHint();
        expect(hasSessionHint()).toBe(true);

        clearSessionHint();
        expect(hasSessionHint()).toBe(false);
    });

    it("fails safely when localStorage throws in restricted contexts", () => {
        vi.stubGlobal("localStorage", {
            getItem() {
                throw new Error("blocked");
            },
            setItem() {
                throw new Error("blocked");
            },
            removeItem() {
                throw new Error("blocked");
            },
        });

        expect(() => setSessionHint()).not.toThrow();
        expect(hasSessionHint()).toBe(false);
        expect(() => clearSessionHint()).not.toThrow();
    });
});
