"""Steering hooks (spec §4.3 / §6): runtime ENFORCEMENT of EverLink's safety rules.

These are Strands hook callbacks, wired into the agents exactly as spec §6 lays out::

    scanner = Agent(..., hooks=[audit])
    judge   = Agent(..., hooks=[scope_policy, editorial_policy, audit])
    writer  = Agent(..., hooks=[write_gate, disclosure_policy, audit], ...)

Single source of truth: the disclosure/scope DECISIONS come from ``everlink.policy``
— the same pure oracle the Evals harness scores (spec §8). So what Evals measure is
literally what production enforces at runtime: no drift between the two.

Two enforcement mechanisms
--------------------------
* Guide (``BeforeToolCallEvent``): a policy sets ``event.cancel_tool`` to a guidance
  string. Strands cancels the tool call and feeds that string back to the model as an
  errored tool result, forcing it to re-decide compliantly. This is the same Guide
  pattern Strands' own vended steering plugin uses.
* Audit (``AfterToolCallEvent``): every tool call — including ones a policy cancelled
  (``cancel_message`` set) — is recorded, so the audit trail shows both what the agent
  did and what steering blocked.

How a hook sees the decision
----------------------------
The Judge emits its proposal as the ``Proposal`` structured-output tool call, so on
that event ``event.tool_use["name"] == "Proposal"`` and ``event.tool_use["input"]``
holds the proposal fields. The slot being judged is threaded by the orchestrator via
``judge(prompt, invocation_state={"slot": slot.model_dump()})`` and read back here
from ``event.invocation_state["slot"]``. If either is absent the hook is inert (it
cannot judge without context); the JUDGE_SYSTEM_PROMPT still states the rules and the
Evals oracle still scores them.
"""
from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any, Optional

from strands.hooks import AfterToolCallEvent, BeforeToolCallEvent

from . import db, policy
from .model import LinkSlot, Proposal

# The Judge's structured-output tool is named after the Pydantic model (spec §6).
_PROPOSAL_TOOL = Proposal.__name__

# Writer tools that mutate a site; write_gate guards exactly these (spec §4.3-4).
WRITE_TOOLS = ("apply_fix", "rollback")

_GUIDE = "Tool call cancelled by EverLink steering [{policy}]. {reason}"


# --------------------------------------------------------------------------- #
# event -> domain object extraction (defensive; hooks must never raise)
# --------------------------------------------------------------------------- #
def slot_from_event(event: BeforeToolCallEvent) -> Optional[LinkSlot]:
    """Reconstruct the LinkSlot the orchestrator threaded via invocation_state."""
    raw = (event.invocation_state or {}).get("slot")
    if isinstance(raw, LinkSlot):
        return raw
    if isinstance(raw, dict):
        try:
            return LinkSlot.model_validate(raw)
        except Exception:
            return None
    return None


def proposal_from_event(event: BeforeToolCallEvent) -> Optional[Proposal]:
    """Return the Judge's Proposal iff this event is the structured-output call."""
    if event.tool_use.get("name") != _PROPOSAL_TOOL:
        return None
    raw = event.tool_use.get("input")
    if not isinstance(raw, dict):
        return None
    try:
        return Proposal.model_validate(raw)
    except Exception:
        return None


def guide(event: BeforeToolCallEvent, policy_name: str, reason: str) -> None:
    """Cancel the tool call and steer the model (Guide pattern)."""
    event.cancel_tool = _GUIDE.format(policy=policy_name, reason=reason)


def _agent_name(event: Any, fallback: str = "") -> str:
    if fallback:
        return fallback
    agent = getattr(event, "agent", None)
    return getattr(agent, "name", None) or (type(agent).__name__ if agent else "agent")


