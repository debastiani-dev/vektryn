import type { CSSProperties } from "react";

export interface PopoverCoords {
    top: number;
    left: number;
    width: number;
    maxHeight: number;
}

export interface PopoverPositionOptions {
    desktopWidth?: number;
    mobileWidth?: number;
    minWidth?: number;
    offsetY?: number;
}

export interface VisualViewportRect {
    top: number;
    left: number;
    width: number;
    height: number;
}

export interface DrawerLayoutResult {
    isCompact: boolean;
    overlayStyle: CSSProperties;
    panelStyle: CSSProperties;
}

const COMPACT_DRAWER_BREAKPOINT_PX = 768;

export function readVisualViewportRect(): VisualViewportRect | null {
    if (typeof globalThis.window === "undefined") {
        return null;
    }
    const vv = globalThis.window.visualViewport;
    if (vv && vv.width > 0 && vv.height > 0) {
        return {
            top: Math.max(0, Math.round(vv.offsetTop)),
            left: Math.max(0, Math.round(vv.offsetLeft)),
            width: Math.round(vv.width),
            height: Math.round(vv.height),
        };
    }
    const width = document.documentElement?.clientWidth || globalThis.window.innerWidth;
    const height = document.documentElement?.clientHeight || globalThis.window.innerHeight;
    return { top: 0, left: 0, width, height };
}

export function computeDrawerLayout(
    viewport: VisualViewportRect,
    desktopMaxWidthPx: number,
): DrawerLayoutResult {
    const isCompact = viewport.width < COMPACT_DRAWER_BREAKPOINT_PX;
    const panelWidth = isCompact
        ? viewport.width
        : Math.min(desktopMaxWidthPx, viewport.width);

    const overlayStyle: CSSProperties = {
        top: `${viewport.top}px`,
        left: `${viewport.left}px`,
        width: `${viewport.width}px`,
        height: `${viewport.height}px`,
    };

    const panelStyle: CSSProperties = isCompact
        ? {
              top: 0,
              left: 0,
              right: "auto",
              bottom: "auto",
              width: `${panelWidth}px`,
              height: `${viewport.height}px`,
          }
        : {
              top: 0,
              right: 0,
              left: "auto",
              bottom: "auto",
              width: `${panelWidth}px`,
              height: `${viewport.height}px`,
          };

    return { isCompact, overlayStyle, panelStyle };
}

export function computePopoverCoords(
    triggerRect: Pick<DOMRect, "right" | "bottom">,
    viewportWidth: number,
    viewportHeight: number,
    options: PopoverPositionOptions = {},
): PopoverCoords {
    const margin = 12;
    const desktopWidth = options.desktopWidth ?? 400;
    const mobileWidth = options.mobileWidth ?? 340;
    const minWidth = options.minWidth ?? 240;
    const offsetY = options.offsetY ?? 10;

    const desiredWidth = viewportWidth >= 640 ? desktopWidth : mobileWidth;
    const width = Math.max(minWidth, Math.min(desiredWidth, viewportWidth - margin * 2));
    const idealLeft = triggerRect.right - width;
    const left = Math.max(margin, Math.min(idealLeft, viewportWidth - width - margin));
    const top = Math.max(margin, Math.min(triggerRect.bottom + offsetY, viewportHeight - 200));
    const maxHeight = Math.max(220, viewportHeight - top - margin);
    return { top, left, width, maxHeight };
}
