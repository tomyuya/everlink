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
    base = dict(id=None, limit=100, rate_delay=0, timeout=15.0, no_l2=False,
                confirm=1, apply=False)
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
# recheck --confirm — the stability gate (bot-mitigated hosts flip verdicts)
# --------------------------------------------------------------------------- #
def test_recheck_confirm_gate_leaves_an_unstable_card(monkeypatch):
    # Healthy on the first probe but flips unhealthy on confirmation => NOT retired.
    # That flip is exactly the Amazon bot-mitigation non-determinism the gate exists
    # to catch; retiring on the lucky first probe would suppress a real (if flaky)
    # signal, which is itself a trust violation.
    store = InMemoryDecisionStore()
    store.enqueue([_card()])
    conn = _FakeConn()
    monkeypatch.setattr(cli, "_open_db_store", lambda: (conn, store))
    monkeypatch.setattr(db, "fetch_slot", lambda c, sid: _slot(sid))
    calls = {"n": 0}

    def _flaky(slot, **kw):
        calls["n"] += 1
        verdict = "healthy" if calls["n"] == 1 else "offer_changed"   # healthy, then flips
        return CheckResult(slot_id=slot.id, final_verdict=verdict)

    monkeypatch.setattr(detect, "check_slot", _flaky)
    audits: list = []
    monkeypatch.setattr(db, "insert_audit",
                        lambda c, a, e, p=None: audits.append((a, e, p)))
    assert cli.cmd_recheck(_args(apply=True, confirm=3)) == 0
    assert store.get("dec-1").status == "pending"       # unstable -> left for a human
    assert audits == []                                 # nothing retired, nothing audited


def test_recheck_confirm_gate_retires_a_stable_card(monkeypatch):
    # Stays healthy across all N confirmations => a proven false positive, retired.
    store = InMemoryDecisionStore()
    store.enqueue([_card()])
    _conn, audits = _wire(monkeypatch, store, verdict="healthy")
    assert cli.cmd_recheck(_args(apply=True, confirm=3)) == 0
    card = store.get("dec-1")
    assert card.status == "rejected"
    assert "consecutive re-probes" in (card.reject_reason or "")   # honest proof string
    assert any(e == "false_positive_retired" for _a, e, _p in audits)


# --------------------------------------------------------------------------- #
# parser wiring
# --------------------------------------------------------------------------- #
def test_recheck_subcommand_is_registered():
    ap = cli.build_parser()
    args = ap.parse_args(["recheck", "dec-9", "--apply", "--no-l2"])
    assert args.command == "recheck" and args.id == "dec-9"
    assert args.apply is True and args.no_l2 is True
    assert args.func is cli.cmd_recheck


def test_recheck_confirm_flag_is_registered():
    ap = cli.build_parser()
    args = ap.parse_args(["recheck", "--confirm", "3", "--apply"])
    assert args.confirm == 3 and args.apply is True
    # default is a single probe (back-compatible)
    assert ap.parse_args(["recheck"]).confirm == 1


# scan 的退出码合同与副作用边界；不实际连接 DB、模型或扫描源站。
from types import SimpleNamespace
from unittest.mock import Mock

import psycopg
import pytest


@pytest.fixture
def scan_io(monkeypatch):
    from everlink import agents

    def forbidden(*args, **kwargs):
        pytest.fail("scan 回归禁止未注入的 I/O")

    monkeypatch.delenv("EVERLINK_DATABASE_URL", raising=False)
    monkeypatch.setattr(db, "connect", forbidden)
    monkeypatch.setattr(psycopg, "connect", forbidden)
    monkeypatch.setattr(cli, "get_mantle_model", Mock(return_value=object()))
    monkeypatch.setattr(cli, "get_model", Mock(return_value=object()))
    monkeypatch.setattr(agents, "build_judge", Mock(return_value=object()))
    monkeypatch.setattr(agents, "build_stub_judge", Mock(return_value=object()))
    slots = [_slot("s1", "https://example.invalid/1"), _slot("s2", "https://example.invalid/2")]
    checks = [CheckResult(slot_id=s.id, final_verdict="dead") for s in slots]
    report = agents.ScanReport(source="synthetic", scanned=2, slots=slots, checks=checks,
                               judge_backend="mantle")
    scan = Mock(return_value=report)
    monkeypatch.setattr(agents, "run_scan", scan)
    real_persist = cli._persist
    persist = Mock(return_value=(2, 0))
    monkeypatch.setattr(cli, "_persist", persist)
    return SimpleNamespace(report=report, scan=scan, persist=persist, real_persist=real_persist)


def _scan_args(*argv):
    return cli.build_parser().parse_args([
        "scan", "--site", "hotdeals", "--judge", "mantle", "--rate-delay", "0", *argv])


