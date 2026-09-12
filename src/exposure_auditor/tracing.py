"""Optional OpenTelemetry export of scan traces.

Spans follow the OpenTelemetry GenAI semantic conventions and carry model
names, token counts, tool names, outcome codes and timings, and nothing
else. No prompts, identifiers, queries or page text: in this app a trace
with content would be a copy of the user's personal data sitting in a
telemetry backend. The same content-free events are stored per scan
(ScanEvent), so tracing works without any backend at all.
"""

from collections.abc import Sequence
from typing import Any

from opentelemetry import trace

_PROVIDER_NAMES = {"bedrock": "aws.bedrock", "foundry": "azure.ai.inference", "anthropic": "anthropic"}
_tracer: Any = None


def configure(service_name: str = "exposure-auditor") -> None:
    """Send spans over OTLP/HTTP; the endpoint comes from OTEL_EXPORTER_OTLP_ENDPOINT."""
    global _tracer
    if _tracer is not None:
        return
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(provider)
    _tracer = trace.get_tracer("exposure_auditor")


def export_scan(
    *,
    scan_id: str,
    kind: str,
    status: str,
    provider: str,
    model: str,
    started_ns: int,
    ended_ns: int,
    events: Sequence[Any],
) -> None:
    if _tracer is None:
        return
    provider_name = _PROVIDER_NAMES.get(provider, provider)
    root = _tracer.start_span(
        f"scan {kind}",
        start_time=started_ns,
        attributes={"scan.id": scan_id, "scan.kind": kind, "scan.status": status, "gen_ai.agent.name": "scan-agent"},
    )
    parent = trace.set_span_in_context(root)
    for e in events:
        if e.kind == "model_call":
            name = f"chat {model}"
            attrs = {
                "gen_ai.operation.name": "chat",
                "gen_ai.provider.name": provider_name,
                "gen_ai.request.model": model,
                "gen_ai.response.finish_reasons": [e.detail or ""],
                "gen_ai.usage.input_tokens": e.input_tokens,
                "gen_ai.usage.output_tokens": e.output_tokens,
                "gen_ai.usage.cache_read_input_tokens": e.cache_read_tokens,
                "gen_ai.usage.cache_creation_input_tokens": e.cache_write_tokens,
            }
        else:
            name = f"execute_tool {e.name}"
            attrs = {
                "gen_ai.operation.name": "execute_tool",
                "gen_ai.tool.name": e.name,
                "tool.status": e.status,
                "tool.outcome": e.detail or "",
            }
        span = _tracer.start_span(name, context=parent, start_time=e.start_ns, attributes=attrs)
        span.end(end_time=e.end_ns)
    root.end(end_time=ended_ns)
