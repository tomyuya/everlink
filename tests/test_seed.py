"""Demo-seed tests (spec §7 line 244 / §11 beats / §2.1 "fixture 回放须明确标注").

Offline and DB-free. Two layers:

  * PURE builder — ``seed.build_seed`` must reproduce the exact demo-night counts the
    narrator reads (41 problem slots · approved 38 / rejected 3 · 37 healed · 1 rolled
    back · final applied 37 / rejected 4 / pending 1), deterministically, with every
    ``final_verdict`` a real ``model.Verdict`` literal (guards the soft-404 mapping), the
    three steering safety curtains audited as ``steering_cancel``, and the pe2 rollback
    recommendation surfaced as a pending ESCALATE_HUMAN card.
  * FAKE-CONN writer — ``write_seed`` / ``reset_seed`` / ``seed_stats`` are exercised
    against an in-memory model of EverLink's own tables (same style as test_writer.py),
    proving the single-transaction write persists every table, is idempotent
    (delete-then-insert), resets to zero in FK-safe order, and REFUSES a forbidden
    source/production host via ``db._assert_writable``.

HONESTY: this never touches a real DB, the network, or AWS. It asserts the seed's SHAPE
and the writer's SQL contract; the live round-trip against EverLink's own Neon store is
verified separately (pf2e), never against a source site or the Blue Neon production host.
"""
import json
import os
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import get_args

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from everlink import model, seed  # noqa: E402
from everlink.db import ProductionWriteRefused  # noqa: E402

_VALID_VERDICTS = set(get_args(model.Verdict))
_FIXED = datetime(2026, 9, 2, 6, 0, 0, tzinfo=timezone.utc)


# --------------------------------------------------------------------------- #
# fake psycopg connection over an in-memory model of EverLink's own tables
# --------------------------------------------------------------------------- #
class _NoopTxn:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FakeInfo:
    dsn = "postgresql://u@ep-everlink-test.aws.neon.tech/everlink"


class _FakeCursor:
    def __init__(self, conn):
        self._c = conn
        self.rowcount = 0
        self._rows: list = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def executemany(self, sql, rows):
        for r in rows:
            self.execute(sql, r)

    def execute(self, sql, params=None):
        s = " ".join(sql.split())
        self._c.log.append((s, params))
        self.rowcount = 0
        self._rows = []
        c = self._c
        if s.startswith("INSERT INTO link_slots"):
            c.slots[params[0]] = params
            self.rowcount = 1
        elif s.startswith("INSERT INTO slot_checks"):
            c.checks.append(params)
            self.rowcount = 1
        elif s.startswith("INSERT INTO decisions"):
            c.decisions[params[0]] = params
            self.rowcount = 1
        elif s.startswith("INSERT INTO write_snapshots"):
            c.snapshots.append(params)
            self.rowcount = 1
        elif s.startswith("INSERT INTO audit_log"):
            c.audit.append(params)
            self.rowcount = 1
        elif s.startswith("DELETE FROM write_snapshots"):
            self.rowcount = c.del_snapshots(params)
        elif s.startswith("DELETE FROM slot_checks"):
            self.rowcount = c.del_checks(params)
        elif s.startswith("DELETE FROM decisions"):
            self.rowcount = c.del_decisions(params)
        elif s.startswith("DELETE FROM link_slots"):
            self.rowcount = c.del_slots(params)
        elif s.startswith("DELETE FROM audit_log"):
            self.rowcount = c.del_audit(params)
        elif s.startswith("SELECT count(*) FROM link_slots"):
            self._rows = [(c.count_in(c.slots, params[0]),)]
        elif s.startswith("SELECT status, count(*) FROM decisions"):
            self._rows = c.decision_by_status(params[0])
        elif s.startswith("SELECT count(*) FROM slot_checks"):
            self._rows = [(sum(1 for x in c.checks if x[0] in params[0]),)]
        elif s.startswith("SELECT count(*) FROM write_snapshots") and "rolled_back_at" in s:
            self._rows = [(sum(1 for x in c.snapshots
                               if x[0] in params[0] and x[5] is not None),)]
        elif s.startswith("SELECT count(*) FROM write_snapshots"):
            self._rows = [(sum(1 for x in c.snapshots if x[0] in params[0]),)]
        elif s.startswith("SELECT count(*) FROM audit_log"):
            self._rows = [(c.count_audit(params[0]),)]

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None