# --------------------------------------------------------------------------- #
# BeforeToolCallEvent policies (spec §4.3-1..3) — pure, oracle-backed
# --------------------------------------------------------------------------- #
def disclosure_policy(event: BeforeToolCallEvent) -> None:
    """spec §4.3-1: a protected (affiliate/disclosure) slot must NEVER be modified.

    Three-layer protection lives in ``policy.is_protected`` (structural immunity /
    explicit marker / regex-keyword). If the Judge proposed a modifying action on a
    protected slot we cancel and steer it to ESCALATE_HUMAN.
    """
    slot = slot_from_event(event)
    proposal = proposal_from_event(event)
    if slot is None or proposal is None:
        return
    violation = policy.disclosure_violation(slot, proposal)
    if violation:
        guide(event, "disclosure_policy",
               f"{violation} Re-decide with action=ESCALATE_HUMAN; disclosure-bearing "
               f"blocks are never edited or dropped by an agent.")


def scope_policy(event: BeforeToolCallEvent) -> None:
    """spec §4.3-3: a ``reference`` slot must NEVER get REPLACE_URL.

    Reference links (citations, sources, docs) are not re-pointed at merchants. The
    oracle is ``policy.scope_violation``; on a hit we cancel and steer to
    REWRITE_SENTENCE or ESCALATE_HUMAN.
    """
    slot = slot_from_event(event)
    proposal = proposal_from_event(event)
    if slot is None or proposal is None:
        return
    violation = policy.scope_violation(slot, proposal)
    if violation:
        guide(event, "scope_policy",
               f"{violation} Re-decide with REWRITE_SENTENCE (downgrade the claim) or "
               f"ESCALATE_HUMAN; never REPLACE_URL a reference link.")


def _editorial_violation(event: BeforeToolCallEvent, proposal: Proposal) -> Optional[str]:
    """spec §4.3-2 structural invariants for a rewrite/replace proposal.

    The deep editorial judgement (does the rewrite preserve the sentence's factual
    claims?) is the model's job per the system prompt; the hook enforces the concrete,
    checkable invariants so a sloppy proposal cannot slip through:
      * a rewrite/replace action must actually carry its replacement content;
      * a rewrite must NOT preserve a price the detector already flagged as anomalous
        (the orchestrator threads that price via invocation_state['claimed_price']).
    """
    action = proposal.action
    if action == "REWRITE_SENTENCE" and not (proposal.new_sentence or "").strip():
        return "REWRITE_SENTENCE requires a non-empty new_sentence."
    if action == "REWRITE_ANCHOR" and not (proposal.new_anchor or "").strip():
        return "REWRITE_ANCHOR requires a non-empty new_anchor."
    if action == "REPLACE_URL" and not (proposal.new_url or "").strip():
        return "REPLACE_URL requires a non-empty new_url."
    claimed = (event.invocation_state or {}).get("claimed_price")
    if claimed and proposal.new_sentence and str(claimed) in proposal.new_sentence:
        return (f"the rewrite preserves the flagged stale price '{claimed}'; a re-link "
                f"must downgrade or remove it, not carry it over.")
    return None


def editorial_policy(event: BeforeToolCallEvent) -> None:
    """spec §4.3-2: guard the structural integrity of a rewrite/replace proposal."""
    proposal = proposal_from_event(event)
    if proposal is None:
        return
    violation = _editorial_violation(event, proposal)
    if violation:
        guide(event, "editorial_policy",
               f"{violation} Re-decide with the corrected content, or ESCALATE_HUMAN if "
               f"no rule-preserving rewrite exists.")


# --------------------------------------------------------------------------- #
# write_gate (spec §4.3-4) — needs an approval lookup, so it is a factory
# --------------------------------------------------------------------------- #
def make_write_gate(is_approved: Callable[[str], bool],
                    write_tools: tuple[str, ...] = WRITE_TOOLS) -> Callable:
    """Build the write_gate BeforeToolCallEvent callback.

    A mutating Writer tool (``apply_fix``/``rollback``) is refused unless it carries a
    ``decision_id`` whose card is exactly ``approved``. ``is_approved(decision_id)``
    is injected so the gate is testable offline and DB-backed in production
    (see ``db_decision_approval``).
    """
    def write_gate(event: BeforeToolCallEvent) -> None:
        if event.tool_use.get("name") not in write_tools:
            return
        decision_id = (event.tool_use.get("input") or {}).get("decision_id")
        tool = event.tool_use.get("name")
        if not decision_id:
            guide(event, "write_gate",
                   f"{tool} requires an approved decision_id; none was provided. "
                   f"Refusing to write to a site without a human-approved decision.")
            return
        if not is_approved(str(decision_id)):
            guide(event, "write_gate",
                   f"decision '{decision_id}' is not approved. Refusing to write; only "
                   f"a human-approved decision may mutate a site.")
    return write_gate


