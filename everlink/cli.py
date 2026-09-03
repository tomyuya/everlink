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
import json
import sys

from . import agents, cards, hitl, notify, steering
from .llm import BedrockNotConfigured, get_model
from .queue import DbDecisionStore


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


def _open_db_store():
    """Connect to EverLink's OWN guarded DB and return ``(conn, DbDecisionStore)``.

    The store is the durable async-Interrupt queue (spec §5 ``decisions``). Raises
    ``RuntimeError`` if the DSN is unset so callers can degrade gracefully. The
    caller owns ``conn`` and must close it.
    """
    from . import db

    dsn = db.everlink_dsn()          # raises RuntimeError if unset
    conn = db.connect(dsn)
    db.ensure_schema(conn)
    return conn, DbDecisionStore(conn)


def _persist(report: agents.ScanReport, audit_records: list[dict],
             decision_cards: list | None = None) -> tuple[int, int]:
    """Write slot_checks + audit_log rows, and enqueue decision cards (all guarded).

    Returns ``(slot_checks_written, cards_enqueued)``. Audit rows are appended
    best-effort so a steering/tool trail survives the run (spec §5 audit_log).
    Cards are enqueued idempotently (status=pending) as the durable Interrupt queue;
    a re-scan never resurrects a card a human already decided.
    """
    from . import db

    dsn = db.everlink_dsn()          # raises RuntimeError if unset
    conn = db.connect(dsn)
    try:
        db.ensure_schema(conn)
        for c in report.checks:
            db.insert_slot_check(c)
        for r in audit_records:
            db.insert_audit(conn, r.get("agent", ""), r.get("event", "tool_result"),
                            json.dumps(r, default=str))
        enqueued = 0
        if decision_cards:
            enqueued = DbDecisionStore(conn).enqueue(decision_cards)
    finally:
        conn.close()
    return len(report.checks), enqueued


def cmd_scan(args: argparse.Namespace) -> int:
    audit = steering.AuditCollector()
    enforce = not args.no_enforce
    judge = None
    backend = "none"
    if args.judge == "stub":
        judge = agents.build_stub_judge(audit_sink=audit, enforce=enforce)
        backend = "stub"
    elif args.judge == "bedrock":
        try:
            model = get_model()
        except BedrockNotConfigured as e:
            print(f"[everlink] Bedrock unavailable:\n{e}", file=sys.stderr)
            return 2
        judge = agents.build_judge(model, audit_sink=audit, enforce=enforce)
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

    if backend != "none":
        cancels = audit.events().count("steering_cancel")
        print(f"\n  steering: enforce={'on' if enforce else 'off'}; "
              f"{cancels} proposal(s) blocked/re-steered by hooks; "
              f"{len(audit.records)} tool call(s) audited.")

    # Aggregate proposals into decision cards (spec §6): cross-article duplicates of
    # the SAME dead link merge into ONE card, so the human reviews a problem once.
    decision_cards = cards.build_decision_cards(report.proposals) if report.proposals else []
    if decision_cards:
        high = sum(1 for c in decision_cards if c.proposal.risk_level == "high")
        print(f"\n  decision cards: {len(decision_cards)} distinct dead link(s) surfaced "
              f"for human review ({high} high-risk -> single-card approval; "
              f"{len(decision_cards) - high} batchable).")

    if args.dry_run:
        print("\n[2/2] --dry-run: nothing written to any database (read-only scan).")
        return 0
    try:
        n, enqueued = _persist(report, audit.records, decision_cards)
    except RuntimeError as e:
        print(f"\n[2/2] skipped persistence: {e}", file=sys.stderr)
        return 0
    print(f"\n[2/2] persisted {n} slot_checks (+{len(audit.records)} audit rows) and "
          f"enqueued {enqueued} decision card(s) [pending] to EverLink's operational DB.")
    return 0


