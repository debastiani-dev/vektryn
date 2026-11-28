from collections import Counter
from typing import Any

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.jobs.models.jobs import JobPosting
from apps.resumes.models.resumes import ResumeProfile
from vektryn_contracts.enums import UNKNOWN_LANGUAGE
from vektryn_contracts.language import detect_content_language


class Command(BaseCommand):
    help = (
        "Idempotently backfill ISO 639-1 language codes for JobPosting and "
        "ResumeProfile rows currently set to 'unknown' at zero LLM cost."
    )

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--batch-size",
            type=int,
            default=500,
            help="Number of rows to stream and bulk_update per batch (default: 500).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Detect and report language counts without writing to PostgreSQL.",
        )
        parser.add_argument(
            "--only",
            choices=("all", "jobs", "resumes"),
            default="all",
            help="Restrict backfill to jobs, resumes, or all (default: all).",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        batch_size: int = max(1, int(options["batch_size"]))
        dry_run: bool = bool(options["dry_run"])
        only: str = str(options["only"])

        if only in ("all", "jobs"):
            self._backfill_jobs(batch_size=batch_size, dry_run=dry_run)
        if only in ("all", "resumes"):
            self._backfill_resumes(batch_size=batch_size, dry_run=dry_run)

    def _backfill_jobs(self, *, batch_size: int, dry_run: bool) -> None:
        qs = (
            JobPosting.all_objects.filter(language=UNKNOWN_LANGUAGE)
            .only("uuid", "title", "description_clean", "language", "modified_at")
            .order_by("uuid")
        )
        scanned = 0
        updated = 0
        counts: Counter[str] = Counter()
        pending: list[JobPosting] = []

        for job in qs.iterator(chunk_size=batch_size):
            scanned += 1
            detected = detect_content_language(
                f"{job.title}\n\n{job.description_clean}"
            )
            counts[detected] += 1
            if detected != UNKNOWN_LANGUAGE:
                job.language = detected
                job.modified_at = timezone.now()
                pending.append(job)
                updated += 1
                if len(pending) >= batch_size:
                    if not dry_run:
                        JobPosting.all_objects.bulk_update(
                            pending, ["language", "modified_at"]
                        )
                    pending.clear()

        if pending and not dry_run:
            JobPosting.all_objects.bulk_update(pending, ["language", "modified_at"])

        self._report("JobPosting", scanned, updated, counts, dry_run=dry_run)

    def _backfill_resumes(self, *, batch_size: int, dry_run: bool) -> None:
        qs = (
            ResumeProfile.all_objects.filter(language=UNKNOWN_LANGUAGE)
            .only("uuid", "raw_text", "language", "modified_at")
            .order_by("uuid")
        )
        scanned = 0
        updated = 0
        counts: Counter[str] = Counter()
        pending: list[ResumeProfile] = []

        for profile in qs.iterator(chunk_size=batch_size):
            scanned += 1
            detected = detect_content_language(profile.raw_text)
            counts[detected] += 1
            if detected != UNKNOWN_LANGUAGE:
                profile.language = detected
                profile.modified_at = timezone.now()
                pending.append(profile)
                updated += 1
                if len(pending) >= batch_size:
                    if not dry_run:
                        ResumeProfile.all_objects.bulk_update(
                            pending, ["language", "modified_at"]
                        )
                    pending.clear()

        if pending and not dry_run:
            ResumeProfile.all_objects.bulk_update(pending, ["language", "modified_at"])

        self._report("ResumeProfile", scanned, updated, counts, dry_run=dry_run)

    def _report(
        self,
        model_label: str,
        scanned: int,
        updated: int,
        counts: Counter[str],
        *,
        dry_run: bool,
    ) -> None:
        still_unknown = counts.get(UNKNOWN_LANGUAGE, 0)
        top_langs = ", ".join(
            f"{code}={n}"
            for code, n in counts.most_common(8)
            if code != UNKNOWN_LANGUAGE
        )
        mode = "DRY-RUN" if dry_run else "APPLIED"
        self.stdout.write(
            f"[{mode}] {model_label}: scanned={scanned} updated={updated} "
            f"still_unknown={still_unknown} detected=[{top_langs or 'none'}]"
        )