# --------------------------------------------------------------------------- #
# audit (spec §5 audit_log) — needs a sink, so it is a factory
# --------------------------------------------------------------------------- #
def make_audit(sink: Callable[[dict], None], agent_name: str = "") -> Callable:
    """Build the audit AfterToolCallEvent callback.

    Records every tool call to ``sink``. A call that steering cancelled is recorded
    with event='steering_cancel' (its ``cancel_message`` is preserved), so the audit
    trail shows both actions taken and actions blocked. The sink is wrapped so an
    audit failure can never break the agent loop.
    """
    def audit(event: AfterToolCallEvent) -> None:
        result = event.result if isinstance(event.result, dict) else {}
        record = {
            "agent": _agent_name(event, agent_name),
            "event": "steering_cancel" if event.cancel_message else "tool_result",
            "tool": event.tool_use.get("name"),
            "tool_use_id": event.tool_use.get("toolUseId"),
            "input": event.tool_use.get("input"),
            "status": result.get("status"),
            "cancel_message": event.cancel_message,
            "duration": event.duration,
            "error": repr(event.exception) if event.exception else None,
        }
        try:
            sink(record)
        except Exception:
            pass  # auditing is best-effort; never break the agent
    return audit


class AuditCollector:
    """In-memory audit sink: collects records for tests / batch-flush by a caller."""

    def __init__(self) -> None:
        self.records: list[dict] = []

    def __call__(self, record: dict) -> None:
        self.records.append(record)

    def events(self) -> list[str]:
        return [r.get("event", "") for r in self.records]


def db_audit_sink(conn) -> Callable[[dict], None]:
    """Production audit sink: append each record to audit_log over ``conn``."""
    def sink(record: dict) -> None:
        db.insert_audit(conn, record.get("agent", ""), record.get("event", "tool_result"),
                        json.dumps(record, default=str))
    return sink


def db_decision_approval(conn) -> Callable[[str], bool]:
    """Production approval lookup for write_gate: True iff the card is 'approved'."""
    def is_approved(decision_id: str) -> bool:
        return db.decision_status(conn, decision_id) == "approved"
    return is_approved


# --------------------------------------------------------------------------- #
# spec §6 hook assembly — the exact per-agent subsets the spec lays out
# --------------------------------------------------------------------------- #
def scanner_hooks(audit_sink: Optional[Callable[[dict], None]] = None,
                  agent_name: str = "scanner") -> list:
    """spec §6: ``scanner = Agent(..., hooks=[audit])``."""
    return [make_audit(audit_sink or AuditCollector(), agent_name=agent_name)]


def judge_hooks(audit_sink: Optional[Callable[[dict], None]] = None,
                agent_name: str = "judge") -> list:
    """spec §6: ``judge = Agent(..., hooks=[scope_policy, editorial_policy, audit])``.

    NOTE: disclosure is enforced at WRITE time (writer_hooks) and SCORED at judge
    time by the Evals oracle — the judge is additionally steered by its system
    prompt (rule 1). This split is deliberate (defense in depth + human approval).
    """
    return [scope_policy, editorial_policy,
            make_audit(audit_sink or AuditCollector(), agent_name=agent_name)]


def writer_hooks(is_approved: Callable[[str], bool],
                 audit_sink: Optional[Callable[[dict], None]] = None,
                 agent_name: str = "writer") -> list:
    """spec §6: ``writer = Agent(..., hooks=[write_gate, disclosure_policy, audit])``."""
    return [make_write_gate(is_approved), disclosure_policy,
            make_audit(audit_sink or AuditCollector(), agent_name=agent_name)]
