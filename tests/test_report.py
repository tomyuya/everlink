"""Weekly-report tests (spec §4.1 '... -> 周报' / §4.2 汇报 / board /report mirror).

Offline and DB-free. Two things are proven:
  * ``report.build_weekly_report`` MIRRORS the board's ``weeklyStats`` SQL — a fake
    psycopg ``conn`` scripts the five aggregate result-sets and we assert the report
    folds them exactly like board/lib/queries.ts (null action -> "unknown",
    decisions_created = sum of by_status, healed/slots from the applied aggregate).
  * ``notify.compose_weekly_report`` renders those numbers honestly — the four headline
    stats + the by-status / by-action / audit breakdowns + a link to the board /report,
    and an EMPTY window says "Nothing to report yet" instead of inventing activity.

HONESTY: the fake conn scripts the rows; it does not exercise a real Postgres. The live
digest over EverLink's own DB is verified separately (see the pe3 live check), and a
green suite here never claims an email/Telegram was actually delivered.
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from everlink import notify, report  # noqa: E402


# --------------------------------------------------------------------------- #
# fake psycopg conn scripting the five weeklyStats aggregates
# --------------------------------------------------------------------------- #
class _FakeCursor:
    def __init__(self, conn):
        self._conn = conn
        self._rows: list = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self._conn.log.append((sql, params))
        self._rows = self._conn.respond(" ".join(sql.split()))

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None


class _FakeConn:
    def __init__(self, *, by_status=None, by_action=None, audit=None,
                 healed=(0, 0), decided=0):
        self.log: list = []
        self.by_status = by_status or []
        self.by_action = by_action or []
        self.audit = audit or []
        self.healed = healed
        self.decided = decided

    def cursor(self):
        return _FakeCursor(self)

    def respond(self, s):
        # dispatch on the SAME five query shapes build_weekly_report issues
        if s.startswith("SELECT status, count(*) FROM decisions"):
            return self.by_status
        if "proposal::jsonb ->> 'action'" in s:
            return self.by_action
        if s.startswith("SELECT event, count(*) FROM audit_log"):
            return self.audit
        if "jsonb_array_length(affected_slot_ids" in s:
            return [self.healed]
        if s.startswith("SELECT count(*) FROM decisions WHERE decided_at"):
            return [(self.decided,)]
        return []


def _flat(text: str) -> str:
    """Collapse whitespace runs so stat-line assertions are padding-independent."""
    return re.sub(r"\s+", " ", text)


# --------------------------------------------------------------------------- #
# build_weekly_report — the board weeklyStats mirror
# --------------------------------------------------------------------------- #
def test_build_weekly_report_mirrors_the_five_aggregates():
    conn = _FakeConn(
        by_status=[("applied", 12), ("rejected", 3), ("pending", 2)],
        by_action=[("REPLACE_URL", 10), ("ESCALATE_HUMAN", 7)],
        audit=[("write", 12), ("verify", 12), ("rollback", 1)],
        healed=(12, 18), decided=15)
    r = report.build_weekly_report(conn, days=7)
    assert r.window_days == 7
    assert r.by_status == {"applied": 12, "rejected": 3, "pending": 2}
    assert r.by_action == {"REPLACE_URL": 10, "ESCALATE_HUMAN": 7}
    assert r.audit_events == {"write": 12, "verify": 12, "rollback": 1}
    assert r.links_healed == 12
    assert r.slots_affected_by_applied == 18
    assert r.decisions_created == 17                    # sum of by_status, mirrors the board
    assert r.decisions_decided == 15
    assert r.generated_at                               # ISO timestamp set
    assert r.is_empty is False
    assert len(conn.log) == 5                           # exactly the five aggregates ran


def test_build_weekly_report_null_action_becomes_unknown():
    conn = _FakeConn(by_status=[("pending", 4)], by_action=[(None, 4)])
    r = report.build_weekly_report(conn, days=30)
    assert r.by_action == {"unknown": 4}                # board's String(r[key] ?? "unknown")
    assert r.window_days == 30


def test_build_weekly_report_empty_window_is_honest():
    conn = _FakeConn()                                  # no rows anywhere
    r = report.build_weekly_report(conn)
    assert r.decisions_created == 0 and r.links_healed == 0 and r.audit_events == {}
    assert r.slots_affected_by_applied == 0 and r.decisions_decided == 0
    assert r.is_empty is True


# --------------------------------------------------------------------------- #
# WeeklyReport.is_empty + _sorted_counts (pure)
# --------------------------------------------------------------------------- #
def test_weekly_report_is_empty_logic():
    assert notify.WeeklyReport().is_empty is True
    assert notify.WeeklyReport(decisions_created=1).is_empty is False
    assert notify.WeeklyReport(links_healed=1).is_empty is False
    assert notify.WeeklyReport(audit_events={"write": 1}).is_empty is False


def test_sorted_counts_orders_by_value_desc_then_key():
    assert notify._sorted_counts({"a": 1, "b": 5, "c": 3}) == [("b", 5), ("c", 3), ("a", 1)]
    assert notify._sorted_counts({"z": 2, "y": 2}) == [("y", 2), ("z", 2)]


# --------------------------------------------------------------------------- #
# compose_weekly_report — honest rendering
# --------------------------------------------------------------------------- #
def test_compose_weekly_report_empty_says_nothing_to_report():
    note = notify.compose_weekly_report(notify.WeeklyReport(window_days=7),
                                        "https://board.example")
    assert note.subject.startswith("[EverLink] Weekly report")
    assert "Nothing to report yet" in note.text
    assert "Links healed" not in note.text              # no invented stats
    assert "Nothing to report yet" in note.html


def test_compose_weekly_report_renders_stats_and_breakdowns():
    r = notify.WeeklyReport(
        window_days=7, generated_at="2026-09-09T00:00:00+00:00",
        by_status={"applied": 12, "rejected": 3},
        by_action={"REPLACE_URL": 10, "ESCALATE_HUMAN": 5},
        audit_events={"write": 12, "verify": 12, "rollback": 1},
        links_healed=12, slots_affected_by_applied=18,
        decisions_created=15, decisions_decided=15)
    note = notify.compose_weekly_report(r, "https://board.example")
    assert "12 link(s) healed" in note.subject
    flat = _flat(note.text)
    assert "Links healed : 12" in flat
    assert "Slots fixed : 18" in flat
    assert "Decisions created : 15" in flat
    assert "Decisions decided : 15" in flat
    assert "Replace URL" in note.text and "Escalate to human" in note.text   # action labels
    assert "rollback 1" in note.text                                          # audit breakdown
    assert "https://board.example/report" in note.text                       # links to the board
    assert "https://board.example/report" in note.html
    assert "You approve decisions, not links." in note.text


def test_compose_weekly_report_without_board_url_is_honest():
    r = notify.WeeklyReport(links_healed=1, by_status={"applied": 1}, decisions_created=1)
    note = notify.compose_weekly_report(r, "")
    assert "EVERLINK_BOARD_URL not set" in note.text


def test_notifier_push_weekly_report_delivers_composed_note():
    sent: list = []

    def fake_sender(url, headers, body):
        sent.append((url, body))
        return 200, '{"id":"x"}'

    cfg = notify.NotifyConfig(resend_api_key="k", resend_from="a@b.c",
                              notify_emails=["op@x.com"], board_url="https://board.example")
    n = notify.Notifier(config=cfg, sender=fake_sender)
    r = notify.WeeklyReport(links_healed=3, by_status={"applied": 3}, decisions_created=3)
    results = n.push_weekly_report(r)
    assert any(res.status == "sent" for res in results)
    assert sent and "Weekly report" in sent[0][1]["subject"]


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
