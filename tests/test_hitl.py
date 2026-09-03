"""Sync-track tests (spec §6 "Interrupt"): EverLink's LIVE human-in-the-loop gate.

The async track (queue + worker) is covered by test_queue.py. This file covers the
synchronous track — ``make_sync_approval_gate`` pauses the agent via Strands'
native ``event.interrupt`` and ``run_judge_sync`` resumes it with the operator's
answer.

Two levels, mirroring test_steering.py:
  * UNIT — the pure predicates/helpers (``is_high_risk_proposal``,
    ``resume_responses``) fed synthetic events. No agent loop.
  * INTEGRATION — a real Strands ``Agent`` on the offline ``StubModel`` (no AWS,
    no network). Proves the gate genuinely pauses the loop, an "A" answer lets the
    high-risk fix through, and a rejection steers the model to ESCALATE_HUMAN so a
    declined fix is never emitted.

HONESTY: the StubModel scripts the Proposal; it does not exercise real LLM
judgment. What is proven here is the *interrupt plumbing* (pause / resume /
reject-to-escalate) and the write-safety invariant, offline. Real proposal quality
is verified on Bedrock (scripts/verify_bedrock.py + Strands Evals, spec §8).
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from strands.hooks import BeforeToolCallEvent  # noqa: E402

from everlink import agents, hitl  # noqa: E402
from everlink.hitl import make_sync_approval_gate, resume_responses, run_judge_sync  # noqa: E402
from everlink.llm import StubModel  # noqa: E402
from everlink.model import LinkSlot, Proposal  # noqa: E402
from everlink.steering import AuditCollector  # noqa: E402


class _FakeAgent:
    """Stand-in for a Strands Agent (hooks only read ``agent.name``)."""

    def __init__(self, name: str = "judge") -> None:
        self.name = name


def _slot(**kw) -> LinkSlot:
    base = dict(id="s1", site="t", article_id="a", article_title="T", block_id="b",
                block_type="paragraph", slot_type="commercial", url="https://x.com/p")
    base.update(kw)
    return LinkSlot(**base)


def _proposal_event(risk: str = "high", action: str = "REPLACE_URL",
                    slot: LinkSlot | None = None, **fields) -> BeforeToolCallEvent:
    """A synthetic BeforeToolCallEvent carrying the Judge's Proposal tool call."""
    state = {"slot": slot.model_dump()} if slot is not None else {}
    inp = {"action": action, "rationale": "r", "risk_level": risk, **fields}
    return BeforeToolCallEvent(
        agent=_FakeAgent(), selected_tool=None,
        tool_use={"toolUseId": "tu-1", "name": Proposal.__name__, "input": inp},
        invocation_state=state,
    )


# --------------------------------------------------------------------------- #
# UNIT — pure predicates / helpers
# --------------------------------------------------------------------------- #
def test_is_high_risk_proposal_true_on_high():
    assert hitl.is_high_risk_proposal(_proposal_event(risk="high")) is True


def test_is_high_risk_proposal_false_on_medium_and_low():
    assert hitl.is_high_risk_proposal(_proposal_event(risk="medium")) is False
    assert hitl.is_high_risk_proposal(_proposal_event(risk="low")) is False


def test_is_high_risk_proposal_inert_on_non_proposal_tool():
    ev = BeforeToolCallEvent(
        agent=_FakeAgent(), selected_tool=None,
        tool_use={"toolUseId": "tu-1", "name": "find_alternatives", "input": {"url": "https://a"}},
        invocation_state={},
    )
    assert hitl.is_high_risk_proposal(ev) is False


def test_interrupt_reason_carries_slot_and_proposal():
    slot = _slot(id="slot-9", site="aethelgem", url="https://x.com/dead")
    reason = hitl._interrupt_reason(
        _proposal_event(risk="high", action="REPLACE_URL", slot=slot,
                        new_url="https://amazon.com/dp/X"))
    assert reason["kind"] == "high_risk_fix"
    assert reason["slot_id"] == "slot-9" and reason["site"] == "aethelgem"
    assert reason["action"] == "REPLACE_URL" and reason["risk_level"] == "high"
    assert "how_to_respond" in reason               # the operator always sees guidance


def test_resume_responses_maps_every_interrupt():
    class _Intr:
        def __init__(self, id):
            self.id = id

    class _Res:
        interrupts = [_Intr("i1"), _Intr("i2")]

    out = resume_responses(_Res(), response="A")
    assert out == [
        {"interruptResponse": {"interruptId": "i1", "response": "A"}},
        {"interruptResponse": {"interruptId": "i2", "response": "A"}},
    ]


