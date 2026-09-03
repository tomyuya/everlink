"""Optional OpenTelemetry tracing (spec §9 Phase F "OTel tracing 争取项").

EverLink's pipeline (scan -> detect -> judge -> write -> verify) can be instrumented with
spans so a judge can SEE the agent's telemetry, not just its output — which agent ran, how
many slots it detected, how many proposals it judged, how long each stage took.

STRICTLY OPTIONAL and zero-cost when off:
  * If ``opentelemetry`` is NOT installed, every helper degrades to a no-op (this module
    never raises ImportError at use time).
  * If tracing is not initialized, ``span()`` leans on OpenTelemetry's own
    NonRecordingTracer, so spans are created but not recorded/exported — negligible cost.
  * No pipeline code ever DEPENDS on tracing; offline tests need nothing installed.

Enable for a demo (spans printed to stdout)::

    from everlink import tracing
    tracing.init_tracing(exporter="console")     # or "otlp" with an endpoint
    ... run the pipeline (spans are emitted) ...
    tracing.shutdown()                            # flush + close

The provider is process-global (OpenTelemetry's model); ``init_tracing`` is idempotent and
returns whether tracing is ACTIVE. ``shutdown`` flushes pending spans (BatchSpanProcessor)
so a short-lived CLI/cron run does not lose its trace.
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Any, Optional

try:  # optional dependency — the whole module no-ops without it
    from opentelemetry import trace
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import (BatchSpanProcessor, ConsoleSpanExporter,
                                                SimpleSpanProcessor)
    _OTEL = True
except ImportError:  # pragma: no cover - exercised only where OTel is absent
    _OTEL = False

_PROVIDER: Optional[Any] = None
_ACTIVE = False
_INSTRUMENTATION = "everlink"


def otel_available() -> bool:
    """True iff the opentelemetry SDK is importable in this environment."""
    return _OTEL


def is_active() -> bool:
    """True iff tracing has been initialized AND spans are being recorded."""
    return _ACTIVE and _OTEL


def init_tracing(service_name: str = "everlink", *, exporter: Optional[str] = "console",
                 endpoint: Optional[str] = None, enabled: bool = True) -> bool:
    """Set up the process-global TracerProvider. Returns whether tracing is ACTIVE.

    ``exporter``:
      * ``"console"`` — SimpleSpanProcessor + ConsoleSpanExporter (spans to stdout; the
        demo/CI-friendly default, no collector needed).
      * ``"otlp"``     — BatchSpanProcessor + OTLPSpanExporter to ``endpoint`` (or
        OTEL_EXPORTER_OTLP_ENDPOINT); imported lazily so the base SDK stays sufficient.
      * ``None``       — a provider with NO exporter (spans recorded in-process only;
        useful for tests that assert span shape without stdout noise).
    ``enabled=False`` (or a missing SDK) leaves tracing OFF and returns False.
    """
    global _PROVIDER, _ACTIVE
    if not (_OTEL and enabled):
        return False
    if _ACTIVE:                       # idempotent: one provider per process
        return True

    resource = Resource.create({"service.name": service_name})
    provider = TracerProvider(resource=resource)
    endpoint = endpoint or os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    if exporter == "console":
        provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
    elif exporter == "otlp":
        try:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
            provider.add_span_processor(
                BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint) if endpoint
                                   else OTLPSpanExporter()))
        except ImportError:
            # the OTLP exporter package is not installed — fall back to the console so the
            # run is still observable rather than silently untraced.
            provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
    # exporter=None -> record in-process, export nothing
    trace.set_tracer_provider(provider)
    _PROVIDER = provider
    _ACTIVE = True
    return True


def get_tracer(name: str = _INSTRUMENTATION):
    """A tracer for ``name``. Safe whether or not OTel is installed/initialized: with no
    provider set, OpenTelemetry returns a NonRecordingTracer (spans are no-ops)."""
    if not _OTEL:
        return None
    return trace.get_tracer(name)


@contextmanager
def span(name: str, **attributes: Any):
    """Context manager opening a span ``name`` tagged with ``attributes``.

    Degrades to a plain no-op context when OTel is absent, so callers can instrument
    unconditionally. Records an exception + sets status on error, then re-raises (tracing
    must never swallow a pipeline failure).

        with tracing.span("everlink.detect", slots=41):
            ...
    """
    if not _OTEL:
        yield None
        return
    tracer = get_tracer()
    with tracer.start_as_current_span(name) as sp:
        for k, v in attributes.items():
            try:
                sp.set_attribute(k, v)
            except Exception:  # noqa: BLE001 - a bad attribute must never break the span
                pass
        try:
            yield sp
        except Exception as exc:
            sp.record_exception(exc)
            try:
                from opentelemetry.trace import Status, StatusCode
                sp.set_status(Status(StatusCode.ERROR, str(exc)))
            except Exception:  # noqa: BLE001
                pass
            raise


def shutdown() -> None:
    """Flush + close the provider (so a short CLI/cron run does not lose its trace)."""
    global _PROVIDER, _ACTIVE
    if _PROVIDER is not None:
        try:
            _PROVIDER.force_flush()
            _PROVIDER.shutdown()
        except Exception:  # noqa: BLE001 - teardown is best-effort
            pass
    _PROVIDER = None
    _ACTIVE = False
