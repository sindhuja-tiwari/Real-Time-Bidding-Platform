"""OpenTelemetry tracing.

Off unless OTEL_EXPORTER_OTLP_ENDPOINT is set, so local dev and tests don't
need a collector. When on, the backend exports:

- FastAPI server spans for every request (health and metrics excluded),
- manual spans for the auction itself, the DSP fan-out, each DSP call, and
  the wait to check a connection out of the DB pool.

The manual spans carry the attributes an incident investigation needs
(DSP name and outcome, the deadlines in force, pool occupancy), so traces
alone can separate a slow bidder from a short deadline from a starved pool.

Per-query SQLAlchemy instrumentation was tried and left out: it added several
spans per auction (one per pool connect and query) and enough CPU to stall
the single backend process at ~24 auctions/s.
"""
from __future__ import annotations

from opentelemetry import trace

from app.core.config import get_settings

settings = get_settings()

tracer = trace.get_tracer("rtb-platform")


def configure_tracing(app) -> bool:
    if not settings.OTEL_EXPORTER_OTLP_ENDPOINT:
        return False

    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    resource = Resource.create(
        {"service.name": settings.OTEL_SERVICE_NAME, "service.version": settings.APP_VERSION}
    )
    provider = TracerProvider(resource=resource)
    endpoint = settings.OTEL_EXPORTER_OTLP_ENDPOINT.rstrip("/")
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=f"{endpoint}/v1/traces")))
    trace.set_tracer_provider(provider)

    # exclude_spans drops the per-message ASGI send/receive spans, which
    # triple the span count without adding anything an investigation uses.
    FastAPIInstrumentor.instrument_app(app, excluded_urls="health,metrics", exclude_spans=["send", "receive"])
    return True


def shutdown_tracing() -> None:
    provider = trace.get_tracer_provider()
    if hasattr(provider, "shutdown"):
        provider.shutdown()
