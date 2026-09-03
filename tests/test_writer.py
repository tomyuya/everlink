"""Writer-engine tests (spec §4.1 Phase E / §5 write_snapshots / §12-3 acceptance).

Offline and DB-free: a fake psycopg ``conn`` models EverLink's own ``link_slots`` /
``write_snapshots`` / ``slot_checks`` tables (same style as test_queue.py's fake cursor,
plus a ``transaction()`` context manager so the single-transaction write path is
exercised), and ``verify_fix``'s network re-probe is injected — NO live DB, NO network,
NO AWS credentials.

What is proven here:
  * PURE logic — compute_after / writing_violations / interpret_verify.
  * apply_fix GATES — not-approved, disclosure, scope, out-of-scope site, no-op.
  * apply_fix WRITES — content updated + before/after snapshot recorded (single tx).
  * verify_fix — editorial fixes pass trivially (probed=False); a REPLACE_URL is really
    re-probed; only 'healthy' counts as verified; the re-probe is recorded to slot_checks.
  * rollback — restores the before-state and stamps rolled_back_at.
  * run_fix — verify failure rolls the slot back and dead-letters the card.
  * handler + worker — a dead-lettered card ends 'rejected' (not applied, not retried);
    a clean card is applied by the worker.

HONESTY: the fake probe scripts the verdict; it does not exercise real L1/L2 network
detection. The live write-back / verify / rollback round-trip is verified separately
against EverLink's own DB (see the pe1 live check), never against a source site.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from everlink import db, writer  # noqa: E402
from everlink.hitl import DecisionWorker  # noqa: E402
from everlink.model import CheckResult, Decision, Proposal  # noqa: E402
from everlink.queue import InMemoryDecisionStore  # noqa: E402
from everlink.steering import AuditCollector  # noqa: E402


# --------------------------------------------------------------------------- #
# fake psycopg connection over an in-memory model of EverLink's own tables
# --------------------------------------------------------------------------- #
class _NoopTxn:
    """``with conn.transaction():`` — commits on clean exit, propagates on exception."""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FakeInfo:
    dsn = "postgresql://u@ep-everlink-test.aws.neon.tech/everlink"


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
        s = " ".join(sql.split())
        self.rowcount = 0
        self._rows = []
        if s.startswith("SELECT url, target_url, anchor_text, surrounding_sentence, status "
                        "FROM link_slots"):
            row = self._conn.slot_content(params[0])
            self._rows = [row] if row else []
        elif s.startswith("SELECT") and "FROM link_slots WHERE id" in s:
            row = self._conn.slot_full(params[0])
            self._rows = [row] if row else []
        elif s.startswith("SELECT status FROM decisions"):
            st = self._conn.decisions.get(params[0])
            self._rows = [(st,)] if st else []
        elif s.startswith("UPDATE link_slots SET"):
            self.rowcount = self._conn.update_slot(s, params)
        elif s.startswith("INSERT INTO write_snapshots"):
            self._rows = [(self._conn.add_snapshot(params),)]
            self.rowcount = 1
        elif s.startswith("SELECT id, before_json, after_json, applied_at, rolled_back_at "
                          "FROM write_snapshots"):
            row = self._conn.latest_snapshot(params[0], params[1])
            self._rows = [row] if row else []
        elif s.startswith("UPDATE write_snapshots SET rolled_back_at"):
            self.rowcount = self._conn.mark_rolled_back(params[0])
        elif s.startswith("INSERT INTO slot_checks"):
            self._conn.checks.append(params)
            self.rowcount = 1

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None


class _FakeConn:
    def __init__(self, slots=None):
        self.log: list = []
        self.info = _FakeInfo()
        self.slots: dict[str, dict] = dict(slots or {})
        self.snapshots: list = []
        self.checks: list = []
        self.decisions: dict[str, str] = {}
        self._snap_seq = 0

    def cursor(self):
        return _FakeCursor(self)

    def transaction(self):
        return _NoopTxn()

    def commit(self):
        pass

    def close(self):
        pass

    # -- table model -- #
    def slot_full(self, slot_id):
        d = self.slots.get(slot_id)
        return tuple(d[c] for c in db.SLOT_COLUMNS) if d else None

    def slot_content(self, slot_id):
        d = self.slots.get(slot_id)
        return tuple(d[c] for c in db.CONTENT_FIELDS) if d else None

    def update_slot(self, normalized_sql, params):
        set_part = normalized_sql.split(" SET ", 1)[1].split(", updated_at = now()", 1)[0]
        cols = [a.split(" = ")[0].strip() for a in set_part.split(", ")]
        slot_id = params[-1]
        if slot_id not in self.slots:
            return 0
        for i, c in enumerate(cols):
            self.slots[slot_id][c] = params[i]
        return 1

    def add_snapshot(self, params):
        self._snap_seq += 1
        self.snapshots.append({"id": self._snap_seq, "slot_id": params[0],
                               "decision_id": params[1], "before_json": params[2],
                               "after_json": params[3], "applied_at": "now",
                               "rolled_back_at": None})
        return self._snap_seq

    def latest_snapshot(self, decision_id, slot_id):
        m = [s for s in self.snapshots
             if s["decision_id"] == decision_id and s["slot_id"] == slot_id]
        if not m:
            return None
        s = max(m, key=lambda x: x["id"])
        return (s["id"], s["before_json"], s["after_json"], s["applied_at"], s["rolled_back_at"])

    def mark_rolled_back(self, snap_id):
        for s in self.snapshots:
            if s["id"] == snap_id and s["rolled_back_at"] is None:
                s["rolled_back_at"] = "now"
                return 1
        return 0


def _clear_deny_env():
    for k in ("AETHELGEM_DATABASE_URL", "SANDCART_DATABASE_URL",
              "HOTDEALS_DATABASE_URL", "EVERLINK_FORBIDDEN_HOSTS"):
        os.environ.pop(k, None)


def _slot_row(slot_id, *, site="aethelgem", slot_type="commercial",
              url="https://dead.example/p", anchor="the widget",
              sentence="It costs $19 today.", protected=0,
              block_type="product_card", role=None, status="active"):
    return {"id": slot_id, "site": site, "article_id": "a1", "article_title": "Title",
            "block_id": "b1", "block_type": block_type, "slot_type": slot_type, "role": role,
            "anchor_text": anchor, "url": url, "target_url": url,
            "surrounding_sentence": sentence, "regions": '["us"]', "protected": protected,
            "status": status}


def _conn(**extra_slots):
    _clear_deny_env()
    slots = {"aeg-1": _slot_row("aeg-1")}
    slots.update(extra_slots)
    return _FakeConn(slots)


def _dec(cid="dec-1", slots=None, action="REPLACE_URL", new_url="https://live.example/p",
         risk="medium", **prop):
    return Decision(id=cid, affected_slot_ids=slots or ["aeg-1"],
                    proposal=Proposal(action=action, new_url=new_url, rationale="r",
                                      risk_level=risk, **prop))


_YES = lambda _cid: True   # noqa: E731  - injected approval (all decisions approved)
_NO = lambda _cid: False   # noqa: E731  - injected approval (nothing approved)


def _probe(verdict="healthy", l1=200, l2=None):
    def p(slot, *, timeout=15.0, use_l2=True):
        return CheckResult(slot_id=slot.id, l1_status=l1, final_verdict=verdict, l2_verdict=l2)
    return p


# --------------------------------------------------------------------------- #
# PURE logic
# --------------------------------------------------------------------------- #
def test_compute_after_replace_url_sets_url_and_target():
    before = {"url": "https://dead", "target_url": "https://dead", "anchor_text": "a",
              "surrounding_sentence": "s", "status": "active"}
    after = writer.compute_after(before, _dec().proposal)
    assert after["url"] == "https://live.example/p"
    assert after["target_url"] == "https://live.example/p"
    assert after["anchor_text"] == "a" and after["status"] == "active"   # untouched


def test_compute_after_editorial_and_drop():
    before = {"url": "u", "target_url": "u", "anchor_text": "old", "surrounding_sentence": "old",
              "status": "active"}
    anchor = writer.compute_after(before, Proposal(action="REWRITE_ANCHOR", new_anchor="new",
                                                   rationale="r", risk_level="low"))
    assert anchor["anchor_text"] == "new" and anchor["url"] == "u"
    sent = writer.compute_after(before, Proposal(action="REWRITE_SENTENCE", new_sentence="ns",
                                                 rationale="r", risk_level="high"))
    assert sent["surrounding_sentence"] == "ns"
    drop = writer.compute_after(before, Proposal(action="DROP_BLOCK", rationale="r",
                                                 risk_level="high"))
    assert drop["status"] == "archived"          # soft-drop, reversible, nothing destroyed
    esc = writer.compute_after(before, Proposal(action="ESCALATE_HUMAN", rationale="r",
                                                risk_level="high"))
    assert esc == before                          # no change => caller refuses the no-op


def test_writing_violations_flags_disclosure_scope_and_escalate():
    prop = _dec().proposal
    disc = writer.writing_violations(
        _row_to_slot(_slot_row("p", block_type="disclosure")), prop)
    assert disc and "disclosure" in disc[0].lower()
    scope = writer.writing_violations(
        _row_to_slot(_slot_row("r", slot_type="reference")), prop)
    assert scope and "scope" in scope[0].lower()
    esc = writer.writing_violations(_row_to_slot(_slot_row("x")),
                                    Proposal(action="ESCALATE_HUMAN", rationale="r",
                                             risk_level="high"))
    assert esc and "ESCALATE_HUMAN" in esc[0]
    assert writer.writing_violations(_row_to_slot(_slot_row("ok")), prop) == []


def _row_to_slot(row_dict):
    from everlink.model import LinkSlot
    return LinkSlot(**{k: row_dict[k] for k in (
        "id", "site", "article_id", "article_title", "block_id", "block_type", "slot_type",
        "role", "anchor_text", "url", "target_url", "surrounding_sentence", "regions",
        "protected", "status")})


def test_interpret_verify_only_healthy_is_verified():
    assert writer.interpret_verify(CheckResult(slot_id="s", final_verdict="healthy",
                                               l1_status=200))[0] is True
    for bad in ("dead", "offer_changed", "program_ended", "needs_human_recheck"):
        ok, reason = writer.interpret_verify(CheckResult(slot_id="s", final_verdict=bad,
                                                         l1_status=200))
        assert ok is False and "NOT verified" in reason


# --------------------------------------------------------------------------- #
# apply_fix — gates + the single-transaction write
# --------------------------------------------------------------------------- #
def test_apply_fix_refuses_when_not_approved():
    conn = _conn()
    w = writer.apply_fix(conn, _dec(), "aeg-1", is_approved=_NO)
    assert w.status == "refused" and "not approved" in w.reason
    assert conn.snapshots == [] and conn.slots["aeg-1"]["url"] == "https://dead.example/p"


def test_apply_fix_writes_content_and_records_snapshot():
    conn = _conn()
    w = writer.apply_fix(conn, _dec(), "aeg-1", is_approved=_YES)
    assert w.status == "applied" and w.snapshot_id == 1
    assert conn.slots["aeg-1"]["url"] == "https://live.example/p"       # content updated
    assert conn.slots["aeg-1"]["target_url"] == "https://live.example/p"
    assert len(conn.snapshots) == 1                                      # before/after recorded
    assert "https://dead.example/p" in conn.snapshots[0]["before_json"]
    assert "https://live.example/p" in conn.snapshots[0]["after_json"]


def test_apply_fix_skips_out_of_writeback_scope():
    conn = _conn(**{"sc-1": _slot_row("sc-1", site="sandcart")})
    w = writer.apply_fix(conn, _dec(slots=["sc-1"]), "sc-1", is_approved=_YES)
    assert w.status == "skipped" and "write-back scope" in w.reason
    assert conn.snapshots == []                                          # nothing written


def test_apply_fix_refuses_disclosure_slot():
    conn = _conn(**{"p-1": _slot_row("p-1", block_type="disclosure")})
    w = writer.apply_fix(conn, _dec(slots=["p-1"]), "p-1", is_approved=_YES)
    assert w.status == "refused" and "disclosure" in w.reason.lower()
    assert conn.snapshots == []


def test_apply_fix_refuses_reference_replace_url():
    conn = _conn(**{"r-1": _slot_row("r-1", slot_type="reference")})
    w = writer.apply_fix(conn, _dec(slots=["r-1"]), "r-1", is_approved=_YES)
    assert w.status == "refused" and "scope" in w.reason.lower()


def test_apply_fix_refuses_noop_replace_without_new_url():
    conn = _conn()
    d = _dec(new_url=None)
    w = writer.apply_fix(conn, d, "aeg-1", is_approved=_YES)
    assert w.status == "refused" and "no content change" in w.reason
    assert conn.snapshots == []


def test_apply_fix_refuses_missing_slot():
    conn = _conn()
    w = writer.apply_fix(conn, _dec(slots=["ghost"]), "ghost", is_approved=_YES)
    assert w.status == "refused" and "not found" in w.reason


# --------------------------------------------------------------------------- #
# verify_fix — real re-probe only for a replacement URL
# --------------------------------------------------------------------------- #
def test_verify_fix_editorial_passes_without_probing():
    conn = _conn()
    d = _dec(action="REWRITE_ANCHOR", new_url=None, new_anchor="a live vendor page")
    calls = []

    def probe(slot, *, timeout=15.0, use_l2=True):
        calls.append(slot.id)
        return CheckResult(slot_id=slot.id, final_verdict="healthy")

    v = writer.verify_fix(conn, d, "aeg-1", probe=probe)
    assert v.verified is True and v.probed is False and calls == []   # no network for editorial
    assert conn.checks == []                                          # nothing recorded


def test_verify_fix_reprobes_replacement_and_records_check():
    conn = _conn()
    v = writer.verify_fix(conn, _dec(), "aeg-1", probe=_probe("healthy", 200))
    assert v.verified is True and v.probed is True and v.verdict == "healthy"
    assert len(conn.checks) == 1                                     # recorded to slot_checks


def test_verify_fix_fails_when_replacement_also_dead():
    conn = _conn()
    v = writer.verify_fix(conn, _dec(), "aeg-1", probe=_probe("dead", 404))
    assert v.verified is False and v.probed is True and v.verdict == "dead"


# --------------------------------------------------------------------------- #
# rollback — restore before-state
# --------------------------------------------------------------------------- #
def test_rollback_restores_content_and_stamps_snapshot():
    conn = _conn()
    writer.apply_fix(conn, _dec(), "aeg-1", is_approved=_YES)
    assert conn.slots["aeg-1"]["url"] == "https://live.example/p"
    r = writer.rollback(conn, _dec(), "aeg-1")
    assert r.status == "rolled_back"
    assert conn.slots["aeg-1"]["url"] == "https://dead.example/p"     # restored
    assert conn.snapshots[0]["rolled_back_at"] is not None


def test_rollback_without_snapshot_is_refused():
    conn = _conn()
    r = writer.rollback(conn, _dec(), "aeg-1")
    assert r.status == "refused" and "no write_snapshot" in r.reason


# --------------------------------------------------------------------------- #
# run_fix — the per-decision core (apply -> verify -> rollback + dead-letter)
# --------------------------------------------------------------------------- #
def test_run_fix_happy_path_is_ok():
    conn = _conn()
    out = writer.run_fix(conn, _dec(), is_approved=_YES, probe=_probe("healthy"))
    assert out.ok is True and out.dead_letter == ""
    assert out.applied_slots == ["aeg-1"] and out.rolled_back == []


def test_run_fix_rolls_back_and_dead_letters_on_failed_verify():
    conn = _conn()
    out = writer.run_fix(conn, _dec(), is_approved=_YES, probe=_probe("dead", 404))
    assert out.ok is False and out.rolled_back == ["aeg-1"]
    assert out.dead_letter and "NOT verified" in out.dead_letter
    assert conn.slots["aeg-1"]["url"] == "https://dead.example/p"     # rolled back


def test_run_fix_dead_letters_when_nothing_writable():
    conn = _conn(**{"sc-1": _slot_row("sc-1", site="sandcart")})
    out = writer.run_fix(conn, _dec(slots=["sc-1"]), is_approved=_YES, probe=_probe())
    assert out.applied_slots == [] and out.dead_letter and "nothing to do" in out.dead_letter


def test_run_fix_partial_scope_applies_writable_slot():
    conn = _conn(**{"sc-1": _slot_row("sc-1", site="sandcart")})
    out = writer.run_fix(conn, _dec(slots=["aeg-1", "sc-1"]), is_approved=_YES,
                         probe=_probe("healthy"))
    assert out.applied_slots == ["aeg-1"]                             # aethelgem applied
    assert out.dead_letter == ""                                      # sandcart skipped, not a failure
    assert [w.status for w in out.writes] == ["applied", "skipped"]


# --------------------------------------------------------------------------- #
# handler + worker integration (dead-letter vs applied)
# --------------------------------------------------------------------------- #
def test_handler_dead_letters_card_on_failed_verify():
    conn = _conn()
    store = InMemoryDecisionStore()
    d = _dec()
    store.enqueue([d])
    store.approve("dec-1")
    col = AuditCollector()
    handler = writer.make_writer_handler(
        conn, store, is_approved=lambda cid: store.get(cid).status == "approved",
        audit_sink=col, probe=_probe("dead", 404))
    handler(store.get("dec-1"))
    assert store.get("dec-1").status == "rejected"                    # terminally dead-lettered
    assert store.get("dec-1").reject_reason and "NOT verified" in store.get("dec-1").reject_reason
    assert "rollback" in col.events() and "verify" in col.events()


def test_handler_leaves_card_approved_on_success():
    conn = _conn()
    store = InMemoryDecisionStore()
    store.enqueue([_dec()])
    store.approve("dec-1")
    col = AuditCollector()
    handler = writer.make_writer_handler(
        conn, store, is_approved=lambda cid: store.get(cid).status == "approved",
        audit_sink=col, probe=_probe("healthy"))
    handler(store.get("dec-1"))
    assert store.get("dec-1").status == "approved"                    # worker will mark applied
    assert "write" in col.events()


def test_worker_applies_clean_card_and_dead_letters_bad_one():
    conn = _conn(**{"aeg-2": _slot_row("aeg-2", url="https://dead2.example/p")})
    store = InMemoryDecisionStore()
    good = _dec(cid="dec-good", slots=["aeg-1"])
    bad = _dec(cid="dec-bad", slots=["aeg-2"], new_url="https://also-dead.example/p")
    store.enqueue([good, bad])
    store.approve("dec-good")
    store.approve("dec-bad")
    col = AuditCollector()

    def probe(slot, *, timeout=15.0, use_l2=True):
        verdict = "healthy" if "live" in slot.url else "dead"
        return CheckResult(slot_id=slot.id, final_verdict=verdict,
                           l1_status=200 if verdict == "healthy" else 404)

    handler = writer.make_writer_handler(
        conn, store, is_approved=lambda cid: store.get(cid).status == "approved",
        audit_sink=col, probe=probe)
    w = DecisionWorker(store, handler=handler, audit_sink=col)
    applied = w.poll_once()
    assert applied == 1                                                # only the clean card
    assert store.get("dec-good").status == "applied"
    assert store.get("dec-bad").status == "rejected"                   # dead-lettered, not retried
    assert w.poll_once() == 0                                          # nothing approved remains
    assert "dead_letter" in col.events() and "write" in col.events()


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
