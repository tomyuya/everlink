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
