import {
    CheckCircle2,
    FileText,
    FileUp,
    PauseCircle,
    Pencil,
    PlayCircle,
    Plus,
    Sparkles,
    Trash2,
    X,
} from "lucide-react";
import { type FormEvent, useEffect, useState } from "react";
import { vektrynApi } from "../../api/client";
import type { ContractType, ResumeProfile, SeniorityLevel } from "../../types/models";
import {
    formatContractType,
    formatExactDate,
    formatRegionEligibility,
    formatSeniority,
} from "../../utils/format";
import { Tooltip } from "../ui/Tooltip";

const SENIORITY_OPTIONS: SeniorityLevel[] = [
    "junior",
    "mid",
    "senior",
    "staff",
    "principal",
    "lead",
    "manager",
];

const CONTRACT_OPTIONS: ContractType[] = [
    "clt",
    "pj",
    "b2b_contractor",
    "w2",
    "c2c",
    "eor",
];

const REGION_OPTIONS: string[] = [
    "brazil",
    "latam",
    "worldwide",
    "north_america",
    "americas",
    "europe",
    "emea",
    "apac",
];

function toggleItem<T>(list: T[], item: T): T[] {
    return list.includes(item) ? list.filter((v) => v !== item) : [...list, item];
}

interface ResumeCardProps {
    profile: ResumeProfile;
    busy: boolean;
    onEdit: (profile: ResumeProfile) => void;
    onToggleActive: (profile: ResumeProfile) => void;
    onDelete: (profile: ResumeProfile) => void;
}

