interface VektrynLogoProps {
    className?: string;
    animated?: boolean;
}

/**
 * Minimal Orbital Scan radar mark for Vektryn:
 * Concentric opposing sweep arcs with a center pivot and orbit-aligned signal contact.
 */
export function VektrynLogo({
    className = "h-5 w-5",
    animated = false,
}: Readonly<VektrynLogoProps>) {
    return (
        <svg
            viewBox="0 0 32 32"
            fill="none"
            xmlns="http://www.w3.org/2000/svg"
            className={className}
            aria-hidden="true"
        >
            <g className={animated ? "vk-orbit-cw" : undefined}>
                <path
                    d="M2.5 16A13.5 13.5 0 0 1 16 2.5"
                    stroke="#f4f4f5"
                    strokeWidth="2.8"
                    strokeLinecap="round"
                />
                <path
                    d="M29.5 16A13.5 13.5 0 0 1 16 29.5"
                    stroke="#f4f4f5"
                    strokeWidth="2.8"
                    strokeLinecap="round"
                />
                {animated && (
                    <circle
                        cx="25.55"
                        cy="6.45"
                        r="3.1"
                        fill="#a78bfa"
                        className="vk-blip-ping"
                    />
                )}
                <circle cx="25.55" cy="6.45" r="3.1" fill="#a78bfa" />
            </g>
            <g className={animated ? "vk-orbit-ccw" : undefined}>
                <path
                    d="M8.6 16A7.4 7.4 0 0 1 16 8.6"
                    stroke="#f4f4f5"
                    strokeOpacity="0.45"
                    strokeWidth="2.4"
                    strokeLinecap="round"
                />
                <path
                    d="M23.4 16A7.4 7.4 0 0 1 16 23.4"
                    stroke="#f4f4f5"
                    strokeOpacity="0.45"
                    strokeWidth="2.4"
                    strokeLinecap="round"
                />
            </g>
            <circle cx="16" cy="16" r="2.6" fill="#f4f4f5" />
        </svg>
    );
}
