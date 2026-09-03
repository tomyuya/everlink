"""Offline tests for the write-safety guard in everlink.db (no DB connection).

Verifies that EverLink refuses schema/write against any host derived from the
source-site DSNs or the explicit deny-list, while allowing its own DB host.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from everlink.db import (  # noqa: E402
    ProductionWriteRefused, _assert_writable, _forbidden_fragments, _host_of,
)

SRC = "AETHELGEM_DATABASE_URL"
OWN = "EVERLINK_DATABASE_URL"
DENY = "EVERLINK_FORBIDDEN_HOSTS"


def _setenv(**kv):
    for k, v in kv.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


def test_host_of():
    assert _host_of("postgresql://u:p@ep-xyz-pooler.aws.neon.tech/db?ssl=x") == \
        "ep-xyz-pooler.aws.neon.tech"
    assert _host_of("") == ""
    assert _host_of("not-a-url") == ""


def test_denylist_derives_from_source_env():
    _setenv(**{SRC: "postgresql://u:p@ep-src-pooler.aws.neon.tech/neondb", DENY: None})
    frags = _forbidden_fragments()
    assert "ep-src-pooler.aws.neon.tech" in frags


def test_refuses_write_to_source_host():
    _setenv(**{SRC: "postgresql://u:p@ep-src-pooler.aws.neon.tech/neondb", DENY: None})
    try:
        _assert_writable("postgresql://u:p@ep-src-pooler.aws.neon.tech/everlink")
        raise AssertionError("expected ProductionWriteRefused")
    except ProductionWriteRefused:
        pass


def test_refuses_write_to_explicit_deny_fragment():
    _setenv(**{SRC: None, DENY: "ep-secret-pooler.aws.neon.tech"})
    try:
        _assert_writable("postgresql://u:p@ep-secret-pooler.aws.neon.tech/everlink")
        raise AssertionError("expected ProductionWriteRefused")
    except ProductionWriteRefused:
        pass


def test_allows_write_to_own_host():
    _setenv(**{SRC: "postgresql://u:p@ep-src-pooler.aws.neon.tech/neondb",
               DENY: None,
               OWN: "postgresql://u:p@ep-everlink-pooler.aws.neon.tech/everlink"})
    # different host from the source => allowed (no raise)
    _assert_writable(os.environ[OWN])


# --------------------------------------------------------------------------- #
# cli._persist regression — the scan's DB write path MUST pass conn to insert_slot_check
# --------------------------------------------------------------------------- #
class _RecInfo:
    dsn = "postgresql://u@ep-everlink-test.aws.neon.tech/everlink"


class _RecCursor:
    def __init__(self, conn):
        self._c = conn
        self.rowcount = 0

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def executemany(self, sql, rows):
        for r in rows:
            self.execute(sql, r)

    def execute(self, sql, params=None):
        self._c.log.append((" ".join(sql.split()), params))
        self.rowcount = 1


class _RecConn:
    def __init__(self):
        self.log: list = []
        self.info = _RecInfo()

    def cursor(self):
        return _RecCursor(self)

    def commit(self):
        pass

    def close(self):
        pass


def test_persist_passes_conn_to_insert_slot_check():
    """Regression for the nightly-scan crash: ``cli._persist`` must call
    ``insert_slot_check(conn, check)``. Calling it with only the CheckResult raised
    ``TypeError: insert_slot_check() missing 1 required positional argument: 'result'``
    and failed the scan step for any site that actually had checks to persist (the
    first-party sites yield 0 slots, so only a generic scan exposed it)."""
    from everlink import cli, db
    from everlink.agents import ScanReport
    from everlink.model import CheckResult, LinkSlot

    _setenv(**{SRC: None, DENY: None,
               OWN: "postgresql://u@ep-everlink-test.aws.neon.tech/everlink"})
    conn = _RecConn()
    real_connect, real_schema = db.connect, db.ensure_schema
    db.connect = lambda dsn: conn
    db.ensure_schema = lambda c: None
    try:
        report = ScanReport(
            source="x", scanned=1, judge_backend="stub",
            slots=[LinkSlot(id="gen-x", site="news.ycombinator.com", article_id="",
                            article_title="", block_id="", block_type="",
                            slot_type="reference", url="https://example.com/dead")],
            checks=[CheckResult(slot_id="gen-x", l1_status=200, final_verdict="dead")])
        written, enqueued = cli._persist(report, [], None)
    finally:
        db.connect, db.ensure_schema = real_connect, real_schema
        for k in (SRC, DENY, OWN):
            os.environ.pop(k, None)

    assert written == 1 and enqueued == 0
    order = [s.split()[2] for s, _ in conn.log if s.startswith("INSERT INTO")]
    assert "link_slots" in order and "slot_checks" in order, conn.log
    assert order.index("link_slots") < order.index("slot_checks"), \
        f"link_slots (FK parent) must be written before slot_checks: {order}"


ALL = [v for k, v in sorted(globals().items()) if k.startswith("test_")]


if __name__ == "__main__":
    failed = 0
    for fn in ALL:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL {fn.__name__}: {e}")
    # cleanup
    for k in (SRC, OWN, DENY):
        os.environ.pop(k, None)
    print(f"\n{len(ALL)-failed}/{len(ALL)} passed")
    sys.exit(1 if failed else 0)
