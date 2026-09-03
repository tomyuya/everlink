"""Phase F demo seeder: inject the clearly-labelled REPLAY dataset into EverLink's
OWN store so a judge never opens an empty inbox (spec §7 line 244 / §11 beats).

The seed is built by ``everlink.seed`` — pure, offline, deterministic — and written
through the SAME guard every other EverLink write uses (``db._assert_writable``), so a
misconfigured DSN cannot touch a source site or the Blue Neon production host. The
whole write is ONE transaction (all-or-nothing) and is idempotent: re-running refreshes
exactly the seed-owned rows and nothing else.

This is a REPLAY, not live scan output and not real Bedrock decisions — every rationale
is human-authored demo copy and every row is tagged ``SEED_MARK`` so ``--reset`` can
remove it cleanly. See ``everlink/seed.py`` for the full honesty note.

Usage:
    python scripts/seed_demo.py --dry-run          # build + print counts, NO db
    python scripts/seed_demo.py --dry-run --json    # same, machine-readable
    set EVERLINK_DATABASE_URL=postgresql://...      # EverLink's own DB, NOT blue
    python scripts/seed_demo.py                     # ensure schema + write seed
    python scripts/seed_demo.py --json              # write + print db-confirmed counts
    python scripts/seed_demo.py --reset             # remove EXACTLY the seed, nothing else
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from everlink import db, seed  # noqa: E402
from everlink.db import ProductionWriteRefused  # noqa: E402


def _print_human_summary(summary: dict) -> None:
    print(f"demo seed [{summary['seed_mark']}] - {summary['kind']}")
    print(f"  generated_at   : {summary['generated_at']}")
    print(f"  problem slots  : {summary['slots']}   by site: {summary['by_site']}")
    print(f"  by verdict     : {summary['by_verdict']}")
    print(f"  protected slots: {summary['protected_slots']}")
    print(f"  scan cards     : {summary['scan_cards']}   decision rows: "
          f"{summary['decision_rows']}")
    print(f"  human triage   : approved {summary['human_approved']} / rejected "
          f"{summary['human_rejected']}")
    print(f"  worker outcome : links healed {summary['links_healed']} / rolled back "
          f"{summary['rolled_back']}")
    print(f"  final status   : {summary['final_status']}")
    print(f"  write_snapshots: {summary['write_snapshots']}   verify checks: "
          f"{summary['verify_checks']}")
    print(f"  audit rows     : {summary['audit_rows']}   events: "
          f"{summary['audit_events']}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Inject the EverLink demo seed dataset.")
    ap.add_argument("--dry-run", action="store_true",
                    help="build the plan + print counts only; do not connect or write")
    ap.add_argument("--json", action="store_true", dest="as_json",
                    help="emit machine-readable JSON (the TRUE counts) instead of prose")
    ap.add_argument("--reset", action="store_true",
                    help="remove EXACTLY the seed rows (SEED_MARK-tagged), nothing else")
    ap.add_argument("--no-ensure", action="store_true",
                    help="skip ensure_schema on write (tables already exist)")
    args = ap.parse_args()

    # --dry-run and --reset never need the plan built twice; the builder is pure.
    if args.dry_run:
        summary = seed.build_seed().summary()
        if args.as_json:
            print(json.dumps(summary, indent=2, default=str))
        else:
            _print_human_summary(summary)
            print("\n[dry-run] not connecting/writing. Set EVERLINK_DATABASE_URL and "
                  "re-run without --dry-run to persist the seed.")
        return 0

    try:
        dsn = db.everlink_dsn()
    except RuntimeError as e:
        print(f"[abort] {e}", file=sys.stderr)
        return 2

    try:
        conn = db.connect(dsn, read_only=False)
    except ProductionWriteRefused as e:
        print(f"[abort] {e}", file=sys.stderr)
        return 2

    try:
        if args.reset:
            deleted = seed.reset_seed(conn)
            if args.as_json:
                print(json.dumps({"reset": deleted}, indent=2, default=str))
            else:
                print("removed demo seed rows:")
                for table, n in deleted.items():
                    print(f"  {table}: {n}")
            return 0

        summary = seed.write_seed(conn, ensure=not args.no_ensure)
        stats = seed.seed_stats(conn)          # db-confirmed footprint of the seed
        if args.as_json:
            print(json.dumps({"plan": summary, "db": stats}, indent=2, default=str))
        else:
            _print_human_summary(summary)
            print("\ndb-confirmed seed footprint:")
            print(f"  link_slots     : {stats['slots']}")
            print(f"  decisions      : {stats['decisions']}   by status: "
                  f"{stats['by_status']}")
            print(f"  slot_checks    : {stats['slot_checks']}")
            print(f"  write_snapshots: {stats['write_snapshots']}   rolled back: "
                  f"{stats['rolled_back_snapshots']}")
            print(f"  audit rows     : {stats['audit_rows']}")
            print("\nseed written. Open the board inbox to see the 41 problem slots, "
                  "the approved/rejected cards and the rollback recommendation.")
        return 0
    except ProductionWriteRefused as e:
        print(f"[abort] {e}", file=sys.stderr)
        return 2
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
