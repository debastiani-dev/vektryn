import { type ReactNode, useCallback, useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";

interface TooltipProps {
    content: string | null | undefined;
    side?: "top" | "bottom";
    className?: string;
    children: ReactNode;
}

interface TooltipCoords {
    top: number;
    left: number;
    placement: "top" | "bottom";
}

const HOVER_DELAY_MS = 180;
const EDGE_MARGIN_PX = 140;
const FLIP_THRESHOLD_PX = 56;
const OFFSET_PX = 8;

function computeTooltipCoords(rect: DOMRect, preferredSide: "top" | "bottom"): TooltipCoords {
    let placement = preferredSide;
    if (preferredSide === "top" && rect.top < FLIP_THRESHOLD_PX) {
        placement = "bottom";
    } else if (
        preferredSide === "bottom" &&
        window.innerHeight - rect.bottom < FLIP_THRESHOLD_PX
    ) {
        placement = "top";
    }

    const centerX = rect.left + rect.width / 2;
    const minLeft = Math.min(EDGE_MARGIN_PX, window.innerWidth / 2);
    const maxLeft = Math.max(window.innerWidth - EDGE_MARGIN_PX, window.innerWidth / 2);
    const left = Math.min(Math.max(centerX, minLeft), maxLeft);
    const top = placement === "top" ? rect.top - OFFSET_PX : rect.bottom + OFFSET_PX;

    return { top, left, placement };
}

export function Tooltip({
    content,
    side = "top",
    className = "inline-flex",
    children,
}: Readonly<TooltipProps>) {
    const [open, setOpen] = useState(false);
    const [coords, setCoords] = useState<TooltipCoords | null>(null);
    const triggerRef = useRef<HTMLSpanElement | null>(null);
    const timerRef = useRef<number | null>(null);
    const tooltipId = useId();

    const clearTimer = useCallback(() => {
        if (timerRef.current !== null) {
            window.clearTimeout(timerRef.current);
            timerRef.current = null;
        }
    }, []);

    const close = useCallback(() => {
        clearTimer();
        setOpen(false);
    }, [clearTimer]);

    const openNow = useCallback(() => {
        const el = triggerRef.current;
        if (!el) return;
        setCoords(computeTooltipCoords(el.getBoundingClientRect(), side));
        setOpen(true);
    }, [side]);

    const scheduleOpen = useCallback(() => {
        clearTimer();
        timerRef.current = window.setTimeout(() => {
            openNow();
        }, HOVER_DELAY_MS);
    }, [clearTimer, openNow]);

    useEffect(() => {
        return () => clearTimer();
    }, [clearTimer]);

    useEffect(() => {
        if (!open) return;
        const handleDismiss = () => close();
        const handleKeyDown = (event: KeyboardEvent) => {
            if (event.key === "Escape") close();
        };
        window.addEventListener("scroll", handleDismiss, true);
        window.addEventListener("resize", handleDismiss);
        window.addEventListener("keydown", handleKeyDown);
        return () => {
            window.removeEventListener("scroll", handleDismiss, true);
            window.removeEventListener("resize", handleDismiss);
            window.removeEventListener("keydown", handleKeyDown);
        };
    }, [open, close]);

    if (!content) {
        return <>{children}</>;
    }

    const transformValue =
        coords?.placement === "top" ? "translate(-50%, -100%)" : "translate(-50%, 0)";

    return (
        <>
            <span
                ref={triggerRef}
                className={className}
                aria-describedby={open ? tooltipId : undefined}
                onMouseEnter={scheduleOpen}
                onMouseLeave={close}
                onFocus={openNow}
                onBlur={close}
                onPointerDown={close}
            >
                {children}
            </span>

            {open &&
                coords &&
                createPortal(
                    <div
                        id={tooltipId}
                        role="tooltip"
                        style={{
                            top: `${coords.top}px`,
                            left: `${coords.left}px`,
                            transform: transformValue,
                        }}
                        className="pointer-events-none fixed z-[60] max-w-64 rounded-lg border border-zinc-700/90 bg-zinc-900/95 px-2.5 py-1.5 text-center text-xs font-medium leading-snug text-zinc-100 shadow-xl shadow-black/60 backdrop-blur-sm"
                    >
                        {content}
                    </div>,
                    document.body,
                )}
        </>
    );
}