class _FakeConn:
    def __init__(self):
        self.log: list = []
        self.info = _FakeInfo()
        self.slots: dict = {}
        self.checks: list = []
        self.decisions: dict = {}
        self.snapshots: list = []
        self.audit: list = []

    def cursor(self):
        return _FakeCursor(self)

    def transaction(self):
        return _NoopTxn()

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        pass

    # -- table model -- #
    @staticmethod
    def count_in(d, ids):
        return sum(1 for k in d if k in ids)

    def del_snapshots(self, p):
        slot_ids = p[0]
        card_ids = p[1] if len(p) > 1 else None
        before = len(self.snapshots)
        self.snapshots = [x for x in self.snapshots
                          if x[0] not in slot_ids and not (card_ids and x[1] in card_ids)]
        return before - len(self.snapshots)

    def del_checks(self, p):
        before = len(self.checks)
        self.checks = [x for x in self.checks if x[0] not in p[0]]
        return before - len(self.checks)

    def del_decisions(self, p):
        before = len(self.decisions)
        self.decisions = {k: v for k, v in self.decisions.items() if k not in p[0]}
        return before - len(self.decisions)

    def del_slots(self, p):
        before = len(self.slots)
        self.slots = {k: v for k, v in self.slots.items() if k not in p[0]}
        return before - len(self.slots)

    def del_audit(self, p):
        mark = p[0].strip("%")
        before = len(self.audit)
        self.audit = [x for x in self.audit if mark not in x[3]]
        return before - len(self.audit)

    def count_audit(self, like):
        mark = like.strip("%")
        return sum(1 for x in self.audit if mark in x[3])

    def decision_by_status(self, ids):
        cnt = Counter(v[3] for k, v in self.decisions.items() if k in ids)
        return [(status, n) for status, n in cnt.items()]


def _clear_deny_env():
    for k in ("AETHELGEM_DATABASE_URL", "SANDCART_DATABASE_URL",
              "HOTDEALS_DATABASE_URL", "EVERLINK_FORBIDDEN_HOSTS"):
        os.environ.pop(k, None)


def _conn():
    _clear_deny_env()
    return _FakeConn()


# --------------------------------------------------------------------------- #
# PURE builder — the demo-night counts the narrator reads
# --------------------------------------------------------------------------- #
def test_build_seed_hits_spec_anchor_counts():
    s = seed.build_seed(_FIXED).summary()
    assert s["slots"] == 41                       # spec §11 "早间报告 41 问题槽"
    assert s["scan_cards"] == 41
    assert s["decision_rows"] == 42               # 41 scan + 1 rollback recommendation
    assert s["human_approved"] == 38              # spec §11 "批 38"
    assert s["human_rejected"] == 3               # spec §11 "驳 3"
    assert s["links_healed"] == 37                # spec §11 "37 dead→0"
    assert s["rolled_back"] == 1                  # spec §11 "一条回滚演示"
    assert s["final_status"] == {"applied": 37, "rejected": 4, "pending": 1}


def test_build_seed_site_and_verdict_distribution():
    s = seed.build_seed(_FIXED).summary()
    assert s["by_site"] == {"aethelgem": 39, "hotdeals": 1, "sandcart": 1}
    # the 2 soft-404 slots fold to 'offer_changed' via the REAL detect oracle (page lives,
    # offer died), so offer_changed = 1 price-drift + 2 soft-404 = 3; dead = 35 - 2 = 33.
    assert s["by_verdict"] == {"dead": 33, "program_ended": 5, "offer_changed": 3}
    assert s["protected_slots"] == 1              # the affiliate-disclosure block


def test_final_verdict_mapping_matches_the_real_detector():
    """The replay must never drift from production detection: every label's final_verdict
    is literally ``detect.combine_verdict`` over its (l1_verdict, l2_verdict)."""
    from everlink import detect
    for label, spec in seed._VERDICTS.items():
        l1_verdict, _status, l2_verdict = spec[0], spec[1], spec[2]
        assert seed._final_of(label) == detect.combine_verdict(l1_verdict, l2_verdict), label
    # the soft-404 is the case that a hardcoded map got wrong: it is 'offer_changed', not 'dead'
    assert seed._final_of("dead_soft404") == "offer_changed"
    assert seed._final_of("dead") == "dead"


