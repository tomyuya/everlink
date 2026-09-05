"""Run EverLink Evals (spec §8) against a local fixture server.

Starts an in-process fixture server on an ephemeral port, runs the eval pipeline
(the 30-case v1 subset by default, or the FULL 50-case Phase F set with --full),
prints the report, and exits non-zero if any threshold fails. The default stub
backend needs NO AWS credentials: detection accuracy is measured for real, while
the steering / hard-metric evaluators validate the policy oracle and the
orchestration plumbing (see the honesty note the report prints). Score the real
Judge with --judge mantle (the deployed production path) once credentials exist.

--trace wraps the run in OPTIONAL OpenTelemetry spans (everlink.tracing); it is
off by default and zero-cost, so the offline path never depends on a collector.

Usage:
    python scripts/run_evals.py                          # stub judge, 30-case v1 (offline)
    python scripts/run_evals.py --full                   # FULL 50-case Phase F set
    python scripts/run_evals.py --full --trace console   # + OTel spans printed to stdout
    python scripts/run_evals.py --judge mantle           # real Judge (needs AWS creds)
    python scripts/run_evals.py --base-url http://127.0.0.1:8787   # external server
"""
from __future__ import annotations

import argparse
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from everlink import tracing  # noqa: E402
from everlink.evals import format_report, run_evals  # noqa: E402
from everlink.fixtures import make_server  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Run EverLink Evals (30-case v1 subset, or --full for the 50-case set).")
    ap.add_argument("--judge", choices=["none", "stub", "bedrock", "mantle"], default="stub",
                    help="Judge backend (default stub = offline; mantle = the deployed "
                         "real-LLM path via Bedrock Mantle)")
    ap.add_argument("--base-url", default=None,
                    help="use an already-running fixture server instead of starting one")
    ap.add_argument("--timeout", type=float, default=10.0)
    ap.add_argument("--full", action="store_true",
                    help="run the FULL 50-case Phase F set (default: 30-case v1 subset)")
    ap.add_argument("--trace", choices=["off", "console", "otlp"], default="off",
                    help="emit OpenTelemetry spans for the run (optional; off by default)")
    ap.add_argument("--otlp-endpoint", default=None,
                    help="OTLP collector endpoint when --trace otlp")
    args = ap.parse_args()

    if args.trace != "off":
        active = tracing.init_tracing(exporter=args.trace, endpoint=args.otlp_endpoint)
        if not active:
            print("[trace] OpenTelemetry SDK not installed; continuing without tracing.")

    server = thread = None
    report = None
    if args.base_url:
        base = args.base_url
    else:
        server = make_server(port=0)
        host, port = server.server_address
        base = f"http://{host}:{port}"
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
    try:
        report = run_evals(base, judge_backend=args.judge, timeout=args.timeout, full=args.full)
        print(format_report(report))
    finally:
        if args.trace != "off":
            tracing.shutdown()
        if server is not None:
            server.shutdown()
            server.server_close()
        if thread is not None:
            thread.join(timeout=5)
    return 0 if (report is not None and report.passed) else 1


if __name__ == "__main__":
    sys.exit(main())
