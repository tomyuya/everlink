"""Human-in-the-loop execution: EverLink's TWO Interrupt tracks (README / spec §6).

Track 1 - SYNC (live demo): ``make_sync_approval_gate`` builds a BeforeToolCallEvent
hook that calls ``event.interrupt(...)``. Strands pauses the agent loop and surfaces
the interrupt in ``AgentResult.interrupts``; the operator responds in-band and the
agent resumes via ``run_judge_sync``. This is Strands' native human-in-the-loop.

Track 2 - ASYNC (production): ``DecisionWorker`` drains the durable decision queue
(``everlink.queue``). A human approves a card out-of-band (board pd3 / notifications
pd4); the worker polls ``claim_next_approved``, dispatches it to a handler (the
Writer, pe1), then ``mark_applied``.

Both tracks gate the SAME high-risk fix and both sit behind write_gate (spec §4.3-4),
so an unapproved action can never reach a site. Same ``Proposal`` schema on both.
"""
from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any, Optional

from strands.hooks import BeforeToolCallEvent

from . import steering
from .model import Decision
from .queue import DecisionStore


# --------------------------------------------------------------------------- #
# Track 1 - synchronous interrupt gate (spec §6 "Interrupt")
# --------------------------------------------------------------------------- #
def is_high_risk_proposal(event: BeforeToolCallEvent) -> bool:
    """True when the Judge's structured Proposal carries risk_level == 'high'."""
    prop = steering.proposal_from_event(event)
    return prop is not None and prop.risk_level == "high"


def _interrupt_reason(event: BeforeToolCallEvent) -> dict:
    """The payload a human sees when the agent pauses (slot + proposed fix)."""
    prop = steering.proposal_from_event(event)
    slot = steering.slot_from_event(event)
    return {
        "kind": "high_risk_fix",
        "slot_id": slot.id if slot else None,
        "site": slot.site if slot else None,
        "url": slot.url if slot else None,
        "action": prop.action if prop else None,
        "new_url": prop.new_url if prop else None,
        "rationale": prop.rationale if prop else None,
        "risk_level": prop.risk_level if prop else None,
        "how_to_respond": "respond 'A' to approve; any other value rejects",
    }


def make_sync_approval_gate(
    needs_approval: Callable[[BeforeToolCallEvent], bool] = is_high_risk_proposal,
    interrupt_name: str = "everlink_high_risk_fix",
    approved_response: str = "A",
    audit_sink: Optional[Callable[[dict], None]] = None,
) -> Callable:
    """Build a BeforeToolCallEvent hook that pauses for a LIVE human approval.

    On a gated tool call the hook calls ``event.interrupt(name, reason)``. The first
    time, Strands raises ``InterruptException``: the loop stops and the interrupt is
    returned in ``AgentResult.interrupts``. The operator resumes the agent with an
    ``interruptResponse`` (see ``run_judge_sync``); ``event.interrupt`` then returns
    that response. Anything other than ``approved_response`` cancels the tool via the
    Guide pattern and steers the model to ESCALATE_HUMAN, so a rejected fix is never
    applied. ``needs_approval`` is injectable so the same gate can protect the
    Writer's ``apply_fix`` in pe1 (not just the Judge's high-risk Proposal).
    """
    def gate(event: BeforeToolCallEvent) -> None:
        if not needs_approval(event):
            return
        approval = event.interrupt(interrupt_name, reason=_interrupt_reason(event))
        if audit_sink is not None:
            try:
                audit_sink({"agent": "judge", "event": "interrupt",
                            "interrupt": interrupt_name, "response": approval,
                            "tool": event.tool_use.get("name")})
            except Exception:
                pass
        if approval != approved_response:
            steering.guide(event, "sync_approval_gate",
                           f"a human operator did NOT approve this high-risk fix "
                           f"(response={approval!r}). Do not apply it; ESCALATE_HUMAN.")
    return gate


