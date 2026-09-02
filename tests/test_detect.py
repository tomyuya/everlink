"""Offline unit tests for the detection layer (everlink.detect) — no network.

combine_verdict is the pure fold at the heart of the L1+L2 pyramid (spec §4.1);
these cases pin every branch, especially the soft-404 (L1 healthy -> L2 dead
offer) and the "L2 clears a blocked L1" second-opinion path.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from everlink.detect import claimed_price_from_text, combine_verdict  # noqa: E402


# --- combine_verdict: L1 conclusive wins ------------------------------------
def test_l1_dead_is_final_even_if_l2_ran():
    assert combine_verdict("dead", "ok") == "dead"


def test_l1_program_ended_is_final():
    assert combine_verdict("program_ended", "unavailable") == "program_ended"


def test_no_l2_passthrough_dead():
    assert combine_verdict("dead", None) == "dead"


def test_no_l2_passthrough_healthy():
    assert combine_verdict("healthy", None) == "healthy"


# --- combine_verdict: the soft-404 payoff -----------------------------------
def test_soft_404_l1_healthy_l2_unavailable_becomes_offer_changed():
    assert combine_verdict("healthy", "unavailable") == "offer_changed"


def test_price_anomaly_becomes_offer_changed():
    assert combine_verdict("healthy", "price_anomaly") == "offer_changed"


def test_l2_dead_overrides_healthy_l1():
    assert combine_verdict("healthy", "dead") == "dead"


# --- combine_verdict: L2 as a second opinion on a blocked L1 ----------------
def test_blocked_l1_stays_recheck_when_l2_also_blocked():
    assert combine_verdict("needs_human_recheck", "blocked") == "needs_human_recheck"


def test_l2_ok_clears_a_blocked_l1():
    # L1 hit a transient 403/timeout; L2 fetched fine -> genuinely healthy.
    assert combine_verdict("needs_human_recheck", "ok") == "healthy"


def test_l2_ok_confirms_healthy_l1():
    assert combine_verdict("healthy", "ok") == "healthy"


# --- claimed_price_from_text ------------------------------------------------
def test_claimed_price_usd():
    assert claimed_price_from_text("The Sony WH-1000XM5 costs $328.00 today.") == "$328.00"


def test_claimed_price_gbp():
    assert claimed_price_from_text("was £199.99 last year") == "£199.99"


def test_claimed_price_none_when_absent():
    assert claimed_price_from_text("no price mentioned here") is None


def test_claimed_price_none_input():
    assert claimed_price_from_text(None) is None


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
