import { BellRing, ExternalLink, X } from "lucide-react";
import type { LiveMatchAlert } from "../../types/models";

interface LiveAlertBannerProps {
    alerts: LiveMatchAlert[];
    onDismiss: (eventId: string) => void;
}

export function LiveAlertBanner({ alerts, onDismiss }: LiveAlertBannerProps) {
    if (alerts.length === 0) {
        return null;
    }

    return (
        <div className="border-b border-violet-500/30 bg-violet-950/30 px-4 py-2.5">
            <div className="mx-auto flex max-w-7xl flex-col gap-2">
                {alerts.slice(0, 3).map((alert) => (
                    <div
                        key={alert.event_id}
                        className="flex items-center justify-between gap-4 rounded-lg border border-violet-500/30 bg-zinc-900/90 px-3.5 py-2 text-sm"
                    >
                        <div className="flex min-w-0 items-center gap-3">
                            <BellRing className="h-4 w-4 shrink-0 text-violet-400" />
                            <span className="rounded bg-emerald-500/15 px-2 py-0.5 font-mono text-xs font-semibold text-emerald-300">
                                {alert.fit_score}% fit
                            </span>
                            <span className="truncate font-medium text-zinc-100">{alert.title}</span>
                            <span className="shrink-0 text-zinc-400">at {alert.company_name}</span>
                        </div>

                        <div className="flex shrink-0 items-center gap-2">
                            <a
                                href={alert.apply_url}
                                target="_blank"
                                rel="noreferrer"
                                className="inline-flex items-center gap-1 rounded-md bg-violet-600 px-2.5 py-1 text-xs font-medium text-white hover:bg-violet-500"
                            >
                                Apply <ExternalLink className="h-3 w-3" />
                            </a>
                            <button
                                type="button"
                                onClick={() => onDismiss(alert.event_id)}
                                aria-label="Dismiss alert"
                                className="rounded p-1 text-zinc-400 hover:bg-zinc-800 hover:text-zinc-200"
                            >
                                <X className="h-4 w-4" />
                            </button>
                        </div>
                    </div>
                ))}
            </div>
        </div>
    );
}