def test_build_seed_is_deterministic():
    a = seed.build_seed(_FIXED)
    b = seed.build_seed(_FIXED)
    assert a.slot_ids == b.slot_ids               # stable ids => idempotent upsert/reset
    assert a.card_ids == b.card_ids
    assert a.summary() == b.summary()


def test_every_final_verdict_is_a_valid_model_literal():
    plan = seed.build_seed(_FIXED)
    for _ts, check in list(plan.scan_checks) + list(plan.verify_checks):
        assert check.final_verdict in _VALID_VERDICTS, check.final_verdict
    # the soft-404 label maps to a real 'dead' final verdict, never the l2 'unavailable'
    assert "unavailable" not in {c.final_verdict for _t, c in plan.scan_checks}


def test_rejected_cards_carry_reasons():
    plan = seed.build_seed(_FIXED)
    rejected = [c for c in plan.all_cards if c.status == "rejected"]
    assert len(rejected) == 4                     # 3 human + 1 machine dead-letter
    for c in rejected:
        assert c.reject_reason and c.reject_reason.strip()


def test_three_steering_curtains_are_audited():
    plan = seed.build_seed(_FIXED)
    cancels = [json.loads(r["payload"]) for r in plan.audit
               if r["event"] == "steering_cancel"]
    policies = {c["policy"] for c in cancels}
    assert len(cancels) == 3
    assert policies == {"disclosure_policy", "scope_policy", "editorial_policy"}
    for c in cancels:                             # the real steering Guide message shape
        assert c["cancel_message"].startswith("Tool call cancelled by EverLink steering")


def test_rollback_recommendation_card_is_pending_escalate():
    plan = seed.build_seed(_FIXED)
    rec = plan.reco_card
    assert rec is not None
    assert rec.status == "pending"                # surfaced to a human, never auto-applied
    assert rec.proposal.action == "ESCALATE_HUMAN"
    assert rec.proposal.risk_level == "high"
    assert rec.id.endswith("-rollback")


def test_audit_event_mix_and_shape():
    plan = seed.build_seed(_FIXED)
    ev = Counter(r["event"] for r in plan.audit)
    assert ev["interrupt"] == 41                  # one per scan card
    assert ev["write"] == 38 and ev["verify"] == 38
    assert ev["rollback"] == 1 and ev["dead_letter"] == 1
    assert ev["notify"] == 2                      # morning brief + decision cards
    for r in plan.audit:                          # every row is a well-formed audit record
        assert set(r) == {"ts", "agent", "event", "payload"}
        assert json.loads(r["payload"]) is not None
        assert seed.SEED_MARK in r["payload"]     # tagged so --reset targets exactly it


def test_rolled_back_slot_restored_and_healed_slot_fixed():
    plan = seed.build_seed(_FIXED)
    by_id = {s.id: s for s in plan.slots}
    rolled = [s for s in plan.snapshots if s["rolled_back_at"] is not None]
    assert len(rolled) == 1
    assert rolled[0]["before"]["url"] != rolled[0]["after"]["url"]   # a real fix was attempted
    assert by_id[rolled[0]["slot_id"]].url == rolled[0]["before"]["url"]   # RESTORED
    healed = [s for s in plan.snapshots if s["rolled_back_at"] is None][0]
    assert by_id[healed["slot_id"]].url == healed["after"]["url"]    # persisted FIXED
    assert by_id[healed["slot_id"]].url != healed["before"]["url"]


def test_summary_is_order_independent():
    plan = seed.build_seed(_FIXED)
    s = plan.summary()
    assert s["by_site"] == dict(Counter(sc.site for sc in plan.scenarios))
    assert s["slots"] == len(plan.scenarios) == 41
    assert s["human_approved"] == sum(1 for sc in plan.scenarios if sc.human == "approve")
    assert s["human_rejected"] == sum(1 for sc in plan.scenarios if sc.human == "reject")


