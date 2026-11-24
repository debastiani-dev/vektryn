import { ChevronLeft, ChevronRight } from "lucide-react";
import { Tooltip } from "./Tooltip";

interface PaginationBarProps {
    page: number;
    pageSize?: number;
    totalCount: number;
    hasPrevious: boolean;
    hasNext: boolean;
    loading?: boolean;
    itemLabel?: string;
    onPageChange: (nextPage: number) => void;
}

export function PaginationBar({
    page,
    pageSize = 25,
    totalCount,
    hasPrevious,
    hasNext,
    loading = false,
    itemLabel = "items",
    onPageChange,
}: Readonly<PaginationBarProps>) {
    if (totalCount === 0) {
        return null;
    }

    const totalPages = Math.max(1, Math.ceil(totalCount / pageSize));
    const startItem = (page - 1) * pageSize + 1;
    const endItem = Math.min(totalCount, page * pageSize);

    return (
        <div className="flex flex-col items-center justify-between gap-4 rounded-2xl border border-zinc-800/80 bg-zinc-900/45 px-5 py-3.5 ring-1 ring-inset ring-white/[0.03] sm:flex-row">
            <p className="font-mono text-xs tabular-nums text-zinc-400">
                Showing {startItem}–{endItem} of {totalCount} {itemLabel}
            </p>

            <div className="flex items-center gap-2">
                <Tooltip content="Go to previous page">
                    <button
                        type="button"
                        disabled={!hasPrevious || loading}
                        onClick={() => onPageChange(Math.max(1, page - 1))}
                        className="inline-flex items-center gap-1.5 rounded-xl border border-zinc-800 bg-zinc-950/70 px-3.5 py-2 text-xs font-medium text-zinc-200 transition hover:border-zinc-700 hover:bg-zinc-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-500/70 disabled:cursor-not-allowed disabled:opacity-40"
                    >
                        <ChevronLeft className="h-4 w-4" />
                        Previous
                    </button>
                </Tooltip>

                <span className="px-3 font-mono text-xs tabular-nums text-zinc-400">
                    Page {page} / {totalPages}
                </span>

                <Tooltip content="Go to next page">
                    <button
                        type="button"
                        disabled={!hasNext || loading}
                        onClick={() => onPageChange(page + 1)}
                        className="inline-flex items-center gap-1.5 rounded-xl border border-zinc-800 bg-zinc-950/70 px-3.5 py-2 text-xs font-medium text-zinc-200 transition hover:border-zinc-700 hover:bg-zinc-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-500/70 disabled:cursor-not-allowed disabled:opacity-40"
                    >
                        Next
                        <ChevronRight className="h-4 w-4" />
                    </button>
                </Tooltip>
            </div>
        </div>
    );
}
