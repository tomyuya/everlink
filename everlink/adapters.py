"""Adapters: turn raw site exports into typed LinkSlot objects (spec §4.1).

Phase A already snapshots each site to `data/slots_*.csv` via read-only SELECTs
(see scripts/export_slots.py). The CSVs are the primary pipeline input, so the
Scanner reads them here rather than re-hitting the production databases on every
run. A uniform `load_slots(site)` interface keeps the door open for live
per-site adapters later without changing callers.
"""
from __future__ import annotations

import csv
import os
from pathlib import Path
from urllib.parse import urljoin

from .model import LinkSlot

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
SITES = ("aethelgem", "sandcart", "hotdeals")


def resolve_origin(site: str) -> str | None:
    """The public origin a DEPLOYER configures for one site, via env.

    Symmetric with ``<SITE>_DATABASE_URL`` (see db.SOURCE_DSN_VARS). Some source
    databases store INTERNAL links as bare relative paths (e.g. ``/products/...``);
    a relative URL has no scheme, so the probe-side SSRF guard rejects it and the
    whole site surfaces as false ``needs_human_recheck`` cards. Resolving against
    the site's configured origin at ingestion fixes the root cause.

    NOTHING is hardcoded: this is an open-source, self-hosted project, so the repo
    can never know a deployer's domain. An unset origin returns ``None`` and the
    relative URL is left as-is — the missing config surfaces honestly instead of a
    guessed domain being fabricated.
    """
    return os.environ.get(f"{site.upper()}_PUBLIC_ORIGIN") or None


def absolutize_slot_url(url: str, origin: str | None) -> str:
    """Resolve a slot URL against a deployer-configured origin (pure function).

    * Already-absolute URLs (http/https) are returned unchanged — no double-prefix.
    * Relative internal links gain the origin via ``urljoin``.
    * No configured origin (or empty url) is returned as-is — never a guessed domain.
    """
    if not origin or not url:
        return url
    if url.startswith(("http://", "https://")):
        return url
    return urljoin(origin, url)


def _row_to_slot(row: dict) -> LinkSlot:
    site = row["site"]
    return LinkSlot(
        id=row["id"],
        site=site,
        article_id=row.get("article_id", ""),
        article_title=row.get("article_title", ""),
        block_id=row.get("block_id", ""),
        block_type=row.get("block_type", ""),
        slot_type=row["slot_type"],
        role=(row.get("role") or None),
        anchor_text=(row.get("anchor_text") or None),
        url=absolutize_slot_url(row["url"], resolve_origin(site)),
        regions=(row.get("regions") or None),
        protected=int(row.get("protected") or 0),
    )


def load_csv(path: str | Path) -> list[LinkSlot]:
    p = Path(path)
    if not p.exists():
        return []
    with open(p, encoding="utf-8", newline="") as f:
        return [_row_to_slot(r) for r in csv.DictReader(f)]


def load_slots(site: str, data_dir: str | Path = DATA_DIR) -> list[LinkSlot]:
    """Load one site's slots from its CSV snapshot."""
    return load_csv(Path(data_dir) / f"slots_{site}.csv")


def load_all(data_dir: str | Path = DATA_DIR) -> list[LinkSlot]:
    """Load every site's slots (prefers the merged slots_all.csv)."""
    merged = Path(data_dir) / "slots_all.csv"
    if merged.exists():
        return load_csv(merged)
    out: list[LinkSlot] = []
    for site in SITES:
        out.extend(load_slots(site, data_dir))
    return out


def extract_slots(site: str, **kwargs) -> list[LinkSlot]:
    """Unified adapter entrypoint (spec §4.1): ``extract_slots(site) -> LinkSlot[]``.

    * One of the three first-party site names -> read its Phase-A CSV snapshot.
    * Anything else (a page URL, a sitemap URL, or a list of URLs) -> the
      read-only ``generic`` adapter, which crawls and NEVER writes back.
    """
    if site in SITES:
        return load_slots(site)
    from .generic import extract_slots_generic
    return extract_slots_generic(site, **kwargs)
