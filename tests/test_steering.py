"""Steering hook tests (spec §4.3 / §6): the runtime enforcement layer.

Two levels, mirroring how the hooks are used:
  * UNIT — synthetic BeforeToolCallEvent / AfterToolCallEvent fed straight to each
    hook callback; assert ``cancel_tool`` (Guide) / audit records. Deterministic,
    no agent loop, no network.
  * INTEGRATION — a real Strands ``Agent`` (offline StubModel) built with
    ``enforce=True``; assert a violating Judge proposal is steered to a compliant
    one. This proves the Guide actually re-drives the model offline.

Honesty: enforcement (these hooks) and scoring (Evals oracle) are separate
consumers of the SAME ``everlink.policy`` functions, so a rule proven here is the
rule scored in test_evals.py.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from strands.hooks import AfterToolCallEvent, BeforeToolCallEvent  # noqa: E402

from everlink import agents, steering  # noqa: E402
from everlink.llm import StubModel  # noqa: E402
from everlink.model import CheckResult, LinkSlot, Proposal  # noqa: E402


class _FakeAgent:
    """Stand-in for a Strands Agent (hooks only read ``agent.name``)."""

    def __init__(self, name: str = "judge") -> None:
        self.name = name


def _slot(**kw) -> LinkSlot:
    base = dict(id="s1", site="t", article_id="a", article_title="T", block_id="b",
                block_type="paragraph", slot_type="commercial", url="https://x.com/p")
    base.update(kw)
    return LinkSlot(**base)


def _before(tool_name: str, tool_input: dict, slot: LinkSlot | None = None,
            claimed_price: str | None = None, verdict: str | None = None) -> BeforeToolCallEvent:
    state: dict = {}
    if slot is not None:
        state["slot"] = slot.model_dump()
    if claimed_price is not None:
        state["claimed_price"] = claimed_price
    if verdict is not None:
        state["verdict"] = verdict
    return BeforeToolCallEvent(
        agent=_FakeAgent(), selected_tool=None,
        tool_use={"toolUseId": "tu-1", "name": tool_name, "input": tool_input},
        invocation_state=state,
    )


def _proposal_call(action: str, **fields) -> tuple[str, dict]:
    """(tool_name, tool_input) for the Judge's Proposal structured-output call."""
    inp = {"action": action, "rationale": "r", "risk_level": "medium", **fields}
    return Proposal.__name__, inp


def _after(tool_name: str, tool_input: dict, cancel_message: str | None = None,
           agent_name: str = "judge") -> AfterToolCallEvent:
    return AfterToolCallEvent(
        agent=_FakeAgent(agent_name), selected_tool=None,
        tool_use={"toolUseId": "tu-1", "name": tool_name, "input": tool_input},
        invocation_state={},
        result={"status": "error" if cancel_message else "success", "content": []},
        cancel_message=cancel_message, duration=0.01,
    )


# --------------------------------------------------------------------------- #
# disclosure_policy (spec §4.3-1)
# --------------------------------------------------------------------------- #
def test_disclosure_cancels_modifying_protected_slot():
    name, inp = _proposal_call("REPLACE_URL", new_url="https://a.com/x")
    ev = _before(name, inp, slot=_slot(protected=1))
    steering.disclosure_policy(ev)
    assert ev.cancel_tool and "disclosure_policy" in ev.cancel_tool


def test_disclosure_cancels_drop_of_disclosure_block():
    name, inp = _proposal_call("DROP_BLOCK")
    ev = _before(name, inp, slot=_slot(block_type="affiliate_disclosure"))
    steering.disclosure_policy(ev)
    assert ev.cancel_tool


def test_disclosure_allows_escalate_human_on_protected():
    name, inp = _proposal_call("ESCALATE_HUMAN")
    ev = _before(name, inp, slot=_slot(protected=1))
    steering.disclosure_policy(ev)
    assert ev.cancel_tool is False


def test_disclosure_inert_on_non_proposal_tool():
    ev = _before("find_alternatives", {"url": "https://a.com"}, slot=_slot(protected=1))
    steering.disclosure_policy(ev)
    assert ev.cancel_tool is False


