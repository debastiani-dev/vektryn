import { AlertCircle, ChevronDown, ChevronUp, FileText, Link2, Loader2, X } from "lucide-react";
import { type SyntheticEvent, useEffect, useState } from "react";
import { vektrynApi } from "../../api/client";
import type { ManualJobImportInput, ManualJobImportResponse } from "../../types/models";

type ImportMode = "url" | "manual";

interface ImportFormFields {
    mode: ImportMode;
    url: string;
    title: string;
    companyName: string;
    applyUrl: string;
    locationRaw: string;
    description: string;
}

interface ImportJobModalProps {
    open: boolean;
    onClose: () => void;
    onImported: (result: ManualJobImportResponse) => void;
}

function validateImportFields(fields: ImportFormFields): string | null {
    if (fields.mode === "url") {
        return fields.url.trim() ? null : "Please enter a public job posting URL.";
    }
    if (!fields.title.trim() || !fields.companyName.trim() || !fields.applyUrl.trim()) {
        return "Role title, company name, and application URL or email are required.";
    }
    if (fields.description.trim().length < 40) {
        return "Job description must be at least 40 characters.";
    }
    return null;
}

function buildImportPayload(fields: ImportFormFields): ManualJobImportInput {
    if (fields.mode === "url") {
        const payload: ManualJobImportInput = { url: fields.url.trim() };
        if (fields.title.trim()) payload.title = fields.title.trim();
        if (fields.companyName.trim()) payload.company_name = fields.companyName.trim();
        if (fields.locationRaw.trim()) payload.location_raw = fields.locationRaw.trim();
        return payload;
    }
    return {
        title: fields.title.trim(),
        company_name: fields.companyName.trim(),
        apply_url: fields.applyUrl.trim(),
        location_raw: fields.locationRaw.trim(),
        description: fields.description.trim(),
    };
}

function formatErrorValue(val: unknown): string {
    if (typeof val === "string") return val;
    if (typeof val === "number" || typeof val === "boolean") return String(val);
    if (Array.isArray(val)) return val.map(formatErrorValue).filter(Boolean).join(" ");
    if (val && typeof val === "object") return JSON.stringify(val);
    return "";
}

function parseImportError(err: unknown): { message: string; isFetchFailure: boolean } {
    const raw = err instanceof Error ? err.message : "Failed to import job posting.";
    const isFetchFailure = raw.startsWith("API 422:");
    const isRateLimited = raw.startsWith("API 429:");

    const match = /^API \d+:\s*(.+)$/s.exec(raw);
    if (match) {
        try {
            const parsed = JSON.parse(match[1]) as Record<string, unknown>;
            if (typeof parsed.detail === "string" && parsed.detail.trim()) {
                return { message: parsed.detail, isFetchFailure };
            }
            const fieldErrors = Object.entries(parsed)
                .map(([field, val]) => {
                    const text = formatErrorValue(val);
                    if (!text) return "";
                    return field === "non_field_errors" ? text : `${field}: ${text}`;
                })
                .filter(Boolean);
            if (fieldErrors.length > 0) {
                return { message: fieldErrors.join(" · "), isFetchFailure };
            }
        } catch {
            // Fall back to raw text
        }
    }
    if (isRateLimited) {
        return {
            message: "You've reached the manual import limit. Please wait a few minutes and try again.",
            isFetchFailure: false,
        };
    }
    return { message: raw, isFetchFailure };
}

