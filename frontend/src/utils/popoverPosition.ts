export interface PopoverCoords {
    top: number;
    left: number;
    width: number;
    maxHeight: number;
}

export function computePopoverCoords(
    triggerRect: Pick<DOMRect, "right" | "bottom">,
    viewportWidth: number,
    viewportHeight: number,
): PopoverCoords {
    const margin = 12;
    const desiredWidth = viewportWidth >= 640 ? 400 : 340;
    const width = Math.max(240, Math.min(desiredWidth, viewportWidth - margin * 2));
    const idealLeft = triggerRect.right - width;
    const left = Math.max(margin, Math.min(idealLeft, viewportWidth - width - margin));
    const top = Math.max(margin, Math.min(triggerRect.bottom + 10, viewportHeight - 200));
    const maxHeight = Math.max(220, viewportHeight - top - margin);
    return { top, left, width, maxHeight };
}
