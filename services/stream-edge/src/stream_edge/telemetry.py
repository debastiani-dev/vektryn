import logging
import os

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
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


def configure_tracing(service_name: str) -> trace.Tracer:
    configure_sentry(service_name)

    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip()
    if endpoint:
        resource = Resource.create({"service.name": service_name})
        provider = TracerProvider(resource=resource)
        provider.add_span_processor(
            BatchSpanProcessor(
                OTLPSpanExporter(endpoint=f"{endpoint.rstrip('/')}/v1/traces")
            )
        )
        trace.set_tracer_provider(provider)
        logger.info(
            "OpenTelemetry tracing enabled for %s -> %s", service_name, endpoint
        )
    return trace.get_tracer(service_name)