def cmd_decisions(args: argparse.Namespace) -> int:
    """List decision cards + status counts (the async-Interrupt queue's read model).

    ``--json`` emits the exact shape the pd3 board consumes, so this command is both
    a demo/inspection surface and the panel's first backend probe.
    """
    try:
        conn, store = _open_db_store()
    except RuntimeError as e:
        print(f"[everlink] decisions unavailable: {e}", file=sys.stderr)
        return 2
    try:
        status = None if args.status == "all" else args.status
        rows = store.list_by_status(status, limit=args.limit)
        counts = store.counts()
        if args.json:
            print(json.dumps({"counts": counts, "decisions": [c.model_dump() for c in rows]},
                             indent=2, default=str))
            return 0
        print(f"decision queue - counts by status: {counts or {}}")
        if not rows:
            print(f"  no '{status or 'all'}' decision cards.")
            return 0
        print(f"  showing {len(rows)} '{status or 'all'}' card(s):")
        for c in rows:
            print(f"   * {c.id}  [{c.status}]  {c.proposal.action} "
                  f"(risk={c.proposal.risk_level})")
            print(f"       slots: {','.join(c.affected_slot_ids)}")
            print(f"       why  : {c.proposal.rationale}")
            if c.status == "rejected" and c.reject_reason:
                print(f"       rejected: {c.reject_reason}")
        return 0
    finally:
        conn.close()


def cmd_decide(args: argparse.Namespace) -> int:
    """Approve or reject ONE decision card — the human's async-Interrupt response.

    This is the CLI twin of the pd3 board's approve/reject control: both call the
    SAME ``DecisionStore`` transition, so an approval here is exactly what the worker
    waits on. A rejection records the reason the agent remembers (spec §4.3).
    """
    if bool(args.approve) == bool(args.reject):
        print("[everlink] decide: pass exactly one of --approve / --reject.", file=sys.stderr)
        return 2
    try:
        conn, store = _open_db_store()
    except RuntimeError as e:
        print(f"[everlink] decide unavailable: {e}", file=sys.stderr)
        return 2
    try:
        if args.approve:
            ok = store.approve(args.id)
            print(f"  {'approved' if ok else 'NOT approved (missing or not pending)'}: {args.id}")
        else:
            ok = store.reject(args.id, args.reason or "")
            print(f"  {'rejected' if ok else 'NOT rejected (missing or not pending)'}: {args.id}")
        return 0 if ok else 1
    finally:
        conn.close()


def cmd_worker(args: argparse.Namespace) -> int:
    """Poll the durable queue and dispatch APPROVED cards (the async-Interrupt track).

    pd2 ships the queue + polling with a NULL handler: a claimed card is marked
    'applied' without touching any site (the safe default). pe1 plugs the Writer
    agent (snapshot -> apply_fix -> verify_fix) in as the handler. Every dispatch is
    audited to audit_log over the same guarded connection.
    """
    try:
        conn, store = _open_db_store()
    except RuntimeError as e:
        print(f"[everlink] worker unavailable: {e}", file=sys.stderr)
        return 2
    try:
        worker = hitl.DecisionWorker(store, handler=hitl.null_handler,
                                     audit_sink=steering.db_audit_sink(conn))
        if args.once:
            applied = worker.poll_once()
            print(f"  worker: 1 poll -> {applied} approved decision(s) applied.")
            return 0
        print(f"  worker: polling every {args.interval}s "
              f"(max_iterations={args.max_iterations or 'unbounded'}); Ctrl-C to stop.")
        try:
            total = worker.run(poll_interval=args.interval, max_iterations=args.max_iterations)
        except KeyboardInterrupt:
            print("\n  worker: stopped by operator.")
            return 0
        print(f"  worker: {total} approved decision(s) applied.")
        return 0
    finally:
        conn.close()


def _print_note(note: "notify.Note") -> None:
    """Print a composed message to stdout (used by ``notify --dry-run``)."""
    bar = "=" * 72
    print(f"\n{bar}\nSUBJECT: {note.subject}\n{'-' * 72}\n{note.text}")
    if note.html:
        print(f"{'-' * 72}\n[html part: {len(note.html)} chars]")
    print(bar)


