"""``python -m everlink`` command line (spec §12 validation entrypoint).

Commands
--------
scan    Discover + detect link rot on a site (READ-ONLY), optionally run the
        Judge to propose fixes, and print an honest report. Detection needs no
        LLM, so ``--judge none`` (the default) produces a real dead-link report
        with zero AWS credentials. ``--dry-run`` writes nothing to any database.

The scan is polite: <=1 request per link at L1, plus a selective second request
at L2 only for ambiguous/soft-404 suspects. Nothing is ever written back to a
scanned site; the only writes (without --dry-run) go to EverLink's OWN guarded
operational store (never a source-site host — see db._assert_writable).
"""
from __future__ import annotations

import argparse
import sys

from . import agents
from .llm import BedrockNotConfigured, get_model


def _print_report(report: agents.ScanReport) -> None:
    counts = report.verdict_counts()
    problems = report.problems()
    print(f"\nscan report - source '{report.source}'  (judge backend: {report.judge_backend})")
    print(f"  scanned : {report.scanned} outbound links")
    print(f"  verdicts: {counts}")
    print(f"  {len(problems)} need attention, {report.scanned - len(problems)} healthy.")
    if not problems:
        return
    proposals = {sp.check.slot_id: sp.proposal for sp in report.proposals}
    print("\n  --- problem links (read-only; nothing written back to the site) ---")
    for c in problems:
        head = f"   * [{c.final_verdict}] slot={c.slot_id}  L1 HTTP {c.l1_status}"
        if c.l2_verdict:
            head += f"  L2={c.l2_verdict}"
        print(head)
        if c.l2_evidence:
            print(f"       evidence: {c.l2_evidence}")
        prop = proposals.get(c.slot_id)
        if prop is not None:
            print(f"       proposal: {prop.action} (risk={prop.risk_level})")
            print(f"                 {prop.rationale}")


def _persist_checks(report: agents.ScanReport) -> int:
    """Write slot_checks to EverLink's own DB (guarded). Returns rows written."""
    from . import db

    dsn = db.everlink_dsn()          # raises RuntimeError if unset
    conn = db.connect(dsn)
    try:
        db.ensure_schema(conn)
        for c in report.checks:
            db.insert_slot_check(c)
    finally:
        conn.close()
    return len(report.checks)


def cmd_scan(args: argparse.Namespace) -> int:
    judge = None
    backend = "none"
    if args.judge == "stub":
        judge = agents.build_stub_judge()
        backend = "stub"
    elif args.judge == "bedrock":
        try:
            model = get_model()
        except BedrockNotConfigured as e:
            print(f"[everlink] Bedrock unavailable:\n{e}", file=sys.stderr)
            return 2
        judge = agents.build_judge(model)
        backend = "bedrock"

    adapter_kwargs: dict = {}
    if args.max_pages is not None:
        adapter_kwargs["max_pages"] = args.max_pages
    if args.include_internal:
        adapter_kwargs["include_internal"] = True

    print(f"[1/2] discovering + detecting on '{args.site}' "
          f"(limit={args.limit}, L2={'off' if args.no_l2 else 'on'}, judge={backend}) ...")
    report = agents.run_scan(
        args.site, limit=args.limit, rate_delay=args.rate_delay,
        timeout=args.timeout, use_l2=not args.no_l2,
        judge=judge, judge_backend=backend, **adapter_kwargs)
    _print_report(report)

    if args.dry_run:
        print("\n[2/2] --dry-run: nothing written to any database (read-only scan).")
        return 0
    try:
        n = _persist_checks(report)
    except RuntimeError as e:
        print(f"\n[2/2] skipped persistence: {e}", file=sys.stderr)
        return 0
    print(f"\n[2/2] persisted {n} slot_checks to EverLink's operational DB.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="everlink", description="EverLink - autonomous link-rot steward for content sites.")
    sub = ap.add_subparsers(dest="command", required=True)

    sc = sub.add_parser("scan", help="discover + detect link rot (read-only); optionally judge fixes")
    sc.add_argument("--site", required=True,
                    help="first-party site name (aethelgem/sandcart/hotdeals) OR any URL/sitemap")
    sc.add_argument("--limit", type=int, default=25, help="max slots to scan (default 25)")
    sc.add_argument("--rate-delay", type=float, default=1.0, help="seconds between requests")
    sc.add_argument("--timeout", type=float, default=15.0)
    sc.add_argument("--no-l2", action="store_true", help="L1 only (skip L2 page-parse)")
    sc.add_argument("--judge", choices=["none", "stub", "bedrock"], default="none",
                    help="none=detection only (default); stub=offline; bedrock=real LLM")
    sc.add_argument("--dry-run", action="store_true", help="write nothing to any database")
    sc.add_argument("--max-pages", type=int, default=None, help="generic adapter: max pages to crawl")
    sc.add_argument("--include-internal", action="store_true",
                    help="generic adapter: also report same-host links")
    sc.set_defaults(func=cmd_scan)
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)
