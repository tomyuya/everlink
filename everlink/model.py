"""Pydantic models shared across the Scanner / Judge / Writer agents.

These mirror the spec §5 tables and §6 Proposal schema. Structured Output for
the Judge agent is enforced against `Proposal`.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

SlotType = Literal["commercial", "reference", "internal", "component"]
Action = Literal[
    "REPLACE_URL", "REWRITE_ANCHOR", "REWRITE_SENTENCE", "DROP_BLOCK", "ESCALATE_HUMAN"
]
Verdict = Literal[
    "healthy", "dead", "offer_changed", "program_ended", "needs_human_recheck"
]
RiskLevel = Literal["low", "medium", "high"]


class LinkSlot(BaseModel):
    """One outbound link location on a site (spec §5 link_slots)."""

    id: str
    site: str
    article_id: str
    article_title: str
    block_id: str
    block_type: str
    slot_type: SlotType
    role: Optional[str] = None
    anchor_text: Optional[str] = None
    url: str
    target_url: Optional[str] = None
    surrounding_sentence: Optional[str] = None
    regions: Optional[str] = None          # JSON array string, e.g. '["us","ca"]'
    protected: int = 0
    status: str = "active"


class RedirectHop(BaseModel):
    url: str
    status: int


class CheckResult(BaseModel):
    """Outcome of probing one slot (spec §5 slot_checks)."""

    slot_id: str
    l1_status: Optional[int] = None
    redirect_chain: list[RedirectHop] = Field(default_factory=list)
    l2_verdict: Optional[str] = None
    l2_evidence: Optional[str] = None
    final_verdict: Verdict
    error: Optional[str] = None            # transport error text, if any


class Proposal(BaseModel):
    """Judge agent structured output (spec §6). One proposed fix for a card."""

    action: Action
    new_url: Optional[str] = None
    new_anchor: Optional[str] = None
    new_sentence: Optional[str] = None
    rationale: str
    risk_level: RiskLevel


class Decision(BaseModel):
    """A surfaced decision card (spec §5 decisions); may merge several slots."""

    id: str
    affected_slot_ids: list[str]
    proposal: Proposal
    status: Literal["pending", "approved", "rejected", "expired"] = "pending"
    reject_reason: Optional[str] = None
