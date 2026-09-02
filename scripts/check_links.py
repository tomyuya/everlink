"""Phase B verification: run the L1 probe over a small real sample.

Loads the Phase A snapshot (data/slots_all.csv), samples a few slots per site,
probes each live URL politely (<=1 request, rate-limited), and prints the
verdict distribution. Relative/internal URLs are skipped (they need a per-site
base domain, wired up in a later phase) — this is reported honestly, not hidden.

Usage:
    python scripts/check_links.py --per-site 3 --delay 1.5
"""
from __future__ import annotations

import argparse
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from everlink.adapters import load_all  # noqa: E402
from everlink.probes import probe_url  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-site", type=int, default=3)
    ap.add_argument("--delay", type=float, default=1.5, help="seconds between requests")
    ap.add_argument("--timeout", type=float, default=15.0)
    ap.add_argument("--max-hops", type=int, default=6)
    args = ap.parse_args()

    slots = load_all()
    if not slots:
        print("no slots found — run scripts/export_slots.py first")
        return 1

    by_site: dict[str, list] = {}
    for s in slots:
        by_site.setdefault(s.site, []).append(s)

    dist: Counter = Counter()
    probed = skipped = 0
    for site, site_slots in sorted(by_site.items()):
        print(f"\n=== {site} ({len(site_slots)} slots; sampling {args.per_site}) ===")
        for s in site_slots[: args.per_site]:
            if not s.url.lower().startswith("http"):
                skipped += 1
                dist["skipped_relative"] += 1
                print(f"  [skip] {s.id}  relative/internal url: {s.url[:50]}")
                continue
            r = probe_url(s.url, s.id, timeout=args.timeout, max_hops=args.max_hops)
            probed += 1
            dist[r.final_verdict] += 1
            hops = " -> ".join(f"{h.status}" for h in r.redirect_chain) or "-"
            print(f"  [{r.final_verdict}] {s.id}")
            print(f"      url: {s.url[:70]}")
            print(f"      status={r.l1_status} chain=[{hops}] evidence={r.l2_evidence or '-'}")
            if args.delay:
                time.sleep(args.delay)

    print(f"\n=== summary ===")
    print(f"probed={probed} skipped_relative={skipped}")
    for k, v in dist.most_common():
        print(f"  {k}: {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
