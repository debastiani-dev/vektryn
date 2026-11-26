import { LandingArchitecture } from "./LandingArchitecture";
import { LandingCapabilities } from "./LandingCapabilities";
import { LandingFooter } from "./LandingFooter";
import { LandingHero } from "./LandingHero";
import { LandingNavbar } from "./LandingNavbar";
import { LandingPreviewShowcase } from "./LandingPreviewShowcase";

interface LandingPageProps {
    isAuthenticated: boolean;
    onSignIn: () => void;
    onOpenWorkspace: () => void;
}

export function LandingPage({
    isAuthenticated,
    onSignIn,
    onOpenWorkspace,
}: Readonly<LandingPageProps>) {
    return (
        <div className="min-h-screen overflow-x-clip text-zinc-100">
            <LandingNavbar
                isAuthenticated={isAuthenticated}
                onSignIn={onSignIn}
                onOpenWorkspace={onOpenWorkspace}
            />
            <main>
                <LandingHero
                    isAuthenticated={isAuthenticated}
                    onSignIn={onSignIn}
                    onOpenWorkspace={onOpenWorkspace}
                />
                <LandingPreviewShowcase />
                <LandingCapabilities />
                <LandingArchitecture />
            </main>
            <LandingFooter
                isAuthenticated={isAuthenticated}
                onSignIn={onSignIn}
                onOpenWorkspace={onOpenWorkspace}
            />
        </div>
    );
}