def test_resume_responses_empty_when_no_interrupts():
    class _Res:
        interrupts = []

    assert resume_responses(_Res()) == []
    assert resume_responses(object()) == []          # no .interrupts attr -> []


# --------------------------------------------------------------------------- #
# INTEGRATION — the gate pauses a real (offline) agent; approve / reject / inert
# --------------------------------------------------------------------------- #
_HIGH_RISK = {"action": "REPLACE_URL", "new_url": "https://amazon.com/dp/X",
              "rationale": "re-link to a live equivalent", "risk_level": "high"}


def test_sync_gate_pauses_then_approves():
    """A high-risk Proposal pauses the loop; answering 'A' lets it through."""
    col = AuditCollector()
    gate = make_sync_approval_gate(audit_sink=col)
    judge = agents.build_judge(StubModel(structured=dict(_HIGH_RISK)), hooks=[gate])

    seen_reasons: list = []

    def respond(reason):
        seen_reasons.append(reason)
        return "A"

    slot = _slot(id="s-approve", slot_type="commercial")
    result = run_judge_sync(judge, "propose a fix",
                            invocation_state={"slot": slot.model_dump()}, respond=respond)

    assert len(seen_reasons) == 1                   # the gate interrupted exactly once
    assert seen_reasons[0]["kind"] == "high_risk_fix"
    assert seen_reasons[0]["slot_id"] == "s-approve"
    assert getattr(result, "stop_reason", None) != "interrupt"
    assert result.structured_output.action == "REPLACE_URL"   # approved fix emitted
    assert "interrupt" in col.events()              # the pause was audited


def test_sync_gate_pauses_then_rejects_to_escalation():
    """A rejection ('R') steers the model to ESCALATE_HUMAN — the declined fix is
    never emitted. Uses a stateful stub that complies once it sees the Guide."""
    def stateful(messages):
        blob = json.dumps(messages, default=str).lower()
        if "cancelled by everlink steering" in blob:      # saw the rejection guidance
            return {"action": "ESCALATE_HUMAN", "rationale": "operator declined",
                    "risk_level": "medium"}
        return dict(_HIGH_RISK)

    gate = make_sync_approval_gate()
    judge = agents.build_judge(StubModel(structured=stateful), hooks=[gate])

    slot = _slot(id="s-reject", slot_type="commercial")
    result = run_judge_sync(judge, "propose a fix",
                            invocation_state={"slot": slot.model_dump()},
                            respond=lambda _reason: "R")

    assert getattr(result, "stop_reason", None) != "interrupt"
    assert result.structured_output.action == "ESCALATE_HUMAN"   # NOT the declined REPLACE_URL


def test_sync_gate_inert_on_low_risk():
    """A low-risk Proposal is never paused — the whole point of 'surfaces only when
    a real decision is needed'."""
    gate = make_sync_approval_gate()
    judge = agents.build_judge(
        StubModel(structured={"action": "REWRITE_ANCHOR", "new_anchor": "the vendor page",
                              "rationale": "cosmetic", "risk_level": "low"}),
        hooks=[gate])

    calls = {"n": 0}

    def respond(_reason):
        calls["n"] += 1
        return "A"

    result = run_judge_sync(judge, "propose a fix",
                            invocation_state={"slot": _slot().model_dump()}, respond=respond)
    assert calls["n"] == 0                          # never interrupted
    assert result.structured_output.action == "REWRITE_ANCHOR"


def test_sync_gate_reject_is_bounded_by_max_rounds():
    """A stubborn high-risk stub with a rejecting operator must not spin forever —
    run_judge_sync stops at max_rounds and returns the still-interrupted result."""
    gate = make_sync_approval_gate()
    judge = agents.build_judge(StubModel(structured=dict(_HIGH_RISK)), hooks=[gate])

    calls = {"n": 0}

    def respond(_reason):
        calls["n"] += 1
        return "R"                                  # always reject; stub never complies

    result = run_judge_sync(judge, "propose a fix",
                            invocation_state={"slot": _slot().model_dump()},
                            respond=respond, max_rounds=3)
    assert 1 <= calls["n"] <= 3                     # bounded, never infinite
    assert getattr(result, "stop_reason", None) == "interrupt"


ALL = [v for k, v in sorted(globals().items()) if k.startswith("test_")]


if __name__ == "__main__":
    failed = 0
    for fn in ALL:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"FAIL {fn.__name__}: {type(e).__name__}: {e}")
    print(f"\n{len(ALL)-failed}/{len(ALL)} passed")
    sys.exit(1 if failed else 0)
