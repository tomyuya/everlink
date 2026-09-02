"""Scan ANY site read-only for link rot — no AWS credentials required.

The generic adapter (everlink.generic) discovers outbound LinkSlot[] from a
sitemap / page / URL list; L1 (probes) + optional L2 (l2) detect rot. Detection
is pure HTTP — no LLM — so a judge can point this at their own blog and get a
real dead-link report with zero AWS setup. NOTHING is written back: the generic
adapter is read-only by design (spec §4.1 / §11 demo shot).

Usage:
    python scripts/scan_site.py https://example.com/sitemap.xml --max-pages 10
    python scripts/scan_site.py https://example.com/blog/a-post --l2
    python scripts/scan_site.py https://a.com/p1 https://a.com/p2      # URL list

Politeness: <=1 request per link by default (L1 only); --l2 adds a second,
selective request for ambiguous/soft-404 suspects. robots.txt is respected
(fail-open) unless --ignore-robots.
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from everlink.generic import extract_slots_generic  # noqa: E402
from everlink.l2 import L2Result, probe_l2  # noqa: E402
from everlink.model import Verdict  # noqa: E402
from everlink.probes import probe_url  # noqa: E402


def _final_verdict(l1_verdict: Verdict, l2: L2Result | None) -> Verdict:
    """Combine L1 + optional L2 into one verdict (detection pyramid, spec §4.1)."""
    if l2 is None:
        return l1_verdict
    if l1_verdict in ("dead", "program_ended"):
        return l1_verdict                      # L1 already conclusive
    if l2.verdict == "dead":
        return "dead"
    if l2.verdict in ("unavailable", "price_anomaly"):
        return "offer_changed"                 # page lives, the offer died
    if l2.verdict == "blocked":
        return "needs_human_recheck"           # bot-wall: agent knows its limits
    return "healthy"                           # L2 confirms a genuinely live page


def main() -> int:
    ap = argparse.ArgumentParser(description="Read-only link-rot scan of any site.")
    ap.add_argument("source", nargs="+",
                    help="sitemap URL, single page URL, or a list of page URLs")
    ap.add_argument("--site", default=None, help="override the site label")
    ap.add_argument("--max-pages", type=int, default=10)
    ap.add_argument("--max-slots", type=int, default=50)
    ap.add_argument("--rate-delay", type=float, default=1.0,
                    help="seconds between requests (politeness)")
    ap.add_argument("--timeout", type=float, default=20.0)
    ap.add_argument("--include-internal", action="store_true",
                    help="also report same-host links (default: outbound only)")
    ap.add_argument("--l2", action="store_true",
                    help="run L2 page-parse on ambiguous/soft-404 suspects")
    ap.add_argument("--ignore-robots", action="store_true",
                    help="ignore robots.txt (default: respect it, fail-open)")
    args = ap.parse_args()

    source = args.source[0] if len(args.source) == 1 else args.source
    print(f"[1/3] discovering outbound slots from: {source}")
    slots = extract_slots_generic(
        source, site=args.site, max_pages=args.max_pages, max_slots=args.max_slots,
        rate_delay=args.rate_delay, timeout=args.timeout,
        include_internal=args.include_internal, respect_robots=not args.ignore_robots)
    if not slots:
        print("  no outbound slots discovered "
              "(robots-blocked, empty page, or fetch failed).")
        return 1
    by_type = Counter(s.slot_type for s in slots)
    print(f"  found {len(slots)} outbound slots on '{slots[0].site}': {dict(by_type)}")

    print(f"\n[2/3] probing (L1{'' if not args.l2 else ' + L2'}), <=1 request per link ...")
    rows: list[tuple] = []
    verdicts: Counter = Counter()
    for i, slot in enumerate(slots, 1):
        l1 = probe_url(slot.url, slot.id, timeout=args.timeout)
        l2 = None
        if args.l2 and l1.final_verdict in ("healthy", "needs_human_recheck"):
            l2 = probe_l2(slot.url, timeout=args.timeout)
        verdict = _final_verdict(l1.final_verdict, l2)
        verdicts[verdict] += 1
        rows.append((slot, verdict, l1.l1_status, l2.verdict if l2 else ""))
        mark = "" if verdict == "healthy" else f"  <-- {verdict}"
        print(f"  [{i}/{len(slots)}] {verdict:20s} {slot.url[:72]}{mark}")

    problems = [r for r in rows if r[1] != "healthy"]
    print(f"\n[3/3] report - scanned {len(rows)} outbound links on '{slots[0].site}'")
    print(f"  verdicts: {dict(verdicts)}")
    print(f"  {len(problems)} need attention, {len(rows) - len(problems)} healthy.")
    if problems:
        print("\n  --- problem links (read-only; nothing written back) ---")
        for slot, verdict, status, l2v in problems:
            anchor = slot.anchor_text or "(no anchor text)"
            extra = f"  L2={l2v}" if l2v else ""
            print(f"   * [{verdict}] {slot.url}")
            print(f"       found on: {slot.article_id}")
            print(f"       anchor: {anchor!r}  |  L1 HTTP {status}{extra}")
    print("\n  (fix proposals need the Judge agent + Bedrock; see `everlink scan`.)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
