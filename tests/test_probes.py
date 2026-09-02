"""Offline unit tests for L1 classification (no network, no DB).

Covers the honest-verdict rules from spec §4.1: dead / blocked->recheck /
program-ended via redirect-chain analysis / healthy only when provably reachable.
Runnable via `pytest` or directly `python tests/test_probes.py`.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from everlink.model import RedirectHop  # noqa: E402
from everlink.probes import analyze_chain, classify_l1  # noqa: E402


def test_dead_status():
    assert classify_l1(404, [RedirectHop(url="https://x/dp/A", status=404)], "https://x/dp/A")[0] == "dead"
    assert classify_l1(410, [], "https://x/")[0] == "dead"
    assert classify_l1(451, [], "https://x/")[0] == "dead"


def test_blocked_is_recheck_not_dead():
    # Amazon/retailers frequently 403/503 headless clients => never guess dead.
    for st in (403, 429, 500, 503):
        v, _ = classify_l1(st, [RedirectHop(url="https://amazon.com/dp/A", status=st)],
                           "https://amazon.com/dp/A")
        assert v == "needs_human_recheck", st


def test_transport_error_is_recheck():
    v, _ = classify_l1(None, [], "https://x/", error="ConnectTimeout: ...")
    assert v == "needs_human_recheck"


def test_plain_200_is_healthy():
    v, _ = classify_l1(200, [RedirectHop(url="https://x/dp/A", status=200)], "https://x/dp/A")
    assert v == "healthy"


def test_amazon_tag_retained_is_healthy():
    url = "https://www.amazon.com/dp/B0C73?tag=foo-20"
    chain = [RedirectHop(url=url, status=200)]
    hint, _ = analyze_chain(url, chain)
    assert hint is None
    assert classify_l1(200, chain, url)[0] == "healthy"


def test_network_self_redirect_is_program_ended():
    orig = "https://pjtra.com/click/abc?affsub=1"
    chain = [
        RedirectHop(url=orig, status=302),
        RedirectHop(url="https://www.pjtra.com/expired", status=200),
    ]
    hint, ev = analyze_chain(orig, chain)
    assert hint == "program_ended", (hint, ev)
    assert classify_l1(200, chain, orig)[0] == "program_ended"


def test_tracking_lost_landing_homepage_is_program_ended():
    orig = "https://partner.example.com/click?id=9&tag=abc-20"
    chain = [
        RedirectHop(url=orig, status=302),
        RedirectHop(url="https://advertiser.example.com/", status=200),
    ]
    hint, ev = analyze_chain(orig, chain)
    assert hint == "program_ended", (hint, ev)
    assert "homepage" in (ev or "")


def test_tracking_lost_but_deep_link_is_only_evidence():
    # Lost params but landed on a real product path => weaker: evidence, not ended.
    orig = "https://x.com/click?tag=abc-20"
    chain = [
        RedirectHop(url=orig, status=302),
        RedirectHop(url="https://shop.com/product/123", status=200),
    ]
    hint, ev = analyze_chain(orig, chain)
    assert hint is None
    assert ev and "tracking params" in ev
    assert classify_l1(200, chain, orig)[0] == "healthy"


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
    print(f"\n{len(ALL)-failed}/{len(ALL)} passed")
    sys.exit(1 if failed else 0)
