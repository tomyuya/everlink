"""Offline tests for ``python -m everlink`` command glue (everlink.cli).

The CLI orchestrates already-tested primitives (``detect.check_slot``, the queue
stores, ``db.insert_audit``). These tests exercise the COMMAND-LEVEL decision
logic — chiefly ``recheck``'s false-positive retirement — against an in-memory
store with monkeypatched I/O, so no DB, network or AWS credential is needed
(CI-safe, matching the offline style of test_queue.py / test_steering.py).
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from everlink import cli, db, detect  # noqa: E402
from everlink.model import CheckResult, Decision, LinkSlot, Proposal  # noqa: E402
from everlink.queue import InMemoryDecisionStore  # noqa: E402


class _FakeConn:
    """Stand-in for a psycopg conn: cmd_* only ever calls ``.close()`` on it."""

    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


def _card(cid: str = "dec-1", slots: tuple[str, ...] = ("s1",)) -> Decision:
    return Decision(id=cid, affected_slot_ids=list(slots),
                    proposal=Proposal(action="REWRITE_SENTENCE", rationale="r",
                                      risk_level="high"))


def _slot(sid: str = "s1", url: str = "https://www.amazon.com/dp/B0F21KVBHN") -> LinkSlot:
    return LinkSlot(id=sid, site="hotdeals", article_id="a", article_title="T",
                    block_id="b", block_type="paragraph", slot_type="component", url=url)


def _args(**kw) -> argparse.Namespace:
    base = dict(id=None, limit=100, rate_delay=0, timeout=15.0, no_l2=False, apply=False)
    base.update(kw)
    return argparse.Namespace(**base)


def _wire(monkeypatch, store, verdict: str = "healthy"):
    """Point the CLI's DB touchpoints at the in-memory store + a stub probe."""
    conn = _FakeConn()
    monkeypatch.setattr(cli, "_open_db_store", lambda: (conn, store))
    monkeypatch.setattr(db, "fetch_slot", lambda c, sid: _slot(sid))
    monkeypatch.setattr(
        detect, "check_slot",
        lambda slot, **kw: CheckResult(slot_id=slot.id, final_verdict=verdict))
    audits: list = []
    monkeypatch.setattr(
        db, "insert_audit",
        lambda c, agent, event, payload=None: audits.append((agent, event, payload)))
    return conn, audits


# --------------------------------------------------------------------------- #
# recheck — false-positive retirement (the dec-43dcbc9770 remediation path)
# --------------------------------------------------------------------------- #
def test_recheck_dry_run_flags_but_writes_nothing(monkeypatch):
    store = InMemoryDecisionStore()
    store.enqueue([_card()])
    _wire(monkeypatch, store, verdict="healthy")
    assert cli.cmd_recheck(_args(apply=False)) == 0
    assert store.get("dec-1").status == "pending"      # dry-run retired nothing


def test_recheck_apply_retires_a_false_positive(monkeypatch):
    store = InMemoryDecisionStore()
    store.enqueue([_card()])
    _conn, audits = _wire(monkeypatch, store, verdict="healthy")
    assert cli.cmd_recheck(_args(apply=True)) == 0
    card = store.get("dec-1")
    assert card.status == "rejected"                   # proven false positive retired
    assert "false positive" in (card.reject_reason or "").lower()
    assert any(e == "false_positive_retired" for _a, e, _p in audits)


def test_recheck_apply_leaves_a_real_problem_alone(monkeypatch):
    # A slot that STILL probes unhealthy is a real problem, never a false positive.
    store = InMemoryDecisionStore()
    store.enqueue([_card()])
    _conn, audits = _wire(monkeypatch, store, verdict="dead")
    assert cli.cmd_recheck(_args(apply=True)) == 0
    assert store.get("dec-1").status == "pending"       # untouched
    assert audits == []                                 # nothing retired, nothing audited


def test_recheck_needs_every_slot_healthy(monkeypatch):
    # One healthy + one still-dead slot => the card is NOT a false positive.
    store = InMemoryDecisionStore()
    store.enqueue([_card("dec-1", slots=("s1", "s2"))])
    conn = _FakeConn()
    monkeypatch.setattr(cli, "_open_db_store", lambda: (conn, store))
    monkeypatch.setattr(db, "fetch_slot", lambda c, sid: _slot(sid))
    monkeypatch.setattr(
        detect, "check_slot",
        lambda slot, **kw: CheckResult(
            slot_id=slot.id, final_verdict="healthy" if slot.id == "s1" else "dead"))
    monkeypatch.setattr(db, "insert_audit", lambda *a, **k: None)
    assert cli.cmd_recheck(_args(apply=True)) == 0
    assert store.get("dec-1").status == "pending"


def test_recheck_targets_one_card_by_id(monkeypatch):
    store = InMemoryDecisionStore()
    store.enqueue([_card("dec-1"), _card("dec-2", slots=("s2",))])
    _wire(monkeypatch, store, verdict="healthy")
    assert cli.cmd_recheck(_args(id="dec-2", apply=True)) == 0
    assert store.get("dec-2").status == "rejected"      # the targeted card retired
    assert store.get("dec-1").status == "pending"       # the other card untouched


def test_recheck_missing_id_is_honest(monkeypatch):
    store = InMemoryDecisionStore()
    _wire(monkeypatch, store, verdict="healthy")
    assert cli.cmd_recheck(_args(id="dec-nope")) == 1


def test_recheck_non_pending_id_is_honest(monkeypatch):
    # An already-approved card must never be re-rejected by an automated recheck.
    store = InMemoryDecisionStore()
    store.enqueue([_card()])
    store.approve("dec-1")
    _wire(monkeypatch, store, verdict="healthy")
    assert cli.cmd_recheck(_args(id="dec-1")) == 1
    assert store.get("dec-1").status == "approved"


def test_recheck_closes_the_connection(monkeypatch):
    store = InMemoryDecisionStore()
    store.enqueue([_card()])
    conn, _audits = _wire(monkeypatch, store, verdict="healthy")
    cli.cmd_recheck(_args(apply=True))
    assert conn.closed is True                          # no leaked DB connection


# --------------------------------------------------------------------------- #
# parser wiring
# --------------------------------------------------------------------------- #
def test_recheck_subcommand_is_registered():
    ap = cli.build_parser()
    args = ap.parse_args(["recheck", "dec-9", "--apply", "--no-l2"])
    assert args.command == "recheck" and args.id == "dec-9"
    assert args.apply is True and args.no_l2 is True
    assert args.func is cli.cmd_recheck


ALL = [v for k, v in sorted(globals().items()) if k.startswith("test_")]


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))
