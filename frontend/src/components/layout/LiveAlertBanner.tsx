import { BellRing, ExternalLink, Mail, X } from "lucide-react";
import type { LiveMatchAlert } from "../../types/models";
import {
    formatApplyLinkLabel,
    formatApplyLinkTooltip,
    isMailtoUrl,
    scoreBadgeStyle,
} from "../../utils/format";
import { getAlertDedupeKey } from "../../utils/notifications";
import { Tooltip } from "../ui/Tooltip";

interface LiveAlertBannerProps {
    alerts: LiveMatchAlert[];
    onDismiss: (eventId: string) => void;
}

export function LiveAlertBanner({ alerts, onDismiss }: Readonly<LiveAlertBannerProps>) {
    if (alerts.length === 0) {
        return null;
    }

    return (
        <aside
            aria-label="Live match alerts"
            aria-live="polite"
            className="pointer-events-none fixed top-20 right-4 z-40 flex w-[calc(100%-2rem)] max-w-md flex-col gap-3 sm:right-8"
        >
            {alerts.slice(0, 3).map((alert) => {
                const simPct = (alert.cosine_similarity * 100).toFixed(0);
                const alertKey = getAlertDedupeKey(alert);
                return (
                    <div
                        key={alertKey}
                        className="animate-toast-in pointer-events-auto rounded-2xl border border-violet-500/35 bg-zinc-900/95 p-4 shadow-2xl shadow-black/60 ring-1 ring-inset ring-white/[0.05] backdrop-blur-md"
                    >
                        <div className="flex items-start justify-between gap-3">
                            <div className="min-w-0 flex-1 space-y-1.5">
                                <div className="flex flex-wrap items-center gap-2">
                                    <span className="inline-flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider text-violet-300">
                                        <BellRing className="h-3.5 w-3.5" />
                                        Live Match
                                    </span>
                                    <Tooltip
                                        content={`AI fit score: ${alert.fit_score}% · Vector similarity: ${simPct}%`}
                                        side="bottom"
                                    >
                                        <span
                                            className={`rounded-md px-2 py-0.5 font-mono text-xs font-semibold tabular-nums ${scoreBadgeStyle(
                                                alert.fit_score,
                                            )}`}
                                        >
                                            {alert.fit_score}% Fit
                                        </span>
                                    </Tooltip>
                                </div>

                                <p className="truncate text-sm font-semibold text-zinc-100">
                                    {alert.title}
                                </p>
                                <p className="truncate text-xs text-zinc-400">
                                    {alert.company_name}
                                </p>
                            </div>

                            <Tooltip content="Dismiss live alert" side="bottom">
                                <button
                                    type="button"
                                    onClick={() => onDismiss(alertKey)}
                                    aria-label="Dismiss alert"
                                    className="rounded-lg p-1.5 text-zinc-400 transition hover:bg-zinc-800 hover:text-zinc-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-500/70"
                                >
                                    <X className="h-4 w-4" />
                                </button>
                            </Tooltip>
                        </div>

                        <div className="mt-3 flex items-center justify-end gap-2 border-t border-zinc-800/80 pt-3">
                            <Tooltip content={formatApplyLinkTooltip(alert.apply_url)}>
                                <a
                                    href={alert.apply_url}
                                    target={isMailtoUrl(alert.apply_url) ? undefined : "_blank"}
                                    rel={isMailtoUrl(alert.apply_url) ? undefined : "noreferrer"}
                                    className="inline-flex items-center gap-1.5 rounded-lg bg-violet-600 px-3 py-1.5 text-xs font-medium text-white transition hover:bg-violet-500 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-500/70"
                                >
                                    {formatApplyLinkLabel(alert.apply_url, "Apply Now")}{" "}
                                    {isMailtoUrl(alert.apply_url) ? (
                                        <Mail className="h-3.5 w-3.5" />
                                    ) : (
                                        <ExternalLink className="h-3.5 w-3.5" />
                                    )}
                                </a>
                            </Tooltip>
                        </div>
                    </div>
                );
            })}
        </aside>
    );
}
