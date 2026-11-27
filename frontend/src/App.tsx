import { type ReactNode, Suspense, lazy, useCallback, useEffect, useRef, useState } from "react";
import { registerSessionExpiredHandler, vektrynApi } from "./api/client";
import { LandingPage } from "./components/landing/LandingPage";
import { WorkspaceLoader } from "./components/ui/WorkspaceLoader";
import { useTransitionLoader } from "./hooks/useTransitionLoader";
import type { CurrentUser, UserProfileDetail } from "./types/models";
import { clearPendingImport } from "./utils/pendingImportStorage";
import {
    type AppRoute,
    isRouteTransition,
    normalizeRoute,
    resolveInitialRoute,
    shouldHydrateSessionOnBoot,
} from "./utils/routing";
import { syncSentryUser } from "./utils/sentry";
import { clearSessionHint, hasSessionHint, setSessionHint } from "./utils/sessionHint";

const LoginView = lazy(() => import("./components/auth/LoginView"));
const AuthenticatedWorkspace = lazy(
    () => import("./components/layout/AuthenticatedWorkspace"),
);

const TRANSITION_LOADER_HOLD_MS = 1800;
const TRANSITION_LOADER_FADE_MS = 350;

function DarkRouteFallback({ label = "Loading Vektryn..." }: Readonly<{ label?: string }>) {
    return <WorkspaceLoader label={label} />;
}

interface BootSnapshot {
    route: AppRoute;
    needsPathNormalize: boolean;
    shouldHydrate: boolean;
}

function captureBootSnapshot(): BootSnapshot {
    const { route, needsPathNormalize } = resolveInitialRoute();
    const shouldHydrate = shouldHydrateSessionOnBoot(route, hasSessionHint());
    return { route, needsPathNormalize, shouldHydrate };
}

function resolveInitialLoaderLabel(boot: BootSnapshot): string | null {
    if (boot.route === "/login") {
        return "Opening sign in...";
    }
    if (boot.route === "/app" || boot.shouldHydrate) {
        return "Initializing radar workspace...";
    }
    return null;
}

