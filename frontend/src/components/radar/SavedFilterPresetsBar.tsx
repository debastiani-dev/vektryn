import { Bookmark, Check, Loader2, Plus, Trash2, X } from "lucide-react";
import { useState } from "react";
import type { ResumeProfile, SavedFilter } from "../../types/models";
import { isPresetActive, type RadarFilterState } from "../../utils/savedFilters";
import { Tooltip } from "../ui/Tooltip";

interface SavedFilterPresetsBarProps {
    presets: ReadonlyArray<SavedFilter>;
    currentState: RadarFilterState;
    resumes: ReadonlyArray<ResumeProfile>;
    canSaveCurrent: boolean;
    saving: boolean;
    deletingId: string | null;
    error: string | null;
    onApplyPreset: (preset: SavedFilter) => void;
    onSavePreset: (name: string) => Promise<boolean>;
    onDeletePreset: (preset: SavedFilter) => void;
}

export function SavedFilterPresetsBar({
    presets,
    currentState,
    resumes,
    canSaveCurrent,
    saving,
    deletingId,
    error,
    onApplyPreset,
    onSavePreset,
    onDeletePreset,
}: Readonly<SavedFilterPresetsBarProps>) {
    const [creating, setCreating] = useState(false);
    const [nameDraft, setNameDraft] = useState("");

    async function handleSubmit() {
        const trimmed = nameDraft.trim();
        if (!trimmed || saving) return;
        const ok = await onSavePreset(trimmed);
        if (ok) {
            setNameDraft("");
            setCreating(false);
        }
    }

    return (
        <section
            aria-label="Saved filter presets"
            className="space-y-2 rounded-2xl border border-zinc-800/70 bg-zinc-900/30 px-4 py-3 ring-1 ring-inset ring-white/[0.02]"
        >
            <div className="flex flex-wrap items-center gap-2">
                <span className="inline-flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wider text-zinc-400">
                    <Bookmark className="h-3.5 w-3.5 text-violet-400" />
                    Presets
                </span>

                {presets.length === 0 && !creating && (
                    <span className="text-xs text-zinc-500">
                        Configure filters or search above and save a reusable preset.
                    </span>
                )}

                {presets.map((preset) => {
                    const active = isPresetActive(currentState, preset.query_params, resumes);
                    const isDeleting = deletingId === preset.uuid;
                    return (
                        <div
                            key={preset.uuid}
                            className={`inline-flex items-center overflow-hidden rounded-xl border text-xs font-medium transition ${
                                active
                                    ? "border-violet-500/45 bg-violet-500/15 text-violet-200"
                                    : "border-zinc-800 bg-zinc-950/70 text-zinc-300 hover:border-zinc-700 hover:text-zinc-100"
                            }`}
                        >
                            <Tooltip content={`Apply preset "${preset.name}"`}>
                                <button
                                    type="button"
                                    onClick={() => onApplyPreset(preset)}
                                    className="px-3 py-1.5 transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-500/70"
                                >
                                    {preset.name}
                                </button>
                            </Tooltip>
                            <Tooltip content={`Delete preset "${preset.name}"`}>
                                <button
                                    type="button"
                                    disabled={isDeleting}
                                    onClick={() => onDeletePreset(preset)}
                                    aria-label={`Delete preset ${preset.name}`}
                                    className="border-l border-zinc-800/80 px-2 py-1.5 text-zinc-500 transition hover:bg-red-950/40 hover:text-red-300 disabled:opacity-40"
                                >
                                    {isDeleting ? (
                                        <Loader2 className="h-3 w-3 animate-spin" />
                                    ) : (
                                        <Trash2 className="h-3 w-3" />
                                    )}
                                </button>
                            </Tooltip>
                        </div>
                    );
                })}

                {creating ? (
                    <div className="ml-auto flex flex-wrap items-center gap-1.5">
                        <input
                            type="text"
                            maxLength={80}
                            value={nameDraft}
                            onChange={(e) => setNameDraft(e.target.value)}
                            onKeyDown={(e) => {
                                if (e.key === "Enter") {
                                    void handleSubmit();
                                } else if (e.key === "Escape") {
                                    setCreating(false);
                                    setNameDraft("");
                                }
                            }}
                            placeholder="Preset name (e.g. BR Senior Python PJ)"
                            aria-label="New filter preset name"
                            className="h-8 w-60 rounded-lg border border-zinc-700 bg-zinc-950 px-2.5 text-xs text-zinc-100 placeholder:text-zinc-500 focus:border-violet-500 focus:outline-none focus:ring-2 focus:ring-violet-500/25"
                        />
                        <button
                            type="button"
                            disabled={saving || !nameDraft.trim()}
                            onClick={() => void handleSubmit()}
                            className="inline-flex h-8 items-center gap-1 rounded-lg bg-violet-600 px-2.5 text-xs font-medium text-white transition hover:bg-violet-500 disabled:opacity-50"
                        >
                            {saving ? (
                                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                            ) : (
                                <Check className="h-3.5 w-3.5" />
                            )}
                            Save
                        </button>
                        <button
                            type="button"
                            onClick={() => {
                                setCreating(false);
                                setNameDraft("");
                            }}
                            aria-label="Cancel saving preset"
                            className="inline-flex h-8 items-center justify-center rounded-lg px-2 text-zinc-400 transition hover:bg-zinc-800 hover:text-zinc-200"
                        >
                            <X className="h-3.5 w-3.5" />
                        </button>
                    </div>
                ) : (
                    <Tooltip
                        content={
                            canSaveCurrent
                                ? "Save the current search, filters, and sort order as a preset"
                                : "Apply at least one filter, search, or sort option to save a preset"
                        }
                        className="ml-auto inline-flex"
                    >
                        <button
                            type="button"
                            disabled={!canSaveCurrent}
                            onClick={() => setCreating(true)}
                            className="inline-flex items-center gap-1.5 rounded-xl border border-zinc-800 bg-zinc-950/70 px-3 py-1.5 text-xs font-medium text-zinc-300 transition hover:border-violet-500/40 hover:text-violet-200 disabled:cursor-not-allowed disabled:opacity-40"
                        >
                            <Plus className="h-3.5 w-3.5" />
                            Save Current Filter
                        </button>
                    </Tooltip>
                )}
            </div>

            {error && <p className="text-xs text-red-300">{error}</p>}
        </section>
    );
}
