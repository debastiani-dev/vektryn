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
