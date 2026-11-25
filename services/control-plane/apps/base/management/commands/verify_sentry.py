import os

from django.core.management.base import BaseCommand
import sentry_sdk

from config.telemetry import configure_sentry, flush_sentry


class Command(BaseCommand):
    help = "Send a controlled, PII-free verification event to Sentry and flush."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--service",
            default=os.getenv("SENTRY_SERVICE_NAME", "control-plane"),
            help="Sentry service tag to attach to the verification event.",
        )

    def handle(self, *args, **options) -> None:
        service_name = str(options["service"]).strip() or "control-plane"
        if not configure_sentry(service_name):
            self.stdout.write(
                self.style.WARNING(
                    "SENTRY_DSN is not configured; skipped Sentry verification event."
                )
            )
            return

        with sentry_sdk.new_scope() as scope:
            scope.set_tag("service", service_name)
            scope.set_tag("verification", "true")
            event_id = sentry_sdk.capture_message(
                f"Vektryn Sentry verification event ({service_name})",
                level="info",
            )
        flush_sentry(timeout=5.0)
        self.stdout.write(
            self.style.SUCCESS(
                f"Sentry verification event sent for service={service_name} event_id={event_id}"
            )
        )
