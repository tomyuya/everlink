"""Decision-card assembly (spec §6 / §8 hard metric 3).

Turns per-slot Judge proposals into ``Decision`` cards, MERGING cross-article
duplicates of the SAME dead link into ONE card (spec §11 demo: "跨文章合并卡").
Rationale: one dead product link syndicated across five articles is ONE problem
with ONE fix — surfacing five cards would drown the human. The card lists every
affected slot so a single approval heals all of them.

Pure and offline: no DB, no network. pd2 persists these cards to the ``decisions``
table (status=pending) as the durable Interrupt queue; pd3 renders them on the board.
"""
from __future__ import annotations

import hashlib
from typing import Iterable, Optional
from urllib.parse import urlparse, urlunparse

from .agents import SlotProposal
from .model import Decision

# risk ordering so the most conservative proposal represents a merged card
_RISK_ORDER = {"low": 0, "medium": 1, "high": 2}


def merge_key(url: str) -> str:
    """Normalized identity of a link: scheme + host + path, lowercased, no fragment
    and no volatile query. Two articles linking the same dead product page share a
    key, so they merge into one card. (Tracking-param differences are intentionally
    ignored: the same /dp/ASIN is the same offer regardless of ?tag=.)"""
    p = urlparse((url or "").strip())
    host = (p.hostname or "").lower()
    path = (p.path or "/").rstrip("/") or "/"
    return urlunparse((p.scheme.lower(), host, path, "", "", ""))


def build_decision_cards(proposals: Iterable[SlotProposal]) -> list[Decision]:
    """Group proposals by merge_key; one Decision card per distinct dead link.

    The representative proposal is the HIGHEST-RISK one in the group (fail-safe:
    if any article's context makes the fix risky, the merged card is risky and
    routes to single-card review rather than the low-risk weekly batch).
    """
    groups: dict[str, list[SlotProposal]] = {}
    order: list[str] = []
    for sp in proposals:
        k = merge_key(sp.slot.url)
        if k not in groups:
            groups[k] = []
            order.append(k)
        groups[k].append(sp)

    cards: list[Decision] = []
    for k in order:
        group = groups[k]
        rep = max(group, key=lambda sp: _RISK_ORDER.get(sp.proposal.risk_level, 0)).proposal
        digest = hashlib.sha1(k.encode("utf-8")).hexdigest()[:10]
        cards.append(Decision(
            id=f"dec-{digest}",
            affected_slot_ids=[sp.slot.id for sp in group],
            proposal=rep,
        ))
    return cards


def find_card(cards: Iterable[Decision], slot_id: str) -> Optional[Decision]:
    """The card that covers a given slot_id (or None)."""
    for c in cards:
        if slot_id in c.affected_slot_ids:
            return c
    return None
