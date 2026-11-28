import { Cloud, Database, Layers, Server } from "lucide-react";

const PIPELINE_STAGES = [
    {
        step: "01",
        title: "Ingest",
        summary:
            "Scheduled collectors and manual imports normalize postings and publish schema-validated events to Kafka.",
        tag: "Kafka · Event Stream",
    },
    {
        step: "02",
        title: "Enrich",
        summary:
            "Workers deduplicate reposts, classify work mode and language, extract stack and salary metadata via Gemini, and generate 768-dim vectors.",
        tag: "Gemini · 768-dim Vectors",
    },
    {
        step: "03",
        title: "Route & Score",
        summary:
            "Per-user routing selects one winning resume via pgvector and language gates before BYOK Gemini keys run structured fit analysis.",
        tag: "pgvector · BYOK AI",
    },
    {
        step: "04",
        title: "Serve",
        summary:
            "Django serves Hybrid RRF search, Copilot drafts, and Kanban tracking while FastAPI streams live SSE alerts.",
        tag: "REST + Live SSE",
    },
];

const STACK_LAYERS = [
    {
        icon: Server,
        label: "Backend & AI",
        value: "Python 3.13, Django / DRF, FastAPI, BYOK Gemini 3.5/4",
    },
    {
        icon: Database,
        label: "Data & Streaming",
        value: "PostgreSQL 17 + pgvector, Redis, Apache Kafka (KRaft)",
    },
    {
        icon: Layers,
        label: "Frontend",
        value: "React 19, TypeScript, Vite, Tailwind CSS",
    },
    {
        icon: Cloud,
        label: "Cloud & IaC",
        value: "Google Cloud Run, Cloud Scheduler, Private VPC, Terraform",
    },
];

export function LandingArchitecture() {
    return (
        <section id="architecture" className="scroll-mt-20 py-16 sm:py-24">
            <div className="mx-auto max-w-6xl px-4 sm:px-6">
                <div className="max-w-2xl">
                    <p className="font-mono text-xs font-medium uppercase tracking-widest text-violet-400">
                        Event-Driven Architecture
                    </p>
                    <h2 className="mt-2 text-2xl font-semibold tracking-tight text-zinc-100 sm:text-3xl">
                        Django control plane + FastAPI edge connected by Kafka
                    </h2>
                    <p className="mt-3 text-sm leading-relaxed text-zinc-400 sm:text-base">
                        Contract-first event schemas link scheduled collectors, async AI workers,
                        and the web workspace with built-in deduplication and dead-letter replay.
                    </p>
                </div>

                <div className="relative mt-10">
                    <div
                        aria-hidden="true"
                        className="pointer-events-none absolute top-9 right-8 left-8 hidden h-px bg-gradient-to-r from-violet-500/40 via-zinc-700/80 to-emerald-500/40 lg:block"
                    />
                    <ol className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-4">
                        {PIPELINE_STAGES.map((stage) => (
                            <li
                                key={stage.step}
                                className="relative flex flex-col justify-between rounded-2xl border border-white/[0.08] bg-zinc-900/60 p-5 ring-1 ring-inset ring-white/[0.02]"
                            >
                                <div>
                                    <span className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-violet-500/35 bg-zinc-950 font-mono text-xs font-semibold text-violet-300">
                                        {stage.step}
                                    </span>
                                    <h3 className="mt-4 text-base font-semibold text-zinc-100">
                                        {stage.title}
                                    </h3>
                                    <p className="mt-2 text-xs leading-relaxed text-zinc-400">
                                        {stage.summary}
                                    </p>
                                </div>
                                <p className="mt-4 w-fit rounded-lg border border-zinc-800 bg-zinc-950/90 px-2.5 py-1 font-mono text-[11px] text-zinc-300">
                                    {stage.tag}
                                </p>
                            </li>
                        ))}
                    </ol>
                </div>

                <div id="stack" className="scroll-mt-24 mt-14">
                    <p className="font-mono text-xs font-medium uppercase tracking-widest text-violet-400">
                        Tech Stack
                    </p>
                    <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
                        {STACK_LAYERS.map((layer) => {
                            const Icon = layer.icon;
                            return (
                                <div
                                    key={layer.label}
                                    className="rounded-2xl border border-white/[0.08] bg-zinc-900/50 p-5 ring-1 ring-inset ring-white/[0.02]"
                                >
                                    <div className="flex items-center gap-2.5">
                                        <Icon
                                            className="h-4 w-4 text-violet-400"
                                            aria-hidden="true"
                                        />
                                        <h3 className="text-sm font-semibold text-zinc-100">
                                            {layer.label}
                                        </h3>
                                    </div>
                                    <p className="mt-2 text-xs leading-relaxed text-zinc-400">
                                        {layer.value}
                                    </p>
                                </div>
                            );
                        })}
                    </div>
                </div>
            </div>
        </section>
    );
}