def test_disclosure_inert_without_slot_context():
    name, inp = _proposal_call("REPLACE_URL", new_url="https://a.com/x")
    ev = _before(name, inp, slot=None)
    steering.disclosure_policy(ev)
    assert ev.cancel_tool is False


# --------------------------------------------------------------------------- #
# scope_policy (spec §4.3-3)
# --------------------------------------------------------------------------- #
def test_scope_cancels_reference_replace_url():
    name, inp = _proposal_call("REPLACE_URL", new_url="https://amazon.com/dp/X")
    ev = _before(name, inp, slot=_slot(slot_type="reference"))
    steering.scope_policy(ev)
    assert ev.cancel_tool and "scope_policy" in ev.cancel_tool


def test_scope_allows_reference_sentence_rewrite():
    name, inp = _proposal_call("REWRITE_SENTENCE", new_sentence="See the archived source.")
    ev = _before(name, inp, slot=_slot(slot_type="reference"))
    steering.scope_policy(ev)
    assert ev.cancel_tool is False


def test_scope_allows_commercial_replace_url():
    name, inp = _proposal_call("REPLACE_URL", new_url="https://amazon.com/dp/X")
    ev = _before(name, inp, slot=_slot(slot_type="commercial"))
    steering.scope_policy(ev)
    assert ev.cancel_tool is False


# --------------------------------------------------------------------------- #
# editorial_policy (spec §4.3-2)
# --------------------------------------------------------------------------- #
def test_editorial_cancels_rewrite_sentence_without_content():
    name, inp = _proposal_call("REWRITE_SENTENCE")          # no new_sentence
    ev = _before(name, inp, slot=_slot())
    steering.editorial_policy(ev)
    assert ev.cancel_tool and "editorial_policy" in ev.cancel_tool


def test_editorial_cancels_replace_url_without_url():
    name, inp = _proposal_call("REPLACE_URL")               # no new_url
    ev = _before(name, inp, slot=_slot())
    steering.editorial_policy(ev)
    assert ev.cancel_tool


def test_editorial_cancels_rewrite_anchor_without_anchor():
    name, inp = _proposal_call("REWRITE_ANCHOR")            # no new_anchor
    ev = _before(name, inp, slot=_slot())
    steering.editorial_policy(ev)
    assert ev.cancel_tool


def test_editorial_allows_complete_rewrite():
    name, inp = _proposal_call("REWRITE_SENTENCE", new_sentence="The model is discontinued.")
    ev = _before(name, inp, slot=_slot())
    steering.editorial_policy(ev)
    assert ev.cancel_tool is False


def test_editorial_cancels_stale_price_surviving_rewrite():
    name, inp = _proposal_call("REWRITE_SENTENCE", new_sentence="Still just $328.00 today!")
    ev = _before(name, inp, slot=_slot(), claimed_price="$328.00")
    steering.editorial_policy(ev)
    assert ev.cancel_tool and "stale price" in ev.cancel_tool


def test_editorial_allows_rewrite_that_drops_stale_price():
    name, inp = _proposal_call("REWRITE_SENTENCE", new_sentence="The price is no longer listed.")
    ev = _before(name, inp, slot=_slot(), claimed_price="$328.00")
    steering.editorial_policy(ev)
    assert ev.cancel_tool is False


# --------------------------------------------------------------------------- #
# recheck_policy — false-positive guard (inconclusive verdict => ESCALATE only)
# --------------------------------------------------------------------------- #
def test_recheck_cancels_rewrite_on_inconclusive_verdict():
    # The probe was blocked/uncertain, so user accessibility is UNKNOWN. Rewriting
    # content on top of a probe limitation is the false positive this kills.
    name, inp = _proposal_call("REWRITE_SENTENCE", new_sentence="Link is unreachable.")
    ev = _before(name, inp, slot=_slot(), verdict="needs_human_recheck")
    steering.recheck_policy(ev)
    assert ev.cancel_tool and "recheck_policy" in ev.cancel_tool


def test_recheck_cancels_replace_url_on_inconclusive_verdict():
    name, inp = _proposal_call("REPLACE_URL", new_url="https://a.com/alt")
    ev = _before(name, inp, slot=_slot(), verdict="needs_human_recheck")
    steering.recheck_policy(ev)
    assert ev.cancel_tool


