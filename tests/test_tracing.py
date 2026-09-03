"""Tracing tests (spec §9 Phase F "OTel tracing 争取项").

everlink.tracing is STRICTLY OPTIONAL and zero-cost when off, so these tests pin the
two contracts that make it safe to leave instrumented in the pipeline:
  1. with tracing NOT initialized, span() is a silent no-op that never breaks the
     wrapped code and never re-raises anything but the body's own exception;
  2. the init -> is_active -> shutdown lifecycle behaves (idempotent init, honest
     inactive when the SDK is missing or enabled=False), and a body exception
     propagates through an ACTIVE span (tracing must never swallow a failure).

Each test resets the process-global provider (shutdown) at entry, and teardown_module
resets it too, so no tracing state leaks into other test modules.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from everlink import tracing  # noqa: E402


def teardown_module(module):  # noqa: ARG001
    tracing.shutdown()


def test_otel_available_is_bool():
    assert tracing.otel_available() in (True, False)


def test_span_is_a_silent_noop_when_uninitialized():
    tracing.shutdown()                      # clean slate: not active
    assert not tracing.is_active()
    ran = False
    with tracing.span("everlink.test.noop", slots=3, verdict="dead"):
        ran = True                          # the wrapped body always executes
    assert ran
    assert not tracing.is_active()          # a no-op span never flips tracing on


def test_init_tracing_disabled_stays_inactive():
    tracing.shutdown()
    assert tracing.init_tracing(enabled=False) is False
    assert not tracing.is_active()


def test_get_tracer_is_safe_when_uninitialized():
    tracing.shutdown()
    tracer = tracing.get_tracer()
    if tracing.otel_available():
        assert tracer is not None           # a NonRecordingTracer; its spans are no-ops
    else:
        assert tracer is None


def test_init_shutdown_lifecycle():
    tracing.shutdown()
    if not tracing.otel_available():
        # no SDK installed: init degrades gracefully and honestly reports inactive
        assert tracing.init_tracing(exporter=None) is False
        assert not tracing.is_active()
        return
    # exporter=None -> record in-process, export nothing (no stdout noise under pytest)
    assert tracing.init_tracing(service_name="everlink-test", exporter=None) is True
    assert tracing.is_active()
    assert tracing.init_tracing(exporter=None) is True   # idempotent: one provider/process
    assert tracing.is_active()
    with tracing.span("everlink.test.active", n=1) as sp:
        assert sp is not None               # a real recording span when active
    tracing.shutdown()
    assert not tracing.is_active()


def test_span_propagates_body_exception_when_active():
    tracing.shutdown()
    if tracing.otel_available():
        tracing.init_tracing(exporter=None)
    raised = False
    try:
        with tracing.span("everlink.test.err"):
            raise ValueError("boom")        # tracing must NOT swallow a real failure
    except ValueError:
        raised = True
    assert raised
    tracing.shutdown()


ALL = [v for k, v in sorted(globals().items()) if k.startswith("test_")]


if __name__ == "__main__":
    failed = 0
    try:
        for fn in ALL:
            try:
                fn()
                print(f"PASS {fn.__name__}")
            except Exception as e:  # noqa: BLE001
                failed += 1
                print(f"FAIL {fn.__name__}: {type(e).__name__}: {e}")
    finally:
        teardown_module(None)
    print(f"\n{len(ALL)-failed}/{len(ALL)} passed")
    sys.exit(1 if failed else 0)