def _print_delivery(results: list) -> None:
    """Print honest per-channel delivery outcomes (ASCII only — Windows-safe)."""
    for r in results:
        print(f"  [{r.status:7s}] {r.channel:9s} {r.detail}")


def _audit_notify(conn, kind: str, results: list, extra: dict | None = None) -> None:
    """Append one ``notify`` row to audit_log (best-effort; never crashes a push)."""
    from . import db

    payload = {
        "agent": "notifier", "event": "notify", "kind": kind,
        "channels": [r.channel for r in results],
        "sent": sum(1 for r in results if r.status == "sent"),
        "skipped": sum(1 for r in results if r.status == "skipped"),
        "failed": sum(1 for r in results if r.status == "failed"),
    }
    if extra:
        payload.update(extra)
    try:
        db.insert_audit(conn, "notifier", "notify", json.dumps(payload, default=str))
    except Exception as e:  # noqa: BLE001 - audit is best-effort, never fails a push
        print(f"  (audit skipped: {e})", file=sys.stderr)


def _brief_from_queue(store, limit: int) -> "notify.MorningBrief":
    """Build the morning brief from the live queue's counts + pending cards."""
    counts = store.counts()
    pending = store.list_by_status("pending", limit=limit)
    by_risk: dict[str, int] = {}
    by_action: dict[str, int] = {}
    high_risk_ids: list[str] = []
    for c in pending:
        by_risk[c.proposal.risk_level] = by_risk.get(c.proposal.risk_level, 0) + 1
        by_action[c.proposal.action] = by_action.get(c.proposal.action, 0) + 1
        if c.proposal.risk_level == "high":
            high_risk_ids.append(c.id)
    return notify.MorningBrief(
        decisions_pending=counts.get("pending", 0),
        problem_slots=sum(len(c.affected_slot_ids) for c in pending),
        by_risk=by_risk, by_action=by_action, high_risk_ids=high_risk_ids)