function ResumeProfileCard({
    profile,
    busy,
    onEdit,
    onToggleActive,
    onDelete,
}: Readonly<ResumeCardProps>) {
    const updatedDate = formatExactDate(profile.modified_at);
    const activeToggleTooltip = profile.is_active
        ? "Pause scoring incoming jobs against this resume"
        : "Activate scoring incoming jobs against this resume";

    return (
        <article className="space-y-5 rounded-2xl border border-zinc-800/90 bg-zinc-900/55 p-6 ring-1 ring-inset ring-white/[0.03] transition hover:border-zinc-700/90">
            <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
                <div className="min-w-0 space-y-2">
                    <div className="flex flex-wrap items-center gap-2">
                        <Tooltip
                            content={
                                profile.is_active
                                    ? "Actively scored against incoming jobs"
                                    : "Paused — skipped by matching worker"
                            }
                        >
                            <span
                                className={`inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1 text-xs font-medium ring-1 ${profile.is_active
                                        ? "bg-emerald-500/12 text-emerald-300 ring-emerald-500/30"
                                        : "bg-zinc-800 text-zinc-400 ring-zinc-700"
                                    }`}
                            >
                                <span
                                    className={`h-1.5 w-1.5 rounded-full ${profile.is_active ? "bg-emerald-400" : "bg-zinc-500"
                                        }`}
                                />
                                {profile.is_active ? "Active" : "Paused"}
                            </span>
                        </Tooltip>

                        <Tooltip
                            content={
                                profile.has_embedding
                                    ? "768-dim Gemini embedding ready for pgvector cosine matching"
                                    : "No embedding computed yet — check GEMINI_API_KEY"
                            }
                        >
                            <span
                                className={`inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1 text-xs font-medium ring-1 ${profile.has_embedding
                                        ? "bg-violet-500/12 text-violet-300 ring-violet-500/30"
                                        : "bg-amber-500/12 text-amber-300 ring-amber-500/30"
                                    }`}
                            >
                                <Sparkles className="h-3.5 w-3.5" />
                                {profile.has_embedding ? "Embedded" : "No Embedding"}
                            </span>
                        </Tooltip>

                        <Tooltip content="Minimum AI fit score required to trigger live SSE match alerts">
                            <span className="rounded-lg bg-zinc-800/80 px-2.5 py-1 font-mono text-xs tabular-nums text-zinc-300">
                                Alert &ge; {profile.min_alert_score}%
                            </span>
                        </Tooltip>
                    </div>

                    <h2 className="text-lg font-semibold text-zinc-100">{profile.label}</h2>

                    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-zinc-500">
                        {updatedDate && <span>Updated {updatedDate}</span>}
                        {profile.source_file_gcs_uri && (
                            <Tooltip content={profile.source_file_gcs_uri}>
                                <span className="inline-flex items-center gap-1 text-zinc-400">
                                    <CheckCircle2 className="h-3.5 w-3.5 text-emerald-400" />
                                    File snapshot stored
                                </span>
                            </Tooltip>
                        )}
                    </div>
                </div>

                <div className="flex shrink-0 items-center gap-2">
                    <Tooltip content={activeToggleTooltip}>
                        <button
                            type="button"
                            disabled={busy}
                            onClick={() => onToggleActive(profile)}
                            aria-label={profile.is_active ? "Pause profile" : "Activate profile"}
                            className="inline-flex items-center gap-1.5 rounded-xl border border-zinc-800 bg-zinc-900 px-3 py-2 text-xs font-medium text-zinc-300 transition hover:border-zinc-700 hover:bg-zinc-800 hover:text-zinc-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-500/70 disabled:opacity-50"
                        >
                            {profile.is_active ? (
                                <>
                                    <PauseCircle className="h-4 w-4 text-amber-400" />
                                    Pause
                                </>
                            ) : (
                                <>
                                    <PlayCircle className="h-4 w-4 text-emerald-400" />
                                    Activate
                                </>
                            )}
                        </button>
                    </Tooltip>

                    <Tooltip content="Edit resume text, upload new file, or adjust target filters">
                        <button
                            type="button"
                            disabled={busy}
                            onClick={() => onEdit(profile)}
                            aria-label="Edit resume profile"
                            className="rounded-xl border border-zinc-800 bg-zinc-900 p-2 text-zinc-300 transition hover:border-zinc-700 hover:bg-zinc-800 hover:text-zinc-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-500/70 disabled:opacity-50"
                        >
                            <Pencil className="h-4 w-4" />
                        </button>
                    </Tooltip>

                    <Tooltip content="Delete resume profile">
                        <button
                            type="button"
                            disabled={busy}
                            onClick={() => onDelete(profile)}
                            aria-label="Delete resume profile"
                            className="rounded-xl border border-zinc-800 bg-zinc-900 p-2 text-zinc-400 transition hover:border-red-500/40 hover:bg-red-950/40 hover:text-red-300 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-red-500/60 disabled:opacity-50"
                        >
                            <Trash2 className="h-4 w-4" />
                        </button>
                    </Tooltip>
                </div>
            </div>

            <div className="grid gap-4 border-t border-zinc-800/70 pt-4 sm:grid-cols-3">
                <div className="space-y-1.5">
                    <p className="text-[11px] font-semibold uppercase tracking-wider text-zinc-500">
                        Target Seniority
                    </p>
                    <div className="flex flex-wrap gap-1.5">
                        {profile.target_seniority.length > 0 ? (
                            profile.target_seniority.map((level) => (
                                <span
                                    key={level}
                                    className="rounded-md bg-zinc-800/80 px-2 py-0.5 text-xs text-zinc-300"
                                >
                                    {formatSeniority(level)}
                                </span>
                            ))
                        ) : (
                            <span className="text-xs text-zinc-500">Any</span>
                        )}
                    </div>
                </div>

                <div className="space-y-1.5">
                    <p className="text-[11px] font-semibold uppercase tracking-wider text-zinc-500">
                        Target Contracts
                    </p>
                    <div className="flex flex-wrap gap-1.5">
                        {profile.target_contract_types.length > 0 ? (
                            profile.target_contract_types.map((contract) => (
                                <span
                                    key={contract}
                                    className="rounded-md bg-zinc-800/80 px-2 py-0.5 text-xs text-zinc-300"
                                >
                                    {formatContractType(contract)}
                                </span>
                            ))
                        ) : (
                            <span className="text-xs text-zinc-500">Any</span>
                        )}
                    </div>
                </div>

                <div className="space-y-1.5">
                    <p className="text-[11px] font-semibold uppercase tracking-wider text-zinc-500">
                        Target Regions
                    </p>
                    <div className="flex flex-wrap gap-1.5">
                        {profile.target_regions.length > 0 ? (
                            profile.target_regions.map((region) => (
                                <span
                                    key={region}
                                    className="rounded-md bg-sky-500/12 px-2 py-0.5 text-xs text-sky-300 ring-1 ring-sky-500/25"
                                >
                                    {formatRegionEligibility(region)}
                                </span>
                            ))
                        ) : (
                            <span className="text-xs text-zinc-500">Any</span>
                        )}
                    </div>
                </div>
            </div>

            {profile.extracted_skills.length > 0 && (
                <div className="space-y-2 border-t border-zinc-800/70 pt-4">
                    <p className="text-[11px] font-semibold uppercase tracking-wider text-zinc-500">
                        Extracted Skills ({profile.extracted_skills.length})
                    </p>
                    <div className="flex flex-wrap gap-1.5">
                        {profile.extracted_skills.slice(0, 18).map((skill) => (
                            <span
                                key={skill}
                                className="rounded-md border border-emerald-500/25 bg-emerald-500/10 px-2.5 py-0.5 font-mono text-xs text-emerald-200"
                            >
                                {skill}
                            </span>
                        ))}
                        {profile.extracted_skills.length > 18 && (
                            <Tooltip
                                content={`Additional skills: ${profile.extracted_skills.slice(18).join(", ")}`}
                            >
                                <span className="rounded-md border border-zinc-800 bg-zinc-900 px-2.5 py-0.5 font-mono text-xs tabular-nums text-zinc-400">
                                    +{profile.extracted_skills.length - 18} more
                                </span>
                            </Tooltip>
                        )}
                    </div>
                </div>
            )}
        </article>
    );
}

