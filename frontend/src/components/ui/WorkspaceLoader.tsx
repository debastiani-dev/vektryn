import { VektrynLogo } from "./VektrynLogo";

interface WorkspaceLoaderProps {
    label?: string;
    placement?: "screen" | "overlay" | "content";
    exiting?: boolean;
}

const PLACEMENT_CLASSES: Record<NonNullable<WorkspaceLoaderProps["placement"]>, string> = {
    screen: "min-h-screen bg-zinc-950",
    overlay: "fixed inset-0 z-50 bg-zinc-950 transition-opacity duration-[350ms]",
    content:
        "fixed inset-0 z-20 bg-zinc-950/95 pt-20 backdrop-blur-sm transition-opacity duration-250",
};

export function WorkspaceLoader({
    label = "Initializing radar workspace...",
    placement = "screen",
    exiting = false,
}: Readonly<WorkspaceLoaderProps>) {
    const positionClasses = PLACEMENT_CLASSES[placement];
    const opacityClass = exiting ? "pointer-events-none opacity-0" : "opacity-100";

    return (
        <output
            aria-live="polite"
            className={`${positionClasses} ${opacityClass} flex flex-col items-center justify-center px-6 text-zinc-100`}
        >
            <div className="vk-loader-enter flex flex-col items-center gap-5">
                <div className="relative flex items-center justify-center">
                    <span
                        aria-hidden="true"
                        className="vk-radar-pulse absolute h-20 w-20 rounded-2xl border border-violet-500/40"
                    />
                    <span
                        aria-hidden="true"
                        className="absolute h-24 w-24 rounded-full bg-violet-500/15 blur-2xl"
                    />
                    <div className="relative flex h-16 w-16 items-center justify-center rounded-2xl bg-zinc-900 ring-1 ring-zinc-800 shadow-2xl shadow-violet-950/50">
                        <VektrynLogo animated className="h-12 w-12" />
                    </div>
                </div>

                <div className="flex flex-col items-center gap-2.5 text-center">
                    <span className="font-mono text-lg font-semibold tracking-tight text-zinc-100">
                        vektryn
                    </span>
                    <div
                        aria-hidden="true"
                        className="h-1 w-36 overflow-hidden rounded-full bg-zinc-900 ring-1 ring-zinc-800/90"
                    >
                        <div className="vk-sweep-bar h-full w-1/3 rounded-full bg-gradient-to-r from-violet-500/30 via-violet-400 to-violet-500/30" />
                    </div>
                    <span className="text-xs font-medium tracking-wide text-zinc-400">
                        {label}
                    </span>
                </div>
            </div>
        </output>
    );
}
