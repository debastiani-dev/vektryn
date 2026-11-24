import logging
import os

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.django import DjangoInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
import sentry_sdk
from sentry_sdk.integrations.django import DjangoIntegration

logger = logging.getLogger(__name__)
_OTEL_CONFIGURED = False
_SENTRY_CONFIGURED = False


def configure_sentry(service_name: str = "vektryn-control-plane") -> bool:
    global _SENTRY_CONFIGURED
    if _SENTRY_CONFIGURED:
        return True

    dsn = os.getenv("SENTRY_DSN", "").strip()
    if not dsn:
        return False

    sentry_sdk.init(
        dsn=dsn,
        environment=os.getenv("SENTRY_ENVIRONMENT", "production"),
        integrations=[DjangoIntegration()],
        traces_sample_rate=float(os.getenv("SENTRY_TRACES_SAMPLE_RATE", "0.1")),
        send_default_pii=False,
    )
    sentry_sdk.set_tag("service", service_name)
    _SENTRY_CONFIGURED = True
    logger.info("Sentry error tracking enabled for %s", service_name)
    return True


def configure_telemetry(service_name: str = "vektryn-control-plane") -> None:
    global _OTEL_CONFIGURED
    configure_sentry(service_name)

    if _OTEL_CONFIGURED:
        return

    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip()
    if not endpoint:
        return

    resource = Resource.create({"service.name": service_name})
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(
        BatchSpanProcessor(
            OTLPSpanExporter(endpoint=f"{endpoint.rstrip('/')}/v1/traces")
        )
    )
    trace.set_tracer_provider(provider)
    DjangoInstrumentor().instrument(excluded_urls="health,metrics")
    _OTEL_CONFIGURED = True
    logger.info("OpenTelemetry Django tracing enabled -> %s", endpoint)