export function ResumesView() {
    const [profiles, setProfiles] = useState<ResumeProfile[]>([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [busyId, setBusyId] = useState<string | null>(null);
    const [formOpen, setFormOpen] = useState(false);
    const [editingProfile, setEditingProfile] = useState<ResumeProfile | null>(null);
    const [submitting, setSubmitting] = useState(false);

    const [label, setLabel] = useState("");
    const [rawText, setRawText] = useState("");
    const [selectedFile, setSelectedFile] = useState<File | null>(null);
    const [minAlertScore, setMinAlertScore] = useState(70);
    const [targetSeniority, setTargetSeniority] = useState<SeniorityLevel[]>([]);
    const [targetContracts, setTargetContracts] = useState<ContractType[]>([]);
    const [targetRegions, setTargetRegions] = useState<string[]>([]);
    const [isActive, setIsActive] = useState(true);

    useEffect(() => {
        let cancelled = false;
        vektrynApi
            .listResumes()
            .then((res) => {
                if (!cancelled) {
                    setProfiles(res.results);
                }
            })
            .catch((err) => {
                if (!cancelled) {
                    setError(
                        err instanceof Error ? err.message : "Failed to load resume profiles",
                    );
                }
            })
            .finally(() => {
                if (!cancelled) {
                    setLoading(false);
                }
            });

        return () => {
            cancelled = true;
        };
    }, []);

    function openCreateForm() {
        setEditingProfile(null);
        setLabel("");
        setRawText("");
        setSelectedFile(null);
        setMinAlertScore(70);
        setTargetSeniority([]);
        setTargetContracts([]);
        setTargetRegions([]);
        setIsActive(true);
        setError(null);
        setFormOpen(true);
    }

    function openEditForm(profile: ResumeProfile) {
        setEditingProfile(profile);
        setLabel(profile.label);
        setRawText(profile.raw_text);
        setSelectedFile(null);
        setMinAlertScore(profile.min_alert_score);
        setTargetSeniority(profile.target_seniority);
        setTargetContracts(profile.target_contract_types);
        setTargetRegions(profile.target_regions);
        setIsActive(profile.is_active);
        setError(null);
        setFormOpen(true);
    }

    async function handleSubmit(event: FormEvent<HTMLFormElement>) {
        event.preventDefault();
        if (!label.trim()) {
            setError("Profile label is required.");
            return;
        }
        if (!editingProfile && !selectedFile && !rawText.trim()) {
            setError("Upload a resume file (.pdf, .docx, .txt, .md) or paste resume text.");
            return;
        }

        setSubmitting(true);
        setError(null);
        try {
            const payload = {
                label: label.trim(),
                raw_text: selectedFile ? undefined : rawText,
                file: selectedFile,
                min_alert_score: minAlertScore,
                target_seniority: targetSeniority,
                target_contract_types: targetContracts,
                target_regions: targetRegions,
                is_active: isActive,
            };

            if (editingProfile) {
                const updated = await vektrynApi.updateResume(editingProfile.uuid, payload);
                setProfiles((prev) =>
                    prev.map((item) => (item.uuid === updated.uuid ? updated : item)),
                );
            } else {
                const created = await vektrynApi.createResume(payload);
                setProfiles((prev) => [created, ...prev]);
            }
            setFormOpen(false);
            setEditingProfile(null);
        } catch (err) {
            setError(err instanceof Error ? err.message : "Failed to save resume profile");
        } finally {
            setSubmitting(false);
        }
    }

    async function handleToggleActive(profile: ResumeProfile) {
        setBusyId(profile.uuid);
        setError(null);
        try {
            const updated = await vektrynApi.updateResume(profile.uuid, {
                is_active: !profile.is_active,
            });
            setProfiles((prev) =>
                prev.map((item) => (item.uuid === updated.uuid ? updated : item)),
            );
        } catch (err) {
            setError(err instanceof Error ? err.message : "Failed to update profile status");
        } finally {
            setBusyId(null);
        }
    }

    async function handleDelete(profile: ResumeProfile) {
        setBusyId(profile.uuid);
        setError(null);
        try {
            await vektrynApi.deleteResume(profile.uuid);
            setProfiles((prev) => prev.filter((item) => item.uuid !== profile.uuid));
        } catch (err) {
            setError(err instanceof Error ? err.message : "Failed to delete resume profile");
        } finally {
            setBusyId(null);
        }
    }

    const activeCount = profiles.filter((p) => p.is_active).length;
    const embeddedCount = profiles.filter((p) => p.has_embedding).length;
    const uniqueSkillsCount = new Set(profiles.flatMap((p) => p.extracted_skills)).size;
    let submitLabel = "Create Profile";
    if (submitting) {
        submitLabel = "Embedding & Saving...";
    } else if (editingProfile) {
        submitLabel = "Save Changes";
    }

    function renderProfilesList() {
        if (loading) {
            return (
                <div className="grid gap-5">
                    {[0, 1].map((idx) => (
                        <div
                            key={idx}
                            className="h-44 animate-pulse rounded-2xl border border-zinc-800/80 bg-zinc-900/45 p-6"
                        />
                    ))}
                </div>
            );
        }
        if (profiles.length === 0) {
            return (
                <div className="flex flex-col items-center justify-center gap-4 rounded-2xl border border-zinc-800/90 bg-zinc-900/40 px-6 py-20 text-center ring-1 ring-inset ring-white/[0.03]">
                    <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-zinc-900 ring-1 ring-zinc-800">
                        <FileText className="h-5 w-5 text-zinc-500" />
                    </div>
                    <div className="space-y-1">
                        <p className="text-base font-medium text-zinc-200">No resume profiles yet</p>
                        <p className="text-sm text-zinc-400">
                            Upload a resume or paste your background to start semantic scoring against incoming jobs.
                        </p>
                    </div>
                    <button
                        type="button"
                        onClick={openCreateForm}
                        className="inline-flex items-center gap-2 rounded-xl bg-violet-600 px-4 py-2.5 text-sm font-medium text-white transition hover:bg-violet-500"
                    >
                        <Plus className="h-4 w-4" />
                        Create First Profile
                    </button>
                </div>
            );
        }
        return (
            <div className="grid gap-5">
                {profiles.map((profile) => (
                    <ResumeProfileCard
                        key={profile.uuid}
                        profile={profile}
                        busy={busyId === profile.uuid}
                        onEdit={openEditForm}
                        onToggleActive={(p) => void handleToggleActive(p)}
                        onDelete={(p) => void handleDelete(p)}
                    />
                ))}
            </div>
        );
    }

    return (
        <div className="space-y-8">
            <header className="space-y-6">
                <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
                    <div className="space-y-1">
                        <h1 className="text-2xl font-semibold tracking-tight text-zinc-100">
                            Resume Profiles
                        </h1>
                        <p className="text-sm text-zinc-400">
                            Manage target search profiles, upload PDF/DOCX resumes, and tune alert thresholds.
                        </p>
                    </div>

                    <Tooltip content="Create a new resume profile with embedding and skill extraction">
                        <button
                            type="button"
                            onClick={openCreateForm}
                            className="inline-flex items-center gap-2 self-start rounded-xl bg-violet-600 px-4 py-2.5 text-sm font-medium text-white shadow-sm shadow-violet-600/20 transition hover:bg-violet-500 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-500/70 sm:self-auto"
                        >
                            <Plus className="h-4 w-4" />
                            New Resume Profile
                        </button>
                    </Tooltip>
                </div>

                <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
                    <div className="rounded-2xl border border-zinc-800/90 bg-zinc-900/45 px-5 py-4 ring-1 ring-inset ring-white/[0.03]">
                        <p className="text-xs font-medium uppercase tracking-wider text-zinc-400">
                            Total Profiles
                        </p>
                        <p className="mt-2 font-mono text-2xl font-semibold tabular-nums text-zinc-100">
                            {loading ? "—" : profiles.length}
                        </p>
                    </div>
                    <div className="rounded-2xl border border-emerald-500/20 bg-emerald-950/15 px-5 py-4 ring-1 ring-inset ring-white/[0.03]">
                        <p className="text-xs font-medium uppercase tracking-wider text-emerald-300/80">
                            Active Profiles
                        </p>
                        <p className="mt-2 font-mono text-2xl font-semibold tabular-nums text-emerald-300">
                            {loading ? "—" : activeCount}
                        </p>
                    </div>
                    <div className="rounded-2xl border border-violet-500/20 bg-violet-950/15 px-5 py-4 ring-1 ring-inset ring-white/[0.03]">
                        <p className="text-xs font-medium uppercase tracking-wider text-violet-300/80">
                            Vector Embedded
                        </p>
                        <p className="mt-2 font-mono text-2xl font-semibold tabular-nums text-violet-300">
                            {loading ? "—" : embeddedCount}
                        </p>
                    </div>
                    <div className="rounded-2xl border border-zinc-800/90 bg-zinc-900/45 px-5 py-4 ring-1 ring-inset ring-white/[0.03]">
                        <p className="text-xs font-medium uppercase tracking-wider text-zinc-400">
                            Extracted Skills
                        </p>
                        <p className="mt-2 font-mono text-2xl font-semibold tabular-nums text-sky-300">
                            {loading ? "—" : uniqueSkillsCount}
                        </p>
                    </div>
                </div>
            </header>

            {error && (
                <div className="rounded-2xl border border-red-500/30 bg-red-950/20 px-5 py-4 text-sm text-red-300">
                    {error}
                </div>
            )}

            {formOpen && (
                <form
                    onSubmit={(e) => void handleSubmit(e)}
                    className="space-y-6 rounded-2xl border border-violet-500/30 bg-zinc-900/70 p-6 ring-1 ring-inset ring-white/[0.04] sm:p-7"
                >
                    <div className="flex items-center justify-between border-b border-zinc-800 pb-4">
                        <h2 className="text-base font-semibold text-zinc-100">
                            {editingProfile ? `Edit "${editingProfile.label}"` : "New Resume Profile"}
                        </h2>
                        <button
                            type="button"
                            onClick={() => setFormOpen(false)}
                            aria-label="Close form"
                            className="rounded-lg p-1.5 text-zinc-400 transition hover:bg-zinc-800 hover:text-zinc-100"
                        >
                            <X className="h-4 w-4" />
                        </button>
                    </div>

                    <div className="grid gap-5 sm:grid-cols-2">
                        <div className="space-y-1.5">
                            <label
                                htmlFor="resume-label"
                                className="block text-xs font-medium uppercase tracking-wider text-zinc-400"
                            >
                                Profile Label
                            </label>
                            <input
                                id="resume-label"
                                type="text"
                                value={label}
                                onChange={(e) => setLabel(e.target.value)}
                                placeholder="Senior Python / Django Backend"
                                className="w-full rounded-xl border border-zinc-800 bg-zinc-950/80 px-4 py-2.5 text-sm text-zinc-100 placeholder:text-zinc-600 focus:border-violet-500 focus:outline-none focus:ring-2 focus:ring-violet-500/25"
                            />
                        </div>

                        <div className="space-y-1.5">
                            <label
                                htmlFor="resume-alert-score"
                                className="flex items-center justify-between text-xs font-medium uppercase tracking-wider text-zinc-400"
                            >
                                <span>Min Alert Fit Score</span>
                                <span className="font-mono text-violet-300 tabular-nums">
                                    {minAlertScore}%
                                </span>
                            </label>
                            <input
                                id="resume-alert-score"
                                type="range"
                                min={0}
                                max={100}
                                step={5}
                                value={minAlertScore}
                                onChange={(e) => setMinAlertScore(Number(e.target.value))}
                                className="mt-2 w-full accent-violet-500"
                            />
                        </div>
                    </div>

                    <div className="space-y-4">
                        <div className="space-y-2">
                            <p className="text-xs font-medium uppercase tracking-wider text-zinc-400">
                                Target Seniority
                            </p>
                            <div className="flex flex-wrap gap-2">
                                {SENIORITY_OPTIONS.map((level) => {
                                    const active = targetSeniority.includes(level);
                                    return (
                                        <button
                                            key={level}
                                            type="button"
                                            onClick={() =>
                                                setTargetSeniority((prev) => toggleItem(prev, level))
                                            }
                                            className={`rounded-lg px-3 py-1.5 text-xs font-medium transition ${active
                                                    ? "bg-violet-600 text-white"
                                                    : "border border-zinc-800 bg-zinc-950/70 text-zinc-400 hover:text-zinc-200"
                                                }`}
                                        >
                                            {formatSeniority(level)}
                                        </button>
                                    );
                                })}
                            </div>
                        </div>

                        <div className="space-y-2">
                            <p className="text-xs font-medium uppercase tracking-wider text-zinc-400">
                                Target Contract Types
                            </p>
                            <div className="flex flex-wrap gap-2">
                                {CONTRACT_OPTIONS.map((contract) => {
                                    const active = targetContracts.includes(contract);
                                    return (
                                        <button
                                            key={contract}
                                            type="button"
                                            onClick={() =>
                                                setTargetContracts((prev) =>
                                                    toggleItem(prev, contract),
                                                )
                                            }
                                            className={`rounded-lg px-3 py-1.5 text-xs font-medium transition ${active
                                                    ? "bg-violet-600 text-white"
                                                    : "border border-zinc-800 bg-zinc-950/70 text-zinc-400 hover:text-zinc-200"
                                                }`}
                                        >
                                            {formatContractType(contract)}
                                        </button>
                                    );
                                })}
                            </div>
                        </div>

                        <div className="space-y-2">
                            <p className="text-xs font-medium uppercase tracking-wider text-zinc-400">
                                Target Regions
                            </p>
                            <div className="flex flex-wrap gap-2">
                                {REGION_OPTIONS.map((region) => {
                                    const active = targetRegions.includes(region);
                                    return (
                                        <button
                                            key={region}
                                            type="button"
                                            onClick={() =>
                                                setTargetRegions((prev) => toggleItem(prev, region))
                                            }
                                            className={`rounded-lg px-3 py-1.5 text-xs font-medium transition ${active
                                                    ? "bg-sky-600 text-white"
                                                    : "border border-zinc-800 bg-zinc-950/70 text-zinc-400 hover:text-zinc-200"
                                                }`}
                                        >
                                            {formatRegionEligibility(region)}
                                        </button>
                                    );
                                })}
                            </div>
                        </div>
                    </div>

                    <div className="grid gap-5 lg:grid-cols-2">
                        <div className="space-y-2">
                            <label
                                htmlFor="resume-file"
                                className="block text-xs font-medium uppercase tracking-wider text-zinc-400"
                            >
                                Upload File (.pdf, .docx, .txt, .md)
                            </label>
                            <label
                                htmlFor="resume-file"
                                className="flex cursor-pointer flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-zinc-700 bg-zinc-950/60 px-4 py-6 text-center transition hover:border-violet-500/60 hover:bg-zinc-950"
                            >
                                <FileUp className="h-5 w-5 text-violet-400" />
                                <span className="text-xs font-medium text-zinc-200">
                                    {selectedFile
                                        ? selectedFile.name
                                        : "Choose a resume file to extract & store"}
                                </span>
                                <span className="text-[11px] text-zinc-500">
                                    Automatically extracts text, skills, and 768-dim vector
                                </span>
                                <input
                                    id="resume-file"
                                    type="file"
                                    accept=".pdf,.docx,.txt,.md"
                                    onChange={(e) => setSelectedFile(e.target.files?.[0] ?? null)}
                                    className="sr-only"
                                />
                            </label>
                        </div>

                        <div className="space-y-2">
                            <label
                                htmlFor="resume-raw-text"
                                className="block text-xs font-medium uppercase tracking-wider text-zinc-400"
                            >
                                Or Paste Resume Text
                            </label>
                            <textarea
                                id="resume-raw-text"
                                rows={5}
                                value={rawText}
                                onChange={(e) => setRawText(e.target.value)}
                                placeholder="Paste plain resume text (ignored if a file is selected above)..."
                                className="w-full rounded-xl border border-zinc-800 bg-zinc-950/80 p-3.5 text-xs leading-relaxed text-zinc-100 placeholder:text-zinc-600 focus:border-violet-500 focus:outline-none focus:ring-2 focus:ring-violet-500/25"
                            />
                        </div>
                    </div>

                    <div className="flex flex-wrap items-center justify-between gap-4 border-t border-zinc-800 pt-4">
                        <label className="inline-flex cursor-pointer items-center gap-2.5 text-sm text-zinc-300">
                            <input
                                type="checkbox"
                                checked={isActive}
                                onChange={(e) => setIsActive(e.target.checked)}
                                className="h-4 w-4 rounded border-zinc-700 bg-zinc-900 accent-violet-500"
                            />
                            Active for real-time job matching
                        </label>

                        <div className="flex items-center gap-3">
                            <button
                                type="button"
                                onClick={() => setFormOpen(false)}
                                className="rounded-xl px-4 py-2 text-sm font-medium text-zinc-400 transition hover:text-zinc-200"
                            >
                                Cancel
                            </button>
                            <button
                                type="submit"
                                disabled={submitting}
                                className="inline-flex items-center gap-2 rounded-xl bg-violet-600 px-5 py-2.5 text-sm font-medium text-white shadow-sm shadow-violet-600/20 transition hover:bg-violet-500 disabled:opacity-60"
                            >
                                {submitLabel}
                            </button>
                        </div>
                    </div>
                </form>
            )}

            {renderProfilesList()}
        </div>
    );
}
