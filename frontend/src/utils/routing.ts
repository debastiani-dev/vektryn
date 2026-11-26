export type AppRoute = "/" | "/login" | "/app";

export function normalizeRoute(pathname: string): AppRoute {
    const trimmed = pathname.trim().replace(/\/+$/, "") || "/";
    if (trimmed === "/login") {
        return "/login";
    }
    if (trimmed === "/app") {
        return "/app";
    }
    return "/";
}

export function shouldHydrateSessionOnBoot(route: AppRoute, sessionHintPresent: boolean): boolean {
    if (route === "/login" || route === "/app") {
        return true;
    }
    return sessionHintPresent;
}

export function isRouteTransition(prevRoute: AppRoute, nextPathname: string): boolean {
    return normalizeRoute(nextPathname) !== prevRoute;
}

export function resolveInitialRoute(): { route: AppRoute; needsPathNormalize: boolean } {
    if (typeof globalThis.window === "undefined") {
        return { route: "/", needsPathNormalize: false };
    }
    const rawPathname = globalThis.window.location.pathname;
    const normalized = normalizeRoute(rawPathname);
    const cleanedRaw = rawPathname.replace(/\/+$/, "") || "/";
    return {
        route: normalized,
        needsPathNormalize: cleanedRaw !== normalized,
    };
}