export function App() {
    const [boot] = useState<BootSnapshot>(captureBootSnapshot);
    const [route, setRoute] = useState<AppRoute>(boot.route);
    const [user, setUser] = useState<CurrentUser | null>(null);
    const [sessionNotice, setSessionNotice] = useState<string | null>(null);
    const [hasCheckedSession, setHasCheckedSession] = useState(false);
    const { loader: transitionLoader, triggerLoader } = useTransitionLoader({
        initialLabel: resolveInitialLoaderLabel(boot),
        holdMs: TRANSITION_LOADER_HOLD_MS,
        fadeMs: TRANSITION_LOADER_FADE_MS,
    });

    const routeRef = useRef<AppRoute>(route);
    const userRef = useRef<CurrentUser | null>(user);
    const sessionCheckInFlightRef = useRef(false);

    useEffect(() => {
        routeRef.current = route;
    }, [route]);

    useEffect(() => {
        userRef.current = user;
        syncSentryUser(user);
    }, [user]);

    const navigate = useCallback((nextRoute: AppRoute, options?: { replace?: boolean }) => {
        const previousRoute = routeRef.current;
        if (typeof globalThis.window !== "undefined") {
            const currentNormalized = normalizeRoute(globalThis.window.location.pathname);
            if (currentNormalized !== nextRoute) {
                if (options?.replace) {
                    globalThis.window.history.replaceState(null, "", nextRoute);
                } else {
                    globalThis.window.history.pushState(null, "", nextRoute);
                }
            }
            if (previousRoute !== nextRoute) {
                globalThis.window.scrollTo(0, 0);
            }
        }
        routeRef.current = nextRoute;
        setRoute(nextRoute);
    }, []);

    useEffect(() => {
        if (typeof globalThis.window === "undefined") {
            return;
        }
        if (boot.needsPathNormalize) {
            const hash = globalThis.window.location.hash || "";
            globalThis.window.history.replaceState(null, "", `${boot.route}${hash}`);
        }

        function handlePopState() {
            const rawPath = globalThis.window.location.pathname;
            if (!isRouteTransition(routeRef.current, rawPath)) {
                return;
            }
            const nextRoute = normalizeRoute(rawPath);
            routeRef.current = nextRoute;
            setRoute(nextRoute);
            if (!globalThis.window.location.hash) {
                globalThis.window.scrollTo(0, 0);
            }
        }

        globalThis.window.addEventListener("popstate", handlePopState);
        return () => globalThis.window.removeEventListener("popstate", handlePopState);
    }, [boot.needsPathNormalize, boot.route]);

    const needsSessionCheck =
        !hasCheckedSession && !user && (boot.shouldHydrate || route === "/login" || route === "/app");

    useEffect(() => {
        if (!needsSessionCheck || sessionCheckInFlightRef.current) {
            return;
        }
        let cancelled = false;
        const autoRedirectHome = boot.shouldHydrate && boot.route === "/";
        sessionCheckInFlightRef.current = true;

        async function fetchSession() {
            try {
                const me = await vektrynApi.getCurrentUser();
                if (cancelled) {
                    return;
                }
                setSessionHint();
                setUser(me);
                const current = routeRef.current;
                if (current === "/login" || (autoRedirectHome && current === "/")) {
                    navigate("/app", { replace: true });
                }
            } catch {
                if (cancelled) {
                    return;
                }
                clearSessionHint();
                setUser(null);
                if (routeRef.current === "/app") {
                    navigate("/login", { replace: true });
                }
            } finally {
                sessionCheckInFlightRef.current = false;
                if (!cancelled) {
                    setHasCheckedSession(true);
                }
            }
        }

        void fetchSession();
        return () => {
            cancelled = true;
            sessionCheckInFlightRef.current = false;
        };
    }, [needsSessionCheck, boot.shouldHydrate, boot.route, navigate]);

    let effectiveRoute: AppRoute = route;
    if (route === "/login" && user) {
        effectiveRoute = "/app";
    } else if (route === "/app" && !user && hasCheckedSession) {
        effectiveRoute = "/login";
    }

    useEffect(() => {
        if (typeof globalThis.window === "undefined") {
            return;
        }
        const currentNormalized = normalizeRoute(globalThis.window.location.pathname);
        if (currentNormalized !== effectiveRoute) {
            globalThis.window.history.replaceState(null, "", effectiveRoute);
            routeRef.current = effectiveRoute;
        }
    }, [effectiveRoute]);

    const clearClientSessionState = useCallback(() => {
        clearSessionHint();
        clearPendingImport();
        setUser(null);
    }, []);

    useEffect(() => {
        return registerSessionExpiredHandler(() => {
            if (!userRef.current) {
                return;
            }
            setSessionNotice(
                "Your session ended (for example, after a password change or timeout). Please sign in again.",
            );
            clearClientSessionState();
            triggerLoader("Opening sign in...");
            navigate("/login", { replace: true });
        });
    }, [clearClientSessionState, navigate, triggerLoader]);

    const handleGoToLogin = useCallback(() => {
        triggerLoader("Opening sign in...");
        navigate("/login");
    }, [navigate, triggerLoader]);

    const handleOpenWorkspace = useCallback(() => {
        triggerLoader("Initializing radar workspace...");
        navigate("/app");
    }, [navigate, triggerLoader]);

    const handleAuthenticated = useCallback(
        (authenticatedUser: CurrentUser) => {
            setSessionHint();
            setSessionNotice(null);
            setUser(authenticatedUser);
            setHasCheckedSession(true);
            triggerLoader("Initializing radar workspace...");
            navigate("/app");
        },
        [navigate, triggerLoader],
    );

    const handleUserProfileSaved = useCallback((updatedProfile: UserProfileDetail) => {
        setUser((prev) => {
            if (!prev) return prev;
            return {
                ...prev,
                email: updatedProfile.email,
                profile: {
                    display_name: updatedProfile.display_name,
                    timezone: updatedProfile.timezone,
                    preferred_currency: updatedProfile.preferred_currency,
                    default_copilot_tone: updatedProfile.default_copilot_tone,
                    has_gemini_api_key: updatedProfile.has_gemini_api_key,
                    gemini_api_key_last4: updatedProfile.gemini_api_key_last4,
                    preferred_gemini_model: updatedProfile.preferred_gemini_model,
                    allow_model_fallback: updatedProfile.allow_model_fallback,
                },
            };
        });
    }, []);

    const handleAccountDeactivated = useCallback(() => {
        setSessionNotice(null);
        clearClientSessionState();
        navigate("/", { replace: true });
    }, [clearClientSessionState, navigate]);

    const handleLogout = useCallback(async () => {
        triggerLoader("Signing out...");
        try {
            await vektrynApi.logout();
        } catch {
            // Clear local session regardless of server response.
        } finally {
            setSessionNotice(null);
            clearClientSessionState();
            navigate("/", { replace: true });
        }
    }, [clearClientSessionState, navigate, triggerLoader]);

    let routeContent: ReactNode;
    if (effectiveRoute === "/") {
        routeContent = (
            <LandingPage
                isAuthenticated={user !== null}
                onSignIn={handleGoToLogin}
                onOpenWorkspace={handleOpenWorkspace}
            />
        );
    } else if (effectiveRoute === "/login") {
        routeContent = needsSessionCheck ? (
            <DarkRouteFallback label="Checking session..." />
        ) : (
            <Suspense fallback={<DarkRouteFallback label="Opening sign in..." />}>
                <LoginView
                    onAuthenticated={handleAuthenticated}
                    onBackToHome={() => navigate("/")}
                    sessionNotice={sessionNotice}
                />
            </Suspense>
        );
    } else if (!user) {
        routeContent = <DarkRouteFallback label="Checking session..." />;
    } else {
        routeContent = (
            <Suspense fallback={<DarkRouteFallback label="Initializing radar workspace..." />}>
                <AuthenticatedWorkspace
                    user={user}
                    onUserProfileSaved={handleUserProfileSaved}
                    onAccountDeactivated={handleAccountDeactivated}
                    onLogout={handleLogout}
                />
            </Suspense>
        );
    }

    return (
        <>
            {transitionLoader.phase !== "idle" && (
                <WorkspaceLoader
                    placement="overlay"
                    exiting={transitionLoader.phase === "exiting"}
                    label={transitionLoader.label}
                />
            )}
            {routeContent}
        </>
    );
}

export default App;
