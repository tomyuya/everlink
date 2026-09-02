"""Evals tests (spec §8): policy oracle + card merge (pure) and the full 30-case
run_evals pipeline against the fixture server.

The honesty-critical test is ``test_oracle_catches_a_violating_judge``: it injects
a Judge that blindly REPLACE_URLs everything and asserts the oracle FLAGS it, so
the steering / hard-metric evaluators are proven non-vacuous (they do not merely
pass because the stub always escalates).
"""
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from everlink import agents, policy  # noqa: E402
from everlink.agents import SlotProposal  # noqa: E402
from everlink.cards import build_decision_cards, merge_key  # noqa: E402
from everlink.evals import build_cases, run_evals  # noqa: E402
from everlink.fixtures import make_server  # noqa: E402
from everlink.llm import StubModel  # noqa: E402
from everlink.model import CheckResult, LinkSlot, Proposal  # noqa: E402

_server = None
_thread = None
_base = None


def setup_module(module):  # noqa: ARG001
    global _server, _thread, _base
    _server = make_server(port=0)
    host, port = _server.server_address
    _base = f"http://{host}:{port}"
    _thread = threading.Thread(target=_server.serve_forever, daemon=True)
    _thread.start()


def teardown_module(module):  # noqa: ARG001
    if _server is not None:
        _server.shutdown()
        _server.server_close()
    if _thread is not None:
        _thread.join(timeout=5)


def _slot(**kw):
    base = dict(id="s", site="t", article_id="a", article_title="T", block_id="b",
                block_type="paragraph", slot_type="commercial", url="https://x.com/p")
    base.update(kw)
    return LinkSlot(**base)


def _prop(action, **kw):
    base = dict(action=action, rationale="r", risk_level="medium")
    base.update(kw)
    return Proposal(**base)


def _sp(slot, action="ESCALATE_HUMAN", risk="high"):
    check = CheckResult(slot_id=slot.id, final_verdict="dead")
    return SlotProposal(slot=slot, check=check,
                        proposal=Proposal(action=action, rationale="r", risk_level=risk))


# --- policy oracle: three-layer disclosure protection -----------------------
def test_is_protected_by_marker():
    assert policy.is_protected(_slot(protected=1))


def test_is_protected_by_block_type():
    assert policy.is_protected(_slot(block_type="affiliate_disclosure"))


def test_is_protected_by_keyword():
    assert policy.is_protected(_slot(anchor_text="our sponsored partner link"))


def test_clean_commercial_slot_not_protected():
    assert not policy.is_protected(_slot(anchor_text="Sony WH-1000XM5"))


def test_disclosure_violation_flags_modifying_a_protected_slot():
    assert policy.disclosure_violation(_slot(protected=1), _prop("REPLACE_URL")) is not None


def test_disclosure_allows_escalate_human():
    assert policy.disclosure_violation(_slot(protected=1), _prop("ESCALATE_HUMAN")) is None


def test_unprotected_slot_may_be_dropped():
    assert policy.disclosure_violation(_slot(), _prop("DROP_BLOCK")) is None


def test_scope_violation_flags_reference_replace_url():
    assert policy.scope_violation(_slot(slot_type="reference"), _prop("REPLACE_URL")) is not None


def test_scope_allows_reference_sentence_rewrite():
    assert policy.scope_violation(_slot(slot_type="reference"), _prop("REWRITE_SENTENCE")) is None


def test_scope_allows_commercial_replace_url():
    assert policy.scope_violation(_slot(slot_type="commercial"), _prop("REPLACE_URL")) is None


def test_proposal_violations_aggregates():
    # a protected reference slot that gets REPLACE_URL violates BOTH rules
    v = policy.proposal_violations(_slot(protected=1, slot_type="reference"), _prop("REPLACE_URL"))
    assert len(v) == 2


# --- card merge (hard metric 3) ---------------------------------------------
def test_merge_key_ignores_tracking_query_and_fragment():
    assert merge_key("https://a.com/dp/X?tag=20#top") == merge_key("https://a.com/dp/X?tag=99")


def test_merge_key_differs_by_path():
    assert merge_key("https://a.com/dp/X") != merge_key("https://a.com/dp/Y")


def test_duplicate_slots_merge_into_one_card():
    a = _sp(_slot(id="dup-a", url="https://a.com/dp/X", article_id="art-A"))
    b = _sp(_slot(id="dup-b", url="https://a.com/dp/X", article_id="art-B"))
    cards = build_decision_cards([a, b])
    assert len(cards) == 1
    assert set(cards[0].affected_slot_ids) == {"dup-a", "dup-b"}


def test_distinct_urls_make_distinct_cards():
    cards = build_decision_cards([
        _sp(_slot(id="s1", url="https://a.com/dp/X")),
        _sp(_slot(id="s2", url="https://a.com/dp/Y")),
        _sp(_slot(id="s3", url="https://a.com/dp/Z")),
    ])
    assert len(cards) == 3


def test_merged_card_takes_the_highest_risk_proposal():
    lo = _sp(_slot(id="a", url="https://a.com/dp/X"), action="REWRITE_ANCHOR", risk="low")
    hi = _sp(_slot(id="b", url="https://a.com/dp/X"), action="ESCALATE_HUMAN", risk="high")
    card = build_decision_cards([lo, hi])[0]
    assert card.proposal.risk_level == "high"


# --- full pipeline against the fixture server -------------------------------
def test_evals_v1_passes_on_stub():
    report = run_evals(_base, judge_backend="stub", timeout=10.0)
    assert report.total_cases == 30
    assert report.detection_correct == 30 and report.detection_accuracy == 1.0
    assert report.steering_violations == 0
    assert report.disclosure_zero_deletion == 1.0
    assert report.reference_zero_replace == 1.0
    assert report.duplicate_merge_ok
    assert report.cards_built > 0
    assert report.passed


def test_oracle_catches_a_violating_judge():
    """A Judge that blindly REPLACE_URLs everything MUST be flagged — proves the
    steering / hard-metric evaluators are real, not vacuous."""
    violating = agents.build_judge(StubModel(structured={
        "action": "REPLACE_URL", "new_url": "https://www.amazon.com/dp/FAKE",
        "rationale": "blind replace", "risk_level": "medium"}))
    cases = [c for c in build_cases() if c.category in ("disclosure", "reference")]
    report = run_evals(_base, judge=violating, judge_backend="stub", cases=cases, timeout=10.0)
    assert report.steering_violations > 0
    assert report.disclosure_zero_deletion < 1.0     # protected slot got REPLACE_URL
    assert report.reference_zero_replace < 1.0       # reference slot got REPLACE_URL
    assert not report.passed


ALL = [v for k, v in sorted(globals().items()) if k.startswith("test_")]


if __name__ == "__main__":
    setup_module(None)
    failed = 0
    try:
        for fn in ALL:
            try:
                fn()
                print(f"PASS {fn.__name__}")
            except Exception as e:  # noqa: BLE001
                failed += 1
                print(f"FAIL {fn.__name__}: {type(e).__name__}: {e}")
    finally:
        teardown_module(None)
    print(f"\n{len(ALL)-failed}/{len(ALL)} passed")
    sys.exit(1 if failed else 0)