export function ImportJobModal({
    open,
    onClose,
    onImported,
}: Readonly<ImportJobModalProps>) {
    const [mode, setMode] = useState<ImportMode>("url");
    const [url, setUrl] = useState("");
    const [showOverrides, setShowOverrides] = useState(false);

    const [title, setTitle] = useState("");
    const [companyName, setCompanyName] = useState("");
    const [applyUrl, setApplyUrl] = useState("");
    const [locationRaw, setLocationRaw] = useState("");
    const [description, setDescription] = useState("");

    const [submitting, setSubmitting] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [suggestManualSwitch, setSuggestManualSwitch] = useState(false);

    useEffect(() => {
        if (!open) return;
        const onKeyDown = (event: KeyboardEvent) => {
            if (event.key === "Escape" && !submitting) {
                onClose();
            }
        };
        window.addEventListener("keydown", onKeyDown);
        return () => window.removeEventListener("keydown", onKeyDown);
    }, [open, submitting, onClose]);

    if (!open) return null;

    function resetFields() {
        setUrl("");
        setTitle("");
        setCompanyName("");
        setApplyUrl("");
        setLocationRaw("");
        setDescription("");
        setShowOverrides(false);
        setError(null);
        setSuggestManualSwitch(false);
    }

    function switchToManualWithUrl() {
        if (url.trim() && !applyUrl.trim()) {
            setApplyUrl(url.trim());
        }
        setMode("manual");
        setError(null);
        setSuggestManualSwitch(false);
    }

    async function handleSubmit(event: SyntheticEvent<HTMLFormElement>) {
        event.preventDefault();
        setError(null);
        setSuggestManualSwitch(false);

        const fields: ImportFormFields = {
            mode,
            url,
            title,
            companyName,
            applyUrl,
            locationRaw,
            description,
        };
        const validationError = validateImportFields(fields);
        if (validationError) {
            setError(validationError);
            return;
        }

        setSubmitting(true);
        try {
            const res = await vektrynApi.importJob(buildImportPayload(fields));
            resetFields();
            onImported(res);
            onClose();
        } catch (err) {
            const { message, isFetchFailure } = parseImportError(err);
            setError(message);
            setSuggestManualSwitch(mode === "url" && isFetchFailure);
        } finally {
            setSubmitting(false);
        }
    }

    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
            <button
                type="button"
                aria-label="Close import modal"
                disabled={submitting}
                onClick={onClose}
                className="fixed inset-0 cursor-default bg-black/75 backdrop-blur-xs"
            />
            <dialog
                open
                aria-modal="true"
                aria-labelledby="import-job-modal-title"
                className="relative z-10 m-0 w-full max-w-2xl overflow-hidden rounded-2xl border border-zinc-800 bg-zinc-950 p-0 text-zinc-100 shadow-2xl shadow-black/60"
            >
                <div className="flex items-start justify-between gap-4 border-b border-zinc-800/90 px-6 py-5">
                    <div>
                        <h2
                            id="import-job-modal-title"
                            className="text-lg font-semibold tracking-tight text-zinc-100"
                        >
                            Import External Job
                        </h2>
                        <p className="mt-1 text-xs text-zinc-400">
                            Extract a public posting URL or enter details manually to run full AI enrichment, vector matching, and gap analysis.
                        </p>
                    </div>
                    <button
                        type="button"
                        disabled={submitting}
                        onClick={onClose}
                        aria-label="Close import modal"
                        className="rounded-lg p-1.5 text-zinc-400 transition hover:bg-zinc-800 hover:text-zinc-100 disabled:opacity-50"
                    >
                        <X className="h-4 w-4" />
                    </button>
                </div>

                <div className="border-b border-zinc-800/80 bg-zinc-900/40 px-6 py-3">
                    <div className="inline-flex rounded-xl border border-zinc-800 bg-zinc-950/90 p-1">
                        <button
                            type="button"
                            onClick={() => {
                                setMode("url");
                                setError(null);
                                setSuggestManualSwitch(false);
                            }}
                            className={`inline-flex items-center gap-2 rounded-lg px-3.5 py-1.5 text-xs font-medium transition ${
                                mode === "url"
                                    ? "bg-violet-600 text-white shadow-xs"
                                    : "text-zinc-400 hover:text-zinc-200"
                            }`}
                        >
                            <Link2 className="h-3.5 w-3.5" />
                            Import from URL
                        </button>
                        <button
                            type="button"
                            onClick={() => {
                                setMode("manual");
                                setError(null);
                                setSuggestManualSwitch(false);
                            }}
                            className={`inline-flex items-center gap-2 rounded-lg px-3.5 py-1.5 text-xs font-medium transition ${
                                mode === "manual"
                                    ? "bg-violet-600 text-white shadow-xs"
                                    : "text-zinc-400 hover:text-zinc-200"
                            }`}
                        >
                            <FileText className="h-3.5 w-3.5" />
                            Enter Manually
                        </button>
                    </div>
                </div>

                <form onSubmit={(e) => void handleSubmit(e)} className="max-h-[75vh] overflow-y-auto px-6 py-5 space-y-5">
                    {error && (
                        <div className="space-y-2.5 rounded-xl border border-red-500/35 bg-red-950/25 px-4 py-3 text-xs text-red-200">
                            <div className="flex items-start gap-2.5">
                                <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-red-400" />
                                <p className="leading-relaxed">{error}</p>
                            </div>
                            {suggestManualSwitch && (
                                <button
                                    type="button"
                                    onClick={switchToManualWithUrl}
                                    className="inline-flex items-center gap-1.5 rounded-lg border border-violet-500/40 bg-violet-500/15 px-3 py-1.5 text-xs font-medium text-violet-200 transition hover:bg-violet-500/25"
                                >
                                    <FileText className="h-3.5 w-3.5" />
                                    Switch to Enter Manually (keep URL)
                                </button>
                            )}
                        </div>
                    )}

                    {mode === "url" ? (
                        <div className="space-y-4">
                            <div className="space-y-1.5">
                                <label
                                    htmlFor="import-job-url"
                                    className="block text-xs font-medium uppercase tracking-wider text-zinc-400"
                                >
                                    Public Job Posting URL
                                </label>
                                <input
                                    id="import-job-url"
                                    type="url"
                                    required
                                    value={url}
                                    onChange={(e) => setUrl(e.target.value)}
                                    placeholder="https://company.com/careers/senior-python-engineer"
                                    className="w-full rounded-xl border border-zinc-800 bg-zinc-900/70 px-4 py-2.5 text-sm text-zinc-100 placeholder:text-zinc-600 focus:border-violet-500 focus:outline-none focus:ring-2 focus:ring-violet-500/25"
                                />
                                <p className="text-xs text-zinc-500">
                                    Works best on public career pages and ATS links. For login-walled listings (like LinkedIn), use Enter Manually.
                                </p>
                            </div>

                            <div className="rounded-xl border border-zinc-800/80 bg-zinc-900/30">
                                <button
                                    type="button"
                                    onClick={() => setShowOverrides((prev) => !prev)}
                                    className="flex w-full items-center justify-between px-4 py-2.5 text-xs font-medium text-zinc-400 transition hover:text-zinc-200"
                                >
                                    <span>Optional metadata overrides (title, company, location)</span>
                                    {showOverrides ? (
                                        <ChevronUp className="h-4 w-4" />
                                    ) : (
                                        <ChevronDown className="h-4 w-4" />
                                    )}
                                </button>
                                {showOverrides && (
                                    <div className="grid gap-3 border-t border-zinc-800/80 p-4 sm:grid-cols-3">
                                        <input
                                            type="text"
                                            value={title}
                                            onChange={(e) => setTitle(e.target.value)}
                                            placeholder="Role title (optional)"
                                            className="rounded-lg border border-zinc-800 bg-zinc-950/80 px-3 py-2 text-xs text-zinc-100 placeholder:text-zinc-600 focus:border-violet-500 focus:outline-none"
                                        />
                                        <input
                                            type="text"
                                            value={companyName}
                                            onChange={(e) => setCompanyName(e.target.value)}
                                            placeholder="Company (optional)"
                                            className="rounded-lg border border-zinc-800 bg-zinc-950/80 px-3 py-2 text-xs text-zinc-100 placeholder:text-zinc-600 focus:border-violet-500 focus:outline-none"
                                        />
                                        <input
                                            type="text"
                                            value={locationRaw}
                                            onChange={(e) => setLocationRaw(e.target.value)}
                                            placeholder="Location (optional)"
                                            className="rounded-lg border border-zinc-800 bg-zinc-950/80 px-3 py-2 text-xs text-zinc-100 placeholder:text-zinc-600 focus:border-violet-500 focus:outline-none"
                                        />
                                    </div>
                                )}
                            </div>
                        </div>
                    ) : (
                        <div className="space-y-4">
                            <div className="grid gap-4 sm:grid-cols-2">
                                <div className="space-y-1.5">
                                    <label
                                        htmlFor="manual-job-title"
                                        className="block text-xs font-medium uppercase tracking-wider text-zinc-400"
                                    >
                                        Role Title *
                                    </label>
                                    <input
                                        id="manual-job-title"
                                        type="text"
                                        required
                                        value={title}
                                        onChange={(e) => setTitle(e.target.value)}
                                        placeholder="Senior Python Backend Engineer"
                                        className="w-full rounded-xl border border-zinc-800 bg-zinc-900/70 px-4 py-2.5 text-sm text-zinc-100 placeholder:text-zinc-600 focus:border-violet-500 focus:outline-none focus:ring-2 focus:ring-violet-500/25"
                                    />
                                </div>
                                <div className="space-y-1.5">
                                    <label
                                        htmlFor="manual-job-company"
                                        className="block text-xs font-medium uppercase tracking-wider text-zinc-400"
                                    >
                                        Company Name *
                                    </label>
                                    <input
                                        id="manual-job-company"
                                        type="text"
                                        required
                                        value={companyName}
                                        onChange={(e) => setCompanyName(e.target.value)}
                                        placeholder="Acme Cloud"
                                        className="w-full rounded-xl border border-zinc-800 bg-zinc-900/70 px-4 py-2.5 text-sm text-zinc-100 placeholder:text-zinc-600 focus:border-violet-500 focus:outline-none focus:ring-2 focus:ring-violet-500/25"
                                    />
                                </div>
                            </div>

                            <div className="grid gap-4 sm:grid-cols-2">
                                <div className="space-y-1.5">
                                    <label
                                        htmlFor="manual-job-apply-url"
                                        className="block text-xs font-medium uppercase tracking-wider text-zinc-400"
                                    >
                                        Application URL or Email *
                                    </label>
                                    <input
                                        id="manual-job-apply-url"
                                        type="text"
                                        required
                                        value={applyUrl}
                                        onChange={(e) => setApplyUrl(e.target.value)}
                                        placeholder="https://company.com/apply or hiring@company.com"
                                        className="w-full rounded-xl border border-zinc-800 bg-zinc-900/70 px-4 py-2.5 text-sm text-zinc-100 placeholder:text-zinc-600 focus:border-violet-500 focus:outline-none focus:ring-2 focus:ring-violet-500/25"
                                    />
                                </div>
                                <div className="space-y-1.5">
                                    <label
                                        htmlFor="manual-job-location"
                                        className="block text-xs font-medium uppercase tracking-wider text-zinc-400"
                                    >
                                        Location (Optional)
                                    </label>
                                    <input
                                        id="manual-job-location"
                                        type="text"
                                        value={locationRaw}
                                        onChange={(e) => setLocationRaw(e.target.value)}
                                        placeholder="Remote - LATAM / Brazil"
                                        className="w-full rounded-xl border border-zinc-800 bg-zinc-900/70 px-4 py-2.5 text-sm text-zinc-100 placeholder:text-zinc-600 focus:border-violet-500 focus:outline-none focus:ring-2 focus:ring-violet-500/25"
                                    />
                                </div>
                            </div>

                            <div className="space-y-1.5">
                                <label
                                    htmlFor="manual-job-description"
                                    className="block text-xs font-medium uppercase tracking-wider text-zinc-400"
                                >
                                    Job Description *
                                </label>
                                <textarea
                                    id="manual-job-description"
                                    rows={7}
                                    required
                                    value={description}
                                    onChange={(e) => setDescription(e.target.value)}
                                    placeholder="Paste the full role requirements, tech stack, compensation, and responsibilities..."
                                    className="w-full rounded-xl border border-zinc-800 bg-zinc-900/70 px-4 py-3 text-sm leading-relaxed text-zinc-100 placeholder:text-zinc-600 focus:border-violet-500 focus:outline-none focus:ring-2 focus:ring-violet-500/25"
                                />
                            </div>
                        </div>
                    )}

                    <div className="flex items-center justify-end gap-3 border-t border-zinc-800/90 pt-4">
                        <button
                            type="button"
                            disabled={submitting}
                            onClick={onClose}
                            className="rounded-xl border border-zinc-800 bg-zinc-900 px-4 py-2.5 text-sm font-medium text-zinc-300 transition hover:bg-zinc-800 hover:text-zinc-100 disabled:opacity-50"
                        >
                            Cancel
                        </button>
                        <button
                            type="submit"
                            disabled={submitting}
                            className="inline-flex items-center gap-2 rounded-xl bg-violet-600 px-5 py-2.5 text-sm font-medium text-white shadow-sm shadow-violet-600/20 transition hover:bg-violet-500 disabled:opacity-60"
                        >
                            {submitting ? (
                                <>
                                    <Loader2 className="h-4 w-4 animate-spin" />
                                    {mode === "url" ? "Fetching & Queueing..." : "Queueing..."}
                                </>
                            ) : (
                                "Import & Score Job"
                            )}
                        </button>
                    </div>
                </form>
            </dialog>
        </div>
    );
}
