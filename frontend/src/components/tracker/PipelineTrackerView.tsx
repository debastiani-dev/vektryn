import { ExternalLink, StickyNote, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { vektrynApi } from "../../api/client";
import type { ApplicationLead, LeadPriority, LeadStatus } from "../../types/models";

const PIPELINE_STAGES: Array<{ id: LeadStatus; label: string }> = [
    { id: "discovered", label: "Discovered" },
    { id: "saved", label: "Saved" },
    { id: "applied", label: "Applied" },
    { id: "screening", label: "Screening" },
    { id: "interviewing", label: "Interviewing" },
    { id: "offer", label: "Offer" },
    { id: "rejected", label: "Rejected" },
    { id: "withdrawn", label: "Withdrawn" },
];

const PRIORITY_STYLES: Record<LeadPriority, string> = {
    low: "bg-zinc-800 text-zinc-400",
    medium: "bg-sky-500/15 text-sky-300",
    high: "bg-rose-500/15 text-rose-300",
};

function getNestedField(source: unknown, field: "title" | "company_name" | "apply_url"): string {
    if (typeof source === "object" && source !== null && field in source) {
        const val = (source as Record<string, unknown>)[field];
        if (typeof val === "string") return val;
    }
    return "";
}

export function PipelineTrackerView() {
    const [leads, setLeads] = useState<ApplicationLead[]>([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [editingNotesId, setEditingNotesId] = useState<string | null>(null);
    const [notesDraft, setNotesDraft] = useState("");
    const [deletingId, setDeletingId] = useState<string | null>(null);

    useEffect(() => {
        let cancelled = false;
        async function load() {
            setLoading(true);
            setError(null);
            try {
                const res = await vektrynApi.listLeads();
                if (!cancelled) setLeads(res.results);
            } catch (err) {
                if (!cancelled) {
                    setError(err instanceof Error ? err.message : "Failed to load application leads");
                }
            } finally {
                if (!cancelled) setLoading(false);
            }
        }
        void load();
        return () => {
            cancelled = true;
        };
    }, []);

    async function handleStatusChange(lead: ApplicationLead, nextStatus: LeadStatus) {
        if (lead.status === nextStatus) return;
        setError(null);
        try {
            const updated = await vektrynApi.updateLead(lead.uuid, { status: nextStatus });
            setLeads((prev) => prev.map((item) => (item.uuid === lead.uuid ? updated : item)));
        } catch (err) {
            setError(err instanceof Error ? err.message : "Failed to update lead status");
        }
    }

    async function handleSaveNotes(lead: ApplicationLead) {
        setError(null);
        try {
            const updated = await vektrynApi.updateLead(lead.uuid, { notes: notesDraft });
            setLeads((prev) => prev.map((item) => (item.uuid === lead.uuid ? updated : item)));
            setEditingNotesId(null);
        } catch (err) {
            setError(err instanceof Error ? err.message : "Failed to save notes");
        }
    }

    async function handleDeleteLead(lead: ApplicationLead) {
        setDeletingId(lead.uuid);
        setError(null);
        try {
            await vektrynApi.deleteLead(lead.uuid);
            setLeads((prev) => prev.filter((item) => item.uuid !== lead.uuid));
            if (editingNotesId === lead.uuid) {
                setEditingNotesId(null);
            }
        } catch (err) {
            const message = err instanceof Error ? err.message : String(err);
            if (message.includes("API 404")) {
                setLeads((prev) => prev.filter((item) => item.uuid !== lead.uuid));
            } else {
                setError(message || "Failed to remove lead");
            }
        } finally {
            setDeletingId(null);
        }
    }

    function startEditingNotes(lead: ApplicationLead) {
        setEditingNotesId(lead.uuid);
        setNotesDraft(lead.notes);
    }

    if (loading) {
        return <div className="py-16 text-center text-sm text-zinc-500">Loading application pipeline...</div>;
    }

    return (
        <div className="space-y-4">
            {error && (
                <div className="rounded-xl border border-red-500/30 bg-red-950/20 p-4 text-sm text-red-300">
                    {error}
                </div>
            )}

            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
                {PIPELINE_STAGES.map((stage) => {
                    const stageLeads = leads.filter((item) => item.status === stage.id);

                    return (
                        <section
                            key={stage.id}
                            className="flex flex-col rounded-xl border border-zinc-800 bg-zinc-900/40 p-3.5"
                        >
                            <div className="mb-3 flex items-center justify-between border-b border-zinc-800/80 pb-2.5">
                                <h2 className="text-xs font-semibold uppercase tracking-wider text-zinc-300">
                                    {stage.label}
                                </h2>
                                <span className="rounded-full bg-zinc-800 px-2 py-0.5 font-mono text-xs text-zinc-400">
                                    {stageLeads.length}
                                </span>
                            </div>

                            <div className="space-y-3">
                                {stageLeads.length === 0 && (
                                    <p className="py-6 text-center text-xs text-zinc-600">No leads in {stage.label}</p>
                                )}

                                {stageLeads.map((lead) => {
                                    const isEditingNotes = editingNotesId === lead.uuid;
                                    const isDeleting = deletingId === lead.uuid;
                                    const leadWithMeta = lead as ApplicationLead & {
                                        job_title?: string;
                                        company_name?: string;
                                        apply_url?: string;
                                    };
                                    const title =
                                        leadWithMeta.job_title ||
                                        getNestedField(lead.job_posting, "title") ||
                                        "Untitled Role";
                                    const companyName =
                                        leadWithMeta.company_name ||
                                        getNestedField(lead.job_posting, "company_name") ||
                                        "Unknown Company";
                                    const applyUrl =
                                        leadWithMeta.apply_url ||
                                        getNestedField(lead.job_posting, "apply_url") ||
                                        "#";

                                    return (
                                        <article
                                            key={lead.uuid}
                                            className="space-y-2.5 rounded-lg border border-zinc-800 bg-zinc-950/90 p-3"
                                        >
                                            <div className="flex items-start justify-between gap-2">
                                                <div>
                                                    <h3 className="text-sm font-medium text-zinc-100">
                                                        {title}
                                                    </h3>
                                                    <p className="text-xs text-zinc-400">{companyName}</p>
                                                </div>

                                                <span
                                                    className={`rounded px-1.5 py-0.5 font-mono text-[10px] uppercase ${PRIORITY_STYLES[lead.priority]
                                                        }`}
                                                >
                                                    {lead.priority}
                                                </span>
                                            </div>

                                            <div className="flex items-center justify-between gap-2 pt-1">
                                                <label htmlFor={`status-${lead.uuid}`} className="sr-only">
                                                    Move stage
                                                </label>
                                                <select
                                                    id={`status-${lead.uuid}`}
                                                    value={lead.status}
                                                    onChange={(e) => void handleStatusChange(lead, e.target.value as LeadStatus)}
                                                    className="rounded border border-zinc-800 bg-zinc-900 px-2 py-1 text-xs text-zinc-200 focus:border-violet-500 focus:outline-none"
                                                >
                                                    {PIPELINE_STAGES.map((opt) => (
                                                        <option key={opt.id} value={opt.id}>
                                                            {opt.label}
                                                        </option>
                                                    ))}
                                                </select>

                                                <div className="flex items-center gap-1.5">
                                                    <button
                                                        type="button"
                                                        onClick={() => startEditingNotes(lead)}
                                                        aria-label="Edit notes"
                                                        className="rounded p-1 text-zinc-400 hover:bg-zinc-800 hover:text-zinc-200"
                                                    >
                                                        <StickyNote className="h-3.5 w-3.5" />
                                                    </button>
                                                    <a
                                                        href={applyUrl}
                                                        target="_blank"
                                                        rel="noreferrer"
                                                        aria-label="Open job posting"
                                                        className="rounded p-1 text-zinc-400 hover:bg-zinc-800 hover:text-zinc-200"
                                                    >
                                                        <ExternalLink className="h-3.5 w-3.5" />
                                                    </a>
                                                    <button
                                                        type="button"
                                                        disabled={isDeleting}
                                                        onClick={() => void handleDeleteLead(lead)}
                                                        aria-label="Unsave lead"
                                                        title="Unsave / remove from tracker"
                                                        className="rounded p-1 text-zinc-400 hover:bg-red-950/50 hover:text-red-300 disabled:opacity-50"
                                                    >
                                                        <Trash2 className="h-3.5 w-3.5" />
                                                    </button>
                                                </div>
                                            </div>

                                            {isEditingNotes && (
                                                <div className="space-y-2 border-t border-zinc-800 pt-2">
                                                    <textarea
                                                        rows={2}
                                                        value={notesDraft}
                                                        onChange={(e) => setNotesDraft(e.target.value)}
                                                        placeholder="Recruiter contact, salary notes, prep..."
                                                        className="w-full rounded border border-zinc-700 bg-zinc-900 p-2 text-xs text-zinc-100 focus:border-violet-500 focus:outline-none"
                                                    />
                                                    <div className="flex justify-end gap-1.5">
                                                        <button
                                                            type="button"
                                                            onClick={() => setEditingNotesId(null)}
                                                            className="rounded px-2 py-1 text-xs text-zinc-400 hover:text-zinc-200"
                                                        >
                                                            Cancel
                                                        </button>
                                                        <button
                                                            type="button"
                                                            onClick={() => void handleSaveNotes(lead)}
                                                            className="rounded bg-violet-600 px-2.5 py-1 text-xs font-medium text-white hover:bg-violet-500"
                                                        >
                                                            Save
                                                        </button>
                                                    </div>
                                                </div>
                                            )}

                                            {!isEditingNotes && lead.notes && (
                                                <p className="border-t border-zinc-800/70 pt-2 text-xs text-zinc-400">
                                                    {lead.notes}
                                                </p>
                                            )}
                                        </article>
                                    );
                                })}
                            </div>
                        </section>
                    );
                })}
            </div>
        </div>
    );
}