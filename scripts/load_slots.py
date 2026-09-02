"""Phase B loader: create EverLink schema + load the LinkSlot snapshot into it.

Reads data/slots_all.csv (Phase A) and upserts into EverLink's OWN database
(EVERLINK_DATABASE_URL). Refuses to run against the Blue Neon production host
(guard in everlink.db), so a misconfigured DSN cannot touch production.

Usage:
    set EVERLINK_DATABASE_URL=postgresql://...   # EverLink's own DB, NOT blue
    python scripts/load_slots.py --dry-run       # preview counts, no write
    python scripts/load_slots.py                 # ensure schema + upsert
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from everlink import db  # noqa: E402
from everlink.adapters import load_all  # noqa: E402
from everlink.db import ProductionWriteRefused  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default=None)
    ap.add_argument("--dry-run", action="store_true",
                    help="load + count only; do not connect or write")
    args = ap.parse_args()

    slots = load_all(args.data_dir) if args.data_dir else load_all()
    if not slots:
        print("no slots found — run scripts/export_slots.py first")
        return 1
    per_site = Counter(s.site for s in slots)
    per_type = Counter(s.slot_type for s in slots)
    print(f"loaded {len(slots)} slots from snapshot")
    print(f"  by site: {dict(per_site)}")
    print(f"  by slot_type: {dict(per_type)}")

    if args.dry_run:
        print("\n[dry-run] not connecting/writing. Set EVERLINK_DATABASE_URL and "
              "re-run without --dry-run to create schema + upsert.")
        return 0

    try:
        dsn = db.everlink_dsn()
    except RuntimeError as e:
        print(f"\n[abort] {e}")
        return 2

    try:
        conn = db.connect(dsn, read_only=False)
    except ProductionWriteRefused as e:
        print(f"\n[abort] {e}")
        return 2
    try:
        db.ensure_schema(conn)          # idempotent; guarded against blue host
        n = db.upsert_link_slots(conn, slots)
        print(f"\nensured schema; upserted {n} link_slots rows")
        for site in sorted(per_site):
            print(f"  link_slots[{site}] = {db.count_slots(conn, site)}")
    except ProductionWriteRefused as e:
        print(f"\n[abort] {e}")
        return 2
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
