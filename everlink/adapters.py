"""Adapters: turn raw site exports into typed LinkSlot objects (spec §4.1).

Phase A already snapshots each site to `data/slots_*.csv` via read-only SELECTs
(see scripts/export_slots.py). The CSVs are the primary pipeline input, so the
Scanner reads them here rather than re-hitting the production databases on every
run. A uniform `load_slots(site)` interface keeps the door open for live
per-site adapters later without changing callers.
"""
from __future__ import annotations

import csv
from pathlib import Path

from .model import LinkSlot

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
SITES = ("aethelgem", "sandcart", "hotdeals")


def _row_to_slot(row: dict) -> LinkSlot:
    return LinkSlot(
        id=row["id"],
        site=row["site"],
        article_id=row.get("article_id", ""),
        article_title=row.get("article_title", ""),
        block_id=row.get("block_id", ""),
        block_type=row.get("block_type", ""),
        slot_type=row["slot_type"],
        role=(row.get("role") or None),
        anchor_text=(row.get("anchor_text") or None),
        url=row["url"],
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
