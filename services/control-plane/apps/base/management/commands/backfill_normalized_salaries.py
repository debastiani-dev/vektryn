from typing import Any

from django.core.management.base import BaseCommand
from django.db.models import Q

from apps.jobs.models.jobs import JobPosting
from apps.jobs.services.fx_rates import get_fx_snapshot, refresh_fx_rates_sync
from vektryn_contracts import normalize_currency_code, normalize_salary_to_annual_usd


def _normalize_single_job_salary(
    job: JobPosting,
    usd_rates: dict[str, Any],
) -> tuple[bool, bool]:
    """Normalize currency and annual USD salary columns in place.

    Returns (changed, plausible_normalized).
    """
    normalized_currency = normalize_currency_code(job.salary_currency)
    normalized = normalize_salary_to_annual_usd(
        job.salary_min,
        job.salary_max,
        normalized_currency,
        job.salary_period,
        usd_rates,
    )
    next_min = normalized.annual_min_usd if normalized is not None else None
    next_max = normalized.annual_max_usd if normalized is not None else None
    next_mid = normalized.annual_mid_usd if normalized is not None else None

    changed = (
        job.salary_currency != normalized_currency
        or job.salary_annual_min_usd != next_min
        or job.salary_annual_max_usd != next_max
        or job.salary_annual_mid_usd != next_mid
    )
    if changed:
        job.salary_currency = normalized_currency
        job.salary_annual_min_usd = next_min
        job.salary_annual_max_usd = next_max
        job.salary_annual_mid_usd = next_mid
    return changed, normalized is not None


class Command(BaseCommand):
    help = (
        "Idempotently normalize JobPosting.salary_currency and populate canonical "
        "annual USD salary columns at $0 LLM cost."
    )

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--batch-size",
            type=int,
            default=500,
            help="Number of JobPosting rows processed per batch (default: 500).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Preview normalized salary counts without writing to PostgreSQL.",
        )
        parser.add_argument(
            "--refresh-fx",
            action="store_true",
            help="Fetch fresh USD FX rates into FxRate and Redis before backfilling.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        batch_size = max(1, int(options["batch_size"]))
        dry_run = bool(options["dry_run"])
        refresh_fx = bool(options["refresh_fx"])

        fx_snapshot = refresh_fx_rates_sync() if refresh_fx else get_fx_snapshot()
        qs = (
            JobPosting.all_objects.filter(
                Q(salary_min__isnull=False) | Q(salary_max__isnull=False)
            )
            .only(
                "uuid",
                "salary_min",
                "salary_max",
                "salary_currency",
                "salary_period",
                "salary_annual_min_usd",
                "salary_annual_max_usd",
                "salary_annual_mid_usd",
            )
            .order_by("created_at")
        )

        scanned = 0
        updated_jobs = 0
        plausible_count = 0
        outlier_or_incomplete = 0
        pending: list[JobPosting] = []

        for job in qs.iterator(chunk_size=batch_size):
            scanned += 1
            changed, is_plausible = _normalize_single_job_salary(job, fx_snapshot.rates)
            if is_plausible:
                plausible_count += 1
            else:
                outlier_or_incomplete += 1
            if changed:
                pending.append(job)
                updated_jobs += 1
            if len(pending) >= batch_size:
                self._flush(pending, dry_run=dry_run)

        self._flush(pending, dry_run=dry_run)
        mode = "DRY-RUN" if dry_run else "APPLIED"
        self.stdout.write(
            f"[{mode}] backfill_normalized_salaries: fx_source={fx_snapshot.source} "
            f"as_of={fx_snapshot.as_of_date} scanned={scanned} updated_jobs={updated_jobs} "
            f"plausible={plausible_count} skipped_or_outlier={outlier_or_incomplete}"
        )

    @staticmethod
    def _flush(pending: list[JobPosting], *, dry_run: bool) -> None:
        if pending and not dry_run:
            JobPosting.all_objects.bulk_update(
                pending,
                [
                    "salary_currency",
                    "salary_annual_min_usd",
                    "salary_annual_max_usd",
                    "salary_annual_mid_usd",
                ],
            )
        pending.clear()