def test_recheck_allows_escalate_human_on_inconclusive_verdict():
    name, inp = _proposal_call("ESCALATE_HUMAN")
    ev = _before(name, inp, slot=_slot(), verdict="needs_human_recheck")
    steering.recheck_policy(ev)
    assert ev.cancel_tool is False


def test_recheck_inert_on_conclusive_verdict():
    # A proven-dead link may still be rewritten/replaced; the guard only fires
    # on an inconclusive probe.
    name, inp = _proposal_call("REPLACE_URL", new_url="https://a.com/alt")
    ev = _before(name, inp, slot=_slot(), verdict="dead")
    steering.recheck_policy(ev)
    assert ev.cancel_tool is False


def test_recheck_inert_without_verdict_context():
    name, inp = _proposal_call("REWRITE_SENTENCE", new_sentence="x")
    ev = _before(name, inp, slot=_slot())          # no verdict threaded
    steering.recheck_policy(ev)
    assert ev.cancel_tool is False



# --------------------------------------------------------------------------- #
# write_gate (spec §4.3-4)
# --------------------------------------------------------------------------- #
def test_write_gate_cancels_apply_fix_without_decision_id():
    gate = steering.make_write_gate(is_approved=lambda _id: True)
    ev = _before("apply_fix", {"slot_id": "s1"})            # no decision_id
    gate(ev)
    assert ev.cancel_tool and "write_gate" in ev.cancel_tool


def test_write_gate_cancels_unapproved_decision():
    gate = steering.make_write_gate(is_approved=lambda _id: False)
    ev = _before("apply_fix", {"slot_id": "s1", "decision_id": "dec-1"})
    gate(ev)
    assert ev.cancel_tool and "not approved" in ev.cancel_tool


def test_write_gate_allows_approved_decision():
    gate = steering.make_write_gate(is_approved=lambda d: d == "dec-1")
    ev = _before("apply_fix", {"slot_id": "s1", "decision_id": "dec-1"})
    gate(ev)
    assert ev.cancel_tool is False


def test_write_gate_guards_rollback_too():
    gate = steering.make_write_gate(is_approved=lambda _id: False)
    ev = _before("rollback", {"decision_id": "dec-9"})
    gate(ev)
    assert ev.cancel_tool


def test_write_gate_ignores_read_tools():
    gate = steering.make_write_gate(is_approved=lambda _id: False)
    ev = _before("verify_fix", {"url": "https://a.com"})    # not a write tool
    gate(ev)
    assert ev.cancel_tool is False


# --------------------------------------------------------------------------- #
# audit (spec §5 audit_log)
# --------------------------------------------------------------------------- #
def test_audit_records_tool_result():
    col = steering.AuditCollector()
    audit = steering.make_audit(col, agent_name="scanner")
    audit(_after("http_probe", {"url": "https://a.com"}))
    assert len(col.records) == 1
    rec = col.records[0]
    assert rec["agent"] == "scanner" and rec["event"] == "tool_result"
    assert rec["tool"] == "http_probe" and rec["status"] == "success"


def test_audit_records_steering_cancel():
    col = steering.AuditCollector()
    audit = steering.make_audit(col, agent_name="judge")
    audit(_after(Proposal.__name__, {"action": "REPLACE_URL"},
                 cancel_message="Tool call cancelled by EverLink steering"))
    rec = col.records[0]
    assert rec["event"] == "steering_cancel"
    assert rec["cancel_message"].startswith("Tool call cancelled")


def test_audit_never_raises_on_sink_error():
    def bad_sink(_record):
        raise RuntimeError("db down")
    audit = steering.make_audit(bad_sink, agent_name="judge")
    audit(_after("http_probe", {"url": "https://a.com"}))   # must not propagate


# --------------------------------------------------------------------------- #
# spec §6 assembly
# --------------------------------------------------------------------------- #
def test_judge_hooks_assembly_matches_spec():
    hooks = steering.judge_hooks()
    assert steering.scope_policy in hooks and steering.editorial_policy in hooks
    assert steering.recheck_policy in hooks                  # false-positive guard
    assert len(hooks) == 4                          # scope, editorial, recheck, audit