def resume_responses(result: Any, response: str = "A") -> list[dict]:
    """Build the interrupt-response payload that resumes a stopped ``AgentResult``."""
    out: list[dict] = []
    for intr in getattr(result, "interrupts", None) or []:
        out.append({"interruptResponse": {"interruptId": intr.id, "response": response}})
    return out


def run_judge_sync(judge, prompt: str, *, invocation_state: Optional[dict] = None,
                   respond: Callable[[Any], str] = lambda _reason: "A",
                   max_rounds: int = 4):
    """Drive the SYNC track: call the judge, auto-answering any interrupt.

    ``respond(reason) -> str`` is the human: return ``"A"`` to approve, anything
    else to reject. Returns the final ``AgentResult`` (its ``structured_output`` is
    the approved Proposal, or None if the fix was rejected and the agent escalated).
    Bounded by ``max_rounds`` so a stubborn loop cannot spin forever.
    """
    state = invocation_state or {}
    result = judge(prompt, invocation_state=state)
    rounds = 0
    while getattr(result, "stop_reason", None) == "interrupt" and rounds < max_rounds:
        rounds += 1
        responses = []
        for intr in getattr(result, "interrupts", None) or []:
            responses.append({"interruptResponse": {
                "interruptId": intr.id, "response": respond(getattr(intr, "reason", None))}})
        result = judge(responses, invocation_state=state)
    return result


# --------------------------------------------------------------------------- #
# Track 2 - asynchronous decision-queue worker (spec §6 "durable decision-queue")
# --------------------------------------------------------------------------- #
Handler = Callable[[Decision], Any]


def null_handler(decision: Decision) -> None:  # noqa: ARG001
    """Default no-op handler: the seam where pe1 plugs in the Writer agent.

    pd2 delivers the durable queue + polling; the actual snapshot -> apply_fix ->
    verify_fix write path is Phase E. Until then a claimed decision is marked
    applied without touching any site (which is also the safe behaviour).
    """
    return None


class DecisionWorker:
    """Polls the durable queue for APPROVED decisions and dispatches them.

    At-least-once semantics: ``claim_next_approved`` does NOT change status, so a
    handler failure leaves the card approved and it is retried on the next poll; the
    worker marks a card ``applied`` only after the handler returns without raising.
    A failing card stops the current drain (to avoid a tight loop) and is retried on
    the next poll — pe1 adds a dead-letter/backoff for persistently-failing writes.
    """

    def __init__(self, store: DecisionStore, handler: Handler = null_handler,
                 audit_sink: Optional[Callable[[dict], None]] = None) -> None:
        self.store = store
        self.handler = handler
        self.audit_sink = audit_sink

    def _audit(self, event: str, decision: Decision, **extra: Any) -> None:
        if self.audit_sink is None:
            return
        rec = {"agent": "worker", "event": event, "decision_id": decision.id,
               "action": decision.proposal.action,
               "affected_slot_ids": decision.affected_slot_ids, **extra}
        try:
            self.audit_sink(rec)
        except Exception:
            pass  # auditing is best-effort; never break the worker

    def poll_once(self) -> int:
        """Drain all currently-approved decisions once. Returns count applied."""
        applied = 0
        while True:
            dec = self.store.claim_next_approved()
            if dec is None:
                break
            try:
                self.handler(dec)
            except Exception as e:  # noqa: BLE001 - leave approved, retry next poll
                self._audit("worker_error", dec, error=repr(e))
                break
            self.store.mark_applied(dec.id)
            self._audit("write", dec)
            applied += 1
        return applied

    def run(self, *, poll_interval: float = 5.0, max_iterations: Optional[int] = None,
            stop: Optional[Callable[[], bool]] = None) -> int:
        """Poll loop. ``max_iterations`` / ``stop`` bound it (tests, graceful stop).

        Returns the total number of decisions applied across all iterations.
        """
        total = 0
        iterations = 0
        while True:
            if stop is not None and stop():
                break
            total += self.poll_once()
            iterations += 1
            if max_iterations is not None and iterations >= max_iterations:
                break
            time.sleep(poll_interval)
        return total