class TestScanExitContract:
    @pytest.mark.parametrize("degraded,expected", [(False, 0), (True, 2)])
    def test_scan_status_requires_successful_persistence(self, scan_io, degraded, expected):
        scan_io.report.judge_error = "RuntimeError" if degraded else None
        assert cli.cmd_scan(_scan_args()) == expected
        scan_io.persist.assert_called_once()
        saved = scan_io.persist.call_args.args[0]
        assert saved.checks == scan_io.report.checks and saved.scanned == 2
        assert cli.agents.build_judge.call_args.kwargs["enforce"] is True

    @pytest.mark.parametrize("degraded,expected", [(False, 0), (True, 2)])
    def test_dry_run_never_persists_even_when_degraded(self, scan_io, degraded, expected):
        scan_io.report.judge_error = "RuntimeError" if degraded else None
        assert cli.cmd_scan(_scan_args("--dry-run")) == expected
        scan_io.persist.assert_not_called()

    @pytest.mark.parametrize("degraded", [False, True])
    def test_missing_dsn_is_failure_not_read_only_success(self, scan_io, monkeypatch, degraded):
        scan_io.report.judge_error = "RuntimeError" if degraded else None
        monkeypatch.setattr(cli, "_persist", scan_io.real_persist)
        assert cli.cmd_scan(_scan_args()) == 1

    @pytest.mark.parametrize("degraded", [False, True])
    @pytest.mark.parametrize("error_type", [RuntimeError, db.ProductionWriteRefused,
                                            psycopg.OperationalError])
    def test_write_failures_override_judge_degradation(self, scan_io, degraded, error_type):
        scan_io.report.judge_error = "RuntimeError" if degraded else None
        scan_io.persist.side_effect = error_type("synthetic persistence failure")
        assert cli.cmd_scan(_scan_args()) == 1
        scan_io.persist.assert_called_once()

    @pytest.mark.parametrize("backend", ["mantle", "bedrock"])
    @pytest.mark.parametrize("boundary", ["model", "judge"])
    def test_initialization_failure_still_detects_and_persists(self, scan_io, backend, boundary):
        target = (cli.get_mantle_model if backend == "mantle" else cli.get_model)
        if boundary == "judge":
            target = cli.agents.build_judge
        target.side_effect = RuntimeError("synthetic-private-init-error")
        assert cli.cmd_scan(_scan_args("--judge", backend)) == 2
        scan_io.scan.assert_called_once()
        assert scan_io.scan.call_args.kwargs["judge"] is None
        scan_io.persist.assert_called_once()
        saved = scan_io.persist.call_args.args[0]
        assert saved.checks == scan_io.report.checks
        assert saved.judge_error and "synthetic-private-init-error" not in saved.judge_error

    def test_initialization_error_output_never_contains_raw_secret(self, scan_io, capsys):
        cli.get_mantle_model.side_effect = RuntimeError("synthetic-private-init-error")
        cli.cmd_scan(_scan_args("--dry-run"))
        captured = capsys.readouterr()
        assert "synthetic-private-init-error" not in captured.out + captured.err
        assert "RuntimeError" in captured.out + captured.err

    def test_initialization_failure_and_write_failure_returns_one(self, scan_io):
        cli.get_mantle_model.side_effect = RuntimeError("synthetic initialization failure")
        scan_io.persist.side_effect = RuntimeError("synthetic persistence failure")
        assert cli.cmd_scan(_scan_args()) == 1
        scan_io.scan.assert_called_once()
        scan_io.persist.assert_called_once()

    def test_degraded_scan_enqueues_only_existing_pending_proposals(self, scan_io):
        from everlink.agents import SlotProposal

        scan_io.report.judge_error = "RuntimeError"
        scan_io.report.proposals = [SlotProposal(
            slot=scan_io.report.slots[0], check=scan_io.report.checks[0],
            proposal=Proposal(action="ESCALATE_HUMAN", rationale="synthetic", risk_level="high"))]
        assert cli.cmd_scan(_scan_args()) == 2
        cards = scan_io.persist.call_args.args[2]
        assert len(cards) == 1 and cards[0].status == "pending"
        assert cards[0].affected_slot_ids == ["s1"]

    def test_due_dry_run_uses_read_only_connection_without_schema(self, scan_io, monkeypatch):
        conn = _FakeConn()
        connect = Mock(return_value=conn)
        schema = Mock()
        monkeypatch.setattr(db, "everlink_dsn", lambda: "postgresql://test@example.invalid/own")
        monkeypatch.setattr(db, "connect", connect)
        monkeypatch.setattr(db, "ensure_schema", schema)
        monkeypatch.setattr(db, "fetch_due_slots", Mock(return_value=scan_io.report.slots))
        assert cli.cmd_scan(_scan_args("--select", "due", "--dry-run")) == 0
        assert connect.call_args.kwargs.get("read_only") is True
        schema.assert_not_called()
        assert conn.closed
        scan_io.persist.assert_not_called()
        assert scan_io.scan.call_args.kwargs["preselected"] == scan_io.report.slots

    @pytest.mark.parametrize("boundary", ["connect", "fetch"])
    def test_due_read_failure_is_nonzero_and_closes_open_connection(self, scan_io, monkeypatch, boundary):
        conn = _FakeConn()
        monkeypatch.setattr(db, "everlink_dsn", lambda: "postgresql://test@example.invalid/own")
        connect = Mock(return_value=conn)
        fetch = Mock(return_value=scan_io.report.slots)
        (connect if boundary == "connect" else fetch).side_effect = psycopg.OperationalError("synthetic")
        monkeypatch.setattr(db, "connect", connect)
        monkeypatch.setattr(db, "ensure_schema", Mock())
        monkeypatch.setattr(db, "fetch_due_slots", fetch)
        assert cli.cmd_scan(_scan_args("--select", "due", "--dry-run")) == 1
        if boundary == "fetch":
            assert conn.closed
        scan_io.scan.assert_not_called()
        scan_io.persist.assert_not_called()

    def test_due_missing_dsn_returns_one(self, scan_io):
        assert cli.cmd_scan(_scan_args("--select", "due")) == 1
        scan_io.scan.assert_not_called()
        scan_io.persist.assert_not_called()


ALL = [v for k, v in sorted(globals().items()) if k.startswith("test_")]


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))
