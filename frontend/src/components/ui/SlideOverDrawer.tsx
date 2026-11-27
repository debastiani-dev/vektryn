import { type ReactNode, useEffect, useState } from "react";
import { createPortal } from "react-dom";
import {
    type VisualViewportRect,
    computeDrawerLayout,
    readVisualViewportRect,
} from "../../utils/popoverPosition";

interface SlideOverDrawerProps {
    labelledBy: string;
    closeLabel: string;
    desktopMaxWidthPx?: number;
    backdropClassName?: string;
    onClose: () => void;
    children: ReactNode;
}

export function SlideOverDrawer({
    labelledBy,
    closeLabel,
    desktopMaxWidthPx = 768,
    backdropClassName = "bg-black/70 backdrop-blur-xs",
    onClose,
    children,
}: Readonly<SlideOverDrawerProps>) {
    const [viewport, setViewport] = useState<VisualViewportRect | null>(readVisualViewportRect);

    useEffect(() => {
        const previousHtmlOverflow = document.documentElement.style.overflow;
        const previousBodyOverflow = document.body.style.overflow;
        document.documentElement.style.overflow = "hidden";
        document.body.style.overflow = "hidden";

        const syncViewport = () => {
            setViewport(readVisualViewportRect());
        };
        const handleKeyDown = (event: KeyboardEvent) => {
            if (event.key === "Escape") {
                onClose();
            }
        };

        syncViewport();
        globalThis.window.addEventListener("keydown", handleKeyDown);
        globalThis.window.addEventListener("resize", syncViewport);
        const vv = globalThis.window.visualViewport;
        vv?.addEventListener("resize", syncViewport);
        vv?.addEventListener("scroll", syncViewport);

        return () => {
            document.documentElement.style.overflow = previousHtmlOverflow;
            document.body.style.overflow = previousBodyOverflow;
            globalThis.window.removeEventListener("keydown", handleKeyDown);
            globalThis.window.removeEventListener("resize", syncViewport);
            vv?.removeEventListener("resize", syncViewport);
            vv?.removeEventListener("scroll", syncViewport);
        };
    }, [onClose]);

    const layout = viewport ? computeDrawerLayout(viewport, desktopMaxWidthPx) : null;
    const isCompact = layout?.isCompact ?? false;
    const panelBorderClass = isCompact ? "" : "md:border-l md:border-zinc-800";
    const panelAnimationClass = isCompact ? "" : "md:animate-drawer-in";
    const fallbackInsetClass = layout ? "" : "inset-0";

    const drawerTree = (
        <div
            style={layout?.overlayStyle}
            className={`fixed ${fallbackInsetClass} z-50 overflow-hidden overscroll-contain`}
        >
            <button
                type="button"
                aria-label={closeLabel}
                onClick={onClose}
                className={`absolute inset-0 h-full w-full cursor-default ${backdropClassName}`}
            />
            <div
                role="dialog"
                aria-modal="true"
                aria-labelledby={labelledBy}
                style={layout?.panelStyle}
                className={`${panelAnimationClass} ${panelBorderClass} absolute ${fallbackInsetClass} z-10 flex min-w-0 flex-col overflow-x-hidden bg-zinc-950 text-zinc-100 shadow-2xl md:left-auto`}
            >
                {children}
            </div>
        </div>
    );

    return typeof document === "undefined" ? drawerTree : createPortal(drawerTree, document.body);
}
