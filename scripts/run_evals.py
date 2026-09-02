"""Run EverLink Evals v1 (spec §8) against a local fixture server.

Starts an in-process fixture server on an ephemeral port, runs the 30-case eval
pipeline, prints the report, and exits non-zero if any threshold fails. The
default stub backend needs NO AWS credentials: detection accuracy is measured for
real, while the steering / hard-metric evaluators validate the policy oracle and
the orchestration plumbing (see the honesty note the report prints). Score the
real Judge with --judge bedrock once credentials exist (Phase F).

Usage:
    python scripts/run_evals.py                    # stub judge (offline, default)
    python scripts/run_evals.py --judge bedrock    # real Judge (needs AWS creds)
    python scripts/run_evals.py --base-url http://127.0.0.1:8787   # external server
"""
from __future__ import annotations

import argparse
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from everlink.evals import format_report, run_evals  # noqa: E402
from everlink.fixtures import make_server  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="Run EverLink Evals v1 (30-case subset).")
    ap.add_argument("--judge", choices=["none", "stub", "bedrock"], default="stub",
                    help="Judge backend (default stub = offline)")
    ap.add_argument("--base-url", default=None,
                    help="use an already-running fixture server instead of starting one")
    ap.add_argument("--timeout", type=float, default=10.0)
    args = ap.parse_args()

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
        report = run_evals(base, judge_backend=args.judge, timeout=args.timeout)
        print(format_report(report))
    finally:
        if server is not None:
            server.shutdown()
            server.server_close()
        if thread is not None:
            thread.join(timeout=5)
    return 0 if (report is not None and report.passed) else 1


if __name__ == "__main__":
    sys.exit(main())
