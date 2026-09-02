"""Detection orchestration: the L1 + L2 pyramid over link slots (spec §4.1).

Bridges ``probes`` (L1: HTTP status + redirect-chain analysis) and ``l2``
(L2: page parse) into one pass with the escalation rule, plus a batch runner.
This is PURE detection — no LLM — so it runs offline with zero AWS credentials
and is the deterministic heart shared by the Scanner tool, the ``everlink scan``
CLI, ``scripts/scan_site.py`` and the Evals harness.

Escalation rule (spec §4.1 "agent knows its limits, never fabricates"):
  * L1 conclusive (dead / program_ended)      -> keep it, skip L2 (save a request)
  * L1 healthy                                 -> run L2 to catch the soft-404
  * L1 needs_human_recheck (blocked/403/timeout)-> run L2 as a second opinion
  * L2 dead                                    -> dead
  * L2 unavailable / price_anomaly             -> offer_changed (page lives, offer died)
  * L2 blocked                                 -> needs_human_recheck
  * L2 ok                                      -> healthy
"""
from __future__ import annotations

import re
import time
from typing import Iterable, Optional

from .l2 import probe_l2
from .model import CheckResult, LinkSlot, Verdict
from .probes import probe_url

# Verdicts where a second (L2) request is worth spending.
_L2_ESCALATE: tuple[Verdict, ...] = ("healthy", "needs_human_recheck")
_PRICE_RE = re.compile(r"(?:\$|£|€|¥|USD|GBP|EUR)\s?\d[\d.,]*", re.I)


def claimed_price_from_text(text: Optional[str]) -> Optional[str]:
    """First currency amount mentioned in a sentence (the article's claim).

    Used so L2 can flag a price_anomaly when the live price has drifted far above
    what the surrounding sentence promises.
    """
    if not text:
        return None
    m = _PRICE_RE.search(text)
    return m.group(0).strip() if m else None


def combine_verdict(l1_verdict: Verdict, l2_verdict: Optional[str]) -> Verdict:
    """PURE: fold an L1 verdict + optional L2 verdict into one final verdict."""
    if l2_verdict is None:
        return l1_verdict
    if l1_verdict in ("dead", "program_ended"):
        return l1_verdict                       # L1 already conclusive
    if l2_verdict == "dead":
        return "dead"
    if l2_verdict in ("unavailable", "price_anomaly"):
        return "offer_changed"
    if l2_verdict == "blocked":
        return "needs_human_recheck"
    return "healthy"                            # L2 confirms a genuinely live page


def check_slot(slot: LinkSlot, *, timeout: float = 15.0, use_l2: bool = True,
               claimed_price: Optional[str] = None,
               engine: str = "auto") -> CheckResult:
    """Detect rot for ONE slot: L1 always, L2 selectively (see escalation rule)."""
    l1 = probe_url(slot.url, slot.id, timeout=timeout)
    l2_verdict: Optional[str] = None
    evidence = l1.l2_evidence                   # L1's redirect-chain evidence
    if use_l2 and l1.final_verdict in _L2_ESCALATE:
        claim = claimed_price or claimed_price_from_text(slot.surrounding_sentence)
        l2 = probe_l2(slot.url, claimed_price=claim, timeout=timeout, engine=engine)
        l2_verdict = l2.verdict
        evidence = l2.evidence or evidence
    return CheckResult(
        slot_id=slot.id,
        l1_status=l1.l1_status,
        redirect_chain=l1.redirect_chain,
        l2_verdict=l2_verdict,
        l2_evidence=evidence,
        final_verdict=combine_verdict(l1.final_verdict, l2_verdict),
        error=l1.error,
    )


def check_slots(slots: Iterable[LinkSlot], *, rate_delay: float = 1.0,
                timeout: float = 15.0, use_l2: bool = True,
                limit: Optional[int] = None, engine: str = "auto") -> list[CheckResult]:
    """Detect rot across slots politely (<=1 request/link, `rate_delay` apart)."""
    out: list[CheckResult] = []
    for i, slot in enumerate(slots):
        if limit is not None and i >= limit:
            break
        out.append(check_slot(slot, timeout=timeout, use_l2=use_l2, engine=engine))
        if rate_delay:
            time.sleep(rate_delay)
    return out