def test_summary_is_honestly_labelled_replay():
    s = seed.build_seed(_FIXED).summary()
    assert s["seed_mark"] == seed.SEED_MARK
    assert "replay" in s["kind"].lower()
    assert "NOT" in s["kind"]                     # not live scan / not real Bedrock


# --------------------------------------------------------------------------- #
# FAKE-CONN writer — SQL contract, idempotency, reset, guard
# --------------------------------------------------------------------------- #
def test_write_seed_persists_every_table():
    conn = _conn()
    plan = seed.build_seed(_FIXED)
    out = seed.write_seed(conn, plan, ensure=False)
    assert len(conn.slots) == 41
    assert len(conn.decisions) == 42
    assert len(conn.checks) == 41 + 38            # scan + verify
    assert len(conn.snapshots) == 38
    assert len(conn.audit) == 133
    assert out["slots"] == 41 and out["human_approved"] == 38   # returns plan.summary()


def test_write_seed_decision_status_split():
    conn = _conn()
    seed.write_seed(conn, seed.build_seed(_FIXED), ensure=False)
    statuses = Counter(v[3] for v in conn.decisions.values())
    assert statuses["applied"] == 37
    assert statuses["rejected"] == 4
    assert statuses["pending"] == 1


def test_write_seed_is_idempotent():
    conn = _conn()
    plan = seed.build_seed(_FIXED)
    seed.write_seed(conn, plan, ensure=False)
    seed.write_seed(conn, plan, ensure=False)     # re-run: delete-then-insert, no dupes
    assert len(conn.slots) == 41
    assert len(conn.decisions) == 42
    assert len(conn.checks) == 79
    assert len(conn.snapshots) == 38
    assert len(conn.audit) == 133


def test_seed_stats_reports_db_footprint():
    conn = _conn()
    seed.write_seed(conn, seed.build_seed(_FIXED), ensure=False)
    st = seed.seed_stats(conn)
    assert st["slots"] == 41
    assert st["decisions"] == 42
    assert st["by_status"] == {"applied": 37, "rejected": 4, "pending": 1}
    assert st["slot_checks"] == 79
    assert st["write_snapshots"] == 38
    assert st["rolled_back_snapshots"] == 1
    assert st["audit_rows"] == 133


def test_reset_seed_removes_exactly_the_seed():
    conn = _conn()
    plan = seed.build_seed(_FIXED)
    seed.write_seed(conn, plan, ensure=False)
    deleted = seed.reset_seed(conn, plan=plan)
    assert deleted == {"write_snapshots": 38, "slot_checks": 79, "decisions": 42,
                       "link_slots": 41, "audit_log": 133}
    assert conn.slots == {} and conn.decisions == {}
    assert conn.checks == [] and conn.snapshots == [] and conn.audit == []


def test_reset_seed_leaves_unrelated_rows_untouched():
    conn = _conn()
    plan = seed.build_seed(_FIXED)
    seed.write_seed(conn, plan, ensure=False)
    conn.slots["real:scan:1"] = ("real:scan:1", "aethelgem")   # a non-seed row
    conn.audit.append(("ts", "scanner", "tool_result", '{"seed": null}'))  # no SEED_MARK
    seed.reset_seed(conn, plan=plan)
    assert "real:scan:1" in conn.slots            # real scanned data survives the reset
    assert len(conn.audit) == 1


def test_write_seed_refuses_forbidden_host():
    conn = _conn()
    os.environ["EVERLINK_FORBIDDEN_HOSTS"] = "ep-everlink-test.aws.neon.tech"
    try:
        raised = False
        try:
            seed.write_seed(conn, seed.build_seed(_FIXED), ensure=False)
        except ProductionWriteRefused:
            raised = True
        assert raised                             # Blue Neon / source-host guard fires first
        assert conn.slots == {}                   # nothing was written
    finally:
        _clear_deny_env()


def test_reset_seed_refuses_forbidden_host():
    conn = _conn()
    os.environ["EVERLINK_FORBIDDEN_HOSTS"] = "ep-everlink-test.aws.neon.tech"
    try:
        raised = False
        try:
            seed.reset_seed(conn, plan=seed.build_seed(_FIXED))
        except ProductionWriteRefused:
            raised = True
        assert raised
    finally:
        _clear_deny_env()


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