def test_scanner_hooks_assembly_matches_spec():
    assert len(steering.scanner_hooks()) == 1               # audit only


def test_writer_hooks_assembly_matches_spec():
    hooks = steering.writer_hooks(is_approved=lambda _id: True)
    assert steering.disclosure_policy in hooks and len(hooks) == 3


# --------------------------------------------------------------------------- #
# INTEGRATION — enforcement steers a real (offline) agent
# --------------------------------------------------------------------------- #
def test_enforced_judge_passes_a_clean_proposal_through():
    col = steering.AuditCollector()
    judge = agents.build_judge(
        StubModel(structured={"action": "ESCALATE_HUMAN", "rationale": "safe",
                              "risk_level": "high"}),
        audit_sink=col, enforce=True)
    slot = _slot(id="ref-1", slot_type="reference", url="https://x.com/ref")
    check = CheckResult(slot_id=slot.id, final_verdict="dead")
    proposal = agents.judge_slot(judge, slot, check)
    assert proposal.action == "ESCALATE_HUMAN"              # compliant, not cancelled
    assert col.records and all(r["event"] != "steering_cancel" for r in col.records)


def test_enforcement_steers_a_violating_judge_to_comply():
    """A stub that first REPLACE_URLs a reference slot must be steered (Guide) into
    ESCALATE_HUMAN. Proves the hook re-drives the model offline, not just blocks."""
    calls = {"n": 0}

    def steerable(messages):
        calls["n"] += 1
        blob = json.dumps(messages, default=str).lower()
        if "cancelled by everlink steering" in blob:        # saw the guidance -> comply
            return {"action": "ESCALATE_HUMAN", "rationale": "steered", "risk_level": "high"}
        return {"action": "REPLACE_URL", "new_url": "https://amazon.com/dp/FAKE",
                "rationale": "blind", "risk_level": "medium"}

    col = steering.AuditCollector()
    judge = agents.build_judge(StubModel(structured=steerable), audit_sink=col, enforce=True)
    slot = _slot(id="ref-2", slot_type="reference", url="https://x.com/ref")
    check = CheckResult(slot_id=slot.id, final_verdict="dead")
    proposal = agents.judge_slot(judge, slot, check)

    assert proposal.action == "ESCALATE_HUMAN"              # final proposal is compliant
    assert calls["n"] >= 2                                  # the model had to re-decide
    assert "steering_cancel" in col.events()                # the block was audited


def test_botwall_false_positive_is_steered_to_escalate():
    """End-to-end regression for the reported incident: an Amazon probe hit a
    bot-wall (final_verdict=needs_human_recheck), and the Judge tried to
    REWRITE_SENTENCE claiming the link is 'inaccessible to users'. Real users
    open it fine — recheck_policy must steer that to ESCALATE_HUMAN."""
    calls = {"n": 0}

    def botwall_judge(messages):
        calls["n"] += 1
        blob = json.dumps(messages, default=str).lower()
        if "cancelled by everlink steering" in blob:        # saw the guidance -> comply
            return {"action": "ESCALATE_HUMAN",
                    "rationale": "automated probe was inconclusive; human click-through required",
                    "risk_level": "high"}
        return {"action": "REWRITE_SENTENCE",
                "new_sentence": "The link is blocked by Amazon's bot-wall, inaccessible to users.",
                "rationale": "bot-wall", "risk_level": "high"}

    col = steering.AuditCollector()
    judge = agents.build_judge(StubModel(structured=botwall_judge), audit_sink=col, enforce=True)
    slot = _slot(id="amz-1", slot_type="commercial", url="https://www.amazon.com/dp/B0F21KVBHN")
    check = CheckResult(slot_id=slot.id, final_verdict="needs_human_recheck",
                        l2_verdict="blocked", l2_evidence="bot-wall / captcha signal")
    proposal = agents.judge_slot(judge, slot, check)

    assert proposal.action == "ESCALATE_HUMAN"              # never a blind rewrite
    assert "inaccessible to users" not in (proposal.new_sentence or "").lower()
    assert calls["n"] >= 2                                  # the model had to re-decide
    assert "steering_cancel" in col.events()                # the block was audited


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
