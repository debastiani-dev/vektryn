import logging
import os

import sentry_sdk
from sentry_sdk.integrations.fastapi import FastApiIntegration

logger = logging.getLogger(__name__)
_SENTRY_CONFIGURED = False


def configure_sentry(service_name: str) -> bool:
    global _SENTRY_CONFIGURED
    if _SENTRY_CONFIGURED:
        return True

    dsn = os.getenv("SENTRY_DSN", "").strip()
    if not dsn:
        return False

    sentry_sdk.init(
        dsn=dsn,
        environment=os.getenv("SENTRY_ENVIRONMENT", "production"),
        integrations=[FastApiIntegration()],
        traces_sample_rate=float(os.getenv("SENTRY_TRACES_SAMPLE_RATE", "0.1")),
        send_default_pii=False,
    )
    sentry_sdk.set_tag("service", service_name)
    _SENTRY_CONFIGURED = True
    logger.info("Sentry error tracking enabled for %s", service_name)
    return True
