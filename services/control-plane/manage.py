#!/usr/bin/env python
import os
import sys

from django.core.management import execute_from_command_line
import sentry_sdk

from config.telemetry import configure_sentry, flush_sentry


def main() -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    sentry_enabled = configure_sentry()
    try:
        execute_from_command_line(sys.argv)
    except Exception as exc:
        if sentry_enabled:
            sentry_sdk.capture_exception(exc)
        raise
    finally:
        if sentry_enabled:
            flush_sentry(timeout=5.0)


if __name__ == "__main__":
    main()
