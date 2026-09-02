"""Integration tests: fixture server + L1 (probes) + L2 (l2) end-to-end.

Spins up the fixture server on an ephemeral port and drives it with the real
L1/L2 code paths. The key assertion is the soft-404: L1 reports 'healthy'
(HTTP 200) while L2 catches 'unavailable' — this is exactly why the detection
pyramid needs both layers (spec §4.1).
"""
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from everlink.fixtures import make_server  # noqa: E402
from everlink.l2 import probe_l2  # noqa: E402
from everlink.probes import probe_url  # noqa: E402

_server = None
_thread = None
_base = None


def setup_module(module):  # noqa: ARG001
    global _server, _thread, _base
    _server = make_server(port=0)          # ephemeral port
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


# --- L1 ---------------------------------------------------------------------
def test_l1_dead_404():
    r = probe_url(f"{_base}/dead", "s1")
    assert r.final_verdict == "dead" and r.l1_status == 404


def test_l1_ok_is_healthy():
    r = probe_url(f"{_base}/ok", "s2")
    assert r.final_verdict == "healthy" and r.l1_status == 200


def test_l1_program_ended_via_dropped_tag():
    r = probe_url(f"{_base}/affiliate/deal?tag=everlink-20", "s3")
    assert r.final_verdict == "program_ended"
    assert len(r.redirect_chain) >= 2      # captured the hop


# --- L2 ---------------------------------------------------------------------
def test_l2_ok_with_price():
    r = probe_l2(f"{_base}/ok", engine="httpx")
    assert r.verdict == "ok" and r.extracted_price == "$328.00"


def test_l2_unavailable():
    assert probe_l2(f"{_base}/unavailable", engine="httpx").verdict == "unavailable"


def test_l2_blocked_botwall():
    assert probe_l2(f"{_base}/blocked", engine="httpx").verdict == "blocked"


def test_l2_dead():
    assert probe_l2(f"{_base}/dead", engine="httpx").verdict == "dead"


def test_l2_price_anomaly_with_claim():
    r = probe_l2(f"{_base}/price-anomaly", claimed_price="$328.00", engine="httpx")
    assert r.verdict == "price_anomaly"    # $599 >= 1.5 x $328


# --- the pyramid payoff -----------------------------------------------------
def test_soft_404_l1_healthy_but_l2_unavailable():
    l1 = probe_url(f"{_base}/unavailable", "s4")
    l2 = probe_l2(f"{_base}/unavailable", engine="httpx")
    assert l1.final_verdict == "healthy"   # HTTP 200 -> L1 can only say reachable
    assert l2.verdict == "unavailable"     # L2 catches the dead offer


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
