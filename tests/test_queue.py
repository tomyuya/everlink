"""Async-track tests (spec §6 durable decision-queue): the DecisionStore contract,
the DecisionWorker poll loop, DB (de)serialization, and the DbDecisionStore SQL shape
(verified against a fake cursor — no live DB, matching test_db.py's offline style).
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from everlink import queue  # noqa: E402
from everlink.hitl import DecisionWorker, null_handler  # noqa: E402
from everlink.model import Decision, Proposal  # noqa: E402
from everlink.queue import (  # noqa: E402
    DbDecisionStore, InMemoryDecisionStore, decision_to_row, row_to_decision,
)


def _card(cid: str, action: str = "REPLACE_URL", risk: str = "medium",
          slots: list[str] | None = None) -> Decision:
    return Decision(id=cid, affected_slot_ids=slots or [f"{cid}-s1"],
                    proposal=Proposal(action=action, rationale="r", risk_level=risk))


# --------------------------------------------------------------------------- #
# InMemoryDecisionStore — the behavioural contract every store must honour
# --------------------------------------------------------------------------- #
def test_enqueue_then_list_pending():
    s = InMemoryDecisionStore()
    assert s.enqueue([_card("d1"), _card("d2")]) == 2
    assert {c.id for c in s.list_pending()} == {"d1", "d2"}
    assert s.counts() == {"pending": 2}


def test_enqueue_is_idempotent_by_id():
    s = InMemoryDecisionStore()
    assert s.enqueue([_card("d1")]) == 1
    assert s.enqueue([_card("d1")]) == 0        # never resurrect/overwrite
    assert s.counts() == {"pending": 1}


def test_enqueue_does_not_overwrite_a_decided_card():
    s = InMemoryDecisionStore()
    s.enqueue([_card("d1")])
    s.approve("d1")
    s.enqueue([_card("d1")])                    # re-scan surfaces the same id
    assert s.get("d1").status == "approved"     # stayed approved


def test_approve_and_reject_transitions():
    s = InMemoryDecisionStore()
    s.enqueue([_card("d1"), _card("d2")])
    assert s.approve("d1") and s.get("d1").status == "approved"
    assert s.approve("d1") is False             # not pending anymore
    assert s.reject("d2", "too risky") and s.get("d2").status == "rejected"
    assert s.get("d2").reject_reason == "too risky"


def test_approve_missing_returns_false():
    assert InMemoryDecisionStore().approve("nope") is False


def test_claim_next_approved_is_fifo_and_non_mutating():
    s = InMemoryDecisionStore()
    s.enqueue([_card("d1"), _card("d2"), _card("d3")])
    s.approve("d2")                             # approve out of order
    s.approve("d1")
    first = s.claim_next_approved()
    assert first.id == "d2"                     # d2 approved first -> claimed first
    assert s.get("d2").status == "approved"     # claim did NOT mutate status
    s.mark_applied("d2")
    assert s.claim_next_approved().id == "d1"


def test_claim_returns_none_without_approved():
    s = InMemoryDecisionStore()
    s.enqueue([_card("d1")])
    assert s.claim_next_approved() is None


def test_mark_applied_is_terminal():
    s = InMemoryDecisionStore()
    s.enqueue([_card("d1")])
    s.approve("d1")
    assert s.mark_applied("d1") and s.get("d1").status == "applied"
    assert s.mark_applied("d1") is False        # not approved anymore
    assert s.claim_next_approved() is None


def test_list_by_status_filters_and_defaults_to_all():
    s = InMemoryDecisionStore()
    s.enqueue([_card("d1"), _card("d2"), _card("d3")])
    s.approve("d1")
    s.reject("d2", "no")
    assert {c.id for c in s.list_by_status("approved")} == {"d1"}
    assert {c.id for c in s.list_by_status("rejected")} == {"d2"}
    assert {c.id for c in s.list_by_status("pending")} == {"d3"}
    assert len(s.list_by_status()) == 3                 # None -> all
    assert s.list_by_status("applied") == []
    assert len(s.list_by_status("pending", limit=0)) == 0   # limit honoured


# --------------------------------------------------------------------------- #
# (de)serialization — pure
# --------------------------------------------------------------------------- #
def test_decision_row_roundtrip():
    card = _card("d1", action="REWRITE_SENTENCE", risk="high", slots=["a", "b"])
    row = decision_to_row(card)
    back = row_to_decision(row)
    assert back.id == card.id and back.affected_slot_ids == ["a", "b"]
    assert back.proposal.action == "REWRITE_SENTENCE" and back.proposal.risk_level == "high"
    assert back.status == card.status


# --------------------------------------------------------------------------- #
# DecisionWorker — async poll loop (at-least-once)
# --------------------------------------------------------------------------- #
def test_worker_applies_approved_decision():
    s = InMemoryDecisionStore()
    s.enqueue([_card("d1")])
    s.approve("d1")
    seen: list[Decision] = []
    w = DecisionWorker(s, handler=seen.append)
    assert w.poll_once() == 1
    assert [d.id for d in seen] == ["d1"]
    assert s.get("d1").status == "applied"


def test_worker_ignores_pending_and_rejected():
    s = InMemoryDecisionStore()
    s.enqueue([_card("d1"), _card("d2")])
    s.reject("d2", "no")
    seen: list[Decision] = []
    w = DecisionWorker(s, handler=seen.append)
    assert w.poll_once() == 0                   # nothing approved
    assert seen == []


def test_worker_drains_all_approved_in_one_poll():
    s = InMemoryDecisionStore()
    s.enqueue([_card("d1"), _card("d2"), _card("d3")])
    for cid in ("d1", "d2", "d3"):
        s.approve(cid)
    seen: list[Decision] = []
    w = DecisionWorker(s, handler=seen.append)
    assert w.poll_once() == 3
    assert s.counts() == {"applied": 3}


def test_worker_handler_failure_leaves_card_approved_for_retry():
    s = InMemoryDecisionStore()
    s.enqueue([_card("d1")])
    s.approve("d1")

    def boom(_d):
        raise RuntimeError("writer blew up")

    w = DecisionWorker(s, handler=boom)
    assert w.poll_once() == 0                   # failed, not applied
    assert s.get("d1").status == "approved"     # still approved -> will retry

    ok: list[Decision] = []
    w.handler = ok.append                        # fix the handler
    assert w.poll_once() == 1                    # retried successfully
    assert s.get("d1").status == "applied"


def test_worker_run_bounded_by_max_iterations():
    s = InMemoryDecisionStore()
    s.enqueue([_card("d1")])
    s.approve("d1")
    seen: list[Decision] = []
    w = DecisionWorker(s, handler=seen.append)
    total = w.run(poll_interval=0.0, max_iterations=2)
    assert total == 1 and len(seen) == 1


def test_worker_run_stops_on_predicate():
    s = InMemoryDecisionStore()
    w = DecisionWorker(s, handler=null_handler)
    assert w.run(poll_interval=0.0, stop=lambda: True) == 0   # stops immediately


def test_worker_audits_applied_write():
    from everlink.steering import AuditCollector
    s = InMemoryDecisionStore()
    s.enqueue([_card("d1")])
    s.approve("d1")
    col = AuditCollector()
    w = DecisionWorker(s, handler=null_handler, audit_sink=col)
    w.poll_once()
    assert "write" in col.events()


# --------------------------------------------------------------------------- #
# DbDecisionStore — SQL shape verified against a fake cursor (no live DB)
# --------------------------------------------------------------------------- #
class _FakeCursor:
    def __init__(self, conn):
        self._conn = conn
        self.rowcount = 0
        self._rows: list = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self._conn.log.append((sql, params))
        self._rows = self._conn.responder(sql, params)
        self.rowcount = self._conn.rowcount_for(sql, params)

    def executemany(self, sql, rows):
        self._conn.log.append((sql, rows))

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None


class _FakeInfo:
    dsn = "postgresql://u@ep-everlink-test.aws.neon.tech/everlink"


class _FakeConn:
    def __init__(self, responder=None, rowcount_for=None):
        self.log: list = []
        self.info = _FakeInfo()
        self._responder = responder or (lambda sql, params: [])
        self._rowcount_for = rowcount_for or (lambda sql, params: 0)

    def cursor(self):
        return _FakeCursor(self)

    def commit(self):
        pass

    def responder(self, sql, params):
        return self._responder(sql, params)

    def rowcount_for(self, sql, params):
        return self._rowcount_for(sql, params)


def _clear_deny_env():
    for k in ("AETHELGEM_DATABASE_URL", "SANDCART_DATABASE_URL",
              "HOTDEALS_DATABASE_URL", "EVERLINK_FORBIDDEN_HOSTS"):
        os.environ.pop(k, None)


def test_db_enqueue_serializes_proposal_as_json():
    _clear_deny_env()
    conn = _FakeConn()
    store = DbDecisionStore(conn)
    store.enqueue([_card("d1")])
    insert = [e for e in conn.log if e[0].startswith("INSERT INTO decisions")]
    assert insert, conn.log
    params = insert[0][1][0]                     # first executemany row
    assert params[0] == "d1"
    assert '"action": "REPLACE_URL"' in params[2] or '"action":"REPLACE_URL"' in params[2]


def test_db_approve_updates_only_pending():
    _clear_deny_env()
    conn = _FakeConn(rowcount_for=lambda sql, p: 1 if sql.startswith("UPDATE") else 0)
    store = DbDecisionStore(conn)
    assert store.approve("d1") is True
    update = [e for e in conn.log if e[0].startswith("UPDATE decisions")][0]
    assert "status = %s" in update[0] and "AND status = %s" in update[0]
    assert update[1][0] == "approved" and update[1][-1] == "pending"


def test_db_claim_selects_approved_and_deserializes():
    _clear_deny_env()
    row = decision_to_row(_card("d9", action="DROP_BLOCK", risk="high"))

    def responder(sql, params):
        if sql.startswith("SELECT") and "status = %s" in sql:
            return [row]
        return []

    conn = _FakeConn(responder=responder)
    store = DbDecisionStore(conn)
    dec = store.claim_next_approved()
    assert dec is not None and dec.id == "d9"
    assert dec.proposal.action == "DROP_BLOCK"
    claim_sql = [e for e in conn.log if e[0].startswith("SELECT")][0][0]
    assert "FOR UPDATE SKIP LOCKED" in claim_sql


def test_db_counts_groups_by_status():
    _clear_deny_env()
    conn = _FakeConn(responder=lambda sql, p: [("pending", 3), ("applied", 1)]
                     if sql.startswith("SELECT status") else [])
    store = DbDecisionStore(conn)
    assert store.counts() == {"pending": 3, "applied": 1}


def test_db_list_by_status_filters_and_deserializes():
    _clear_deny_env()
    row = decision_to_row(_card("d5", action="REWRITE_SENTENCE"))

    def responder(sql, params):
        if sql.startswith("SELECT") and "WHERE status = %s" in sql:
            return [row]
        return []

    conn = _FakeConn(responder=responder)
    store = DbDecisionStore(conn)
    out = store.list_by_status("approved", limit=10)
    assert [c.id for c in out] == ["d5"]
    assert out[0].proposal.action == "REWRITE_SENTENCE"
    sql, params = [e for e in conn.log if e[0].startswith("SELECT")][0]
    assert "WHERE status = %s" in sql and "ORDER BY created_at" in sql
    assert params == ("approved", 10)


def test_db_list_by_status_all_omits_where_clause():
    _clear_deny_env()
    conn = _FakeConn(responder=lambda sql, p: [])
    store = DbDecisionStore(conn)
    store.list_by_status(None, limit=5)
    sql, params = [e for e in conn.log if e[0].startswith("SELECT")][0]
    assert "WHERE status" not in sql and params == (5,)


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