def cmd_notify(args: argparse.Namespace) -> int:
    """Push the queue to the operator over Resend/Telegram (spec §7 push-to-surface).

    Reads the SAME durable ``decisions`` queue the board and worker use, then either
    (default) risk-routes pending cards — medium/high as immediate single-card pushes,
    low rolled into one batch-approval list — or (``--brief``) sends the morning digest.

    ``--dry-run`` composes + prints and sends NOTHING over the network. Delivery is
    reported honestly: ``sent`` only on a real 2xx, ``skipped`` when a channel has no
    credentials, ``failed`` on a 4xx/5xx or transport error. Every real push is audited.
    """
    try:
        conn, store = _open_db_store()
    except RuntimeError as e:
        print(f"[everlink] notify unavailable: {e}", file=sys.stderr)
        return 2
    try:
        cfg = notify.NotifyConfig.from_env()
        if args.channel == "email":                 # channel filter => clear the other
            cfg.telegram_token, cfg.telegram_chat_ids = "", []
        elif args.channel == "telegram":
            cfg.resend_api_key, cfg.resend_from, cfg.notify_emails = "", "", []
        notifier = notify.Notifier(config=cfg)

        if args.brief:
            brief = _brief_from_queue(store, args.limit)
            if args.dry_run:
                _print_note(notify.compose_morning_brief(brief, cfg.board_url))
                print("\n  --dry-run: composed the morning brief; nothing sent.")
                return 0
            results = notifier.push_morning_brief(brief)
            print(f"morning brief -> channel(s) {notifier.active_channels() or '(none)'}:")
            _print_delivery(results)
            _audit_notify(conn, "morning_brief", results,
                          {"pending": brief.decisions_pending,
                           "problem_slots": brief.problem_slots})
            return 1 if any(r.status == "failed" for r in results) else 0

        pending = store.list_by_status("pending", limit=args.limit)
        if not pending:
            print("  no pending decision cards to push.")
            return 0
        if args.dry_run:
            route = notify.route_cards(pending)
            for c in route.immediate:
                _print_note(notify.compose_decision_card(c, cfg.board_url))
            if route.batch:
                _print_note(notify.compose_batch_list(route.batch, cfg.board_url))
            print(f"\n  --dry-run: composed {len(route.immediate)} immediate + "
                  f"{1 if route.batch else 0} batch message(s); nothing sent.")
            return 0
        results, route = notifier.push_decision_cards(pending)
        print(f"decision cards -> channel(s) {notifier.active_channels() or '(none)'}: "
              f"{len(route.immediate)} immediate (medium/high) + "
              f"{len(route.batch)} batched (low).")
        _print_delivery(results)
        _audit_notify(conn, "decision_cards", results,
                      {"immediate": len(route.immediate), "batch": len(route.batch)})
        return 1 if any(r.status == "failed" for r in results) else 0
    finally:
        conn.close()


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
    sc.add_argument("--no-enforce", action="store_true",
                    help="disable spec §6 steering hooks on the Judge (they are ON by "
                         "default; enforcement blocks/re-steers unsafe proposals)")
    sc.add_argument("--dry-run", action="store_true", help="write nothing to any database")
    sc.add_argument("--max-pages", type=int, default=None, help="generic adapter: max pages to crawl")
    sc.add_argument("--include-internal", action="store_true",
                    help="generic adapter: also report same-host links")
    sc.set_defaults(func=cmd_scan)

    dc = sub.add_parser("decisions", help="list decision cards (the async Interrupt queue)")
    dc.add_argument("--status", choices=["all", "pending", "approved", "rejected",
                                         "expired", "applied"], default="pending",
                    help="filter by card status (default pending — the review inbox)")
    dc.add_argument("--limit", type=int, default=100, help="max cards to list (default 100)")
    dc.add_argument("--json", action="store_true", help="emit JSON (the pd3 board's read model)")
    dc.set_defaults(func=cmd_decisions)

    de = sub.add_parser("decide", help="approve or reject one decision card (human response)")
    de.add_argument("id", help="decision card id (e.g. dec-abc123def0)")
    _ar = de.add_mutually_exclusive_group(required=True)
    _ar.add_argument("--approve", action="store_true", help="approve (the worker will apply it)")
    _ar.add_argument("--reject", action="store_true", help="reject (records --reason)")
    de.add_argument("--reason", default="", help="rejection reason the agent remembers")
    de.set_defaults(func=cmd_decide)

    wk = sub.add_parser("worker", help="poll + dispatch approved decisions (async track)")
    wk.add_argument("--once", action="store_true", help="drain once and exit (no poll loop)")
    wk.add_argument("--interval", type=float, default=5.0, help="seconds between polls")
    wk.add_argument("--max-iterations", type=int, default=None, help="stop after N polls")
    wk.set_defaults(func=cmd_worker)

    nt = sub.add_parser("notify", help="push the queue to the operator (Resend email / Telegram)")
    nt.add_argument("--brief", action="store_true",
                    help="send the morning digest instead of the pending decision cards")
    nt.add_argument("--channel", choices=["all", "email", "telegram"], default="all",
                    help="restrict to one channel (default: every configured channel)")
    nt.add_argument("--limit", type=int, default=100, help="max pending cards to push (default 100)")
    nt.add_argument("--dry-run", action="store_true",
                    help="compose + print; send NOTHING over the network (no email/telegram dispatched)")
    nt.set_defaults(func=cmd_notify)
    return ap


def main(argv: list[str] | None = None) -> int:
    # Composed messages use em-dash / ellipsis / risk emoji; force UTF-8 so a Windows
    # console (cp1252/cp932) can print them in `notify --dry-run` without UnicodeEncodeError.
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001 - best-effort (redirected/older streams)
            pass
    args = build_parser().parse_args(argv)
    return args.func(args)
