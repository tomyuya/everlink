"""Offline tests for L2 page parsing (everlink.l2). Pure HTML -> verdict."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from everlink.l2 import (  # noqa: E402
    extract_price, extract_title, parse_product_page,
)

OK_HTML = """
<html><head><title>Amazon | Sony</title></head><body>
<span id="productTitle">Sony WH-1000XM5 Wireless Headphones</span>
<span class="a-offscreen">$328.00</span>
<button>Add to Cart</button>
</body></html>
"""
UNAVAIL_HTML = """
<html><body><span id="productTitle">Some Product</span>
<div id="outOfStock">Currently unavailable. We don't know when or if this item will be back in stock.</div>
</body></html>
"""
DEAD_HTML = "<html><body><h1>Page Not Found</h1>Sorry! We couldn't find that page.</body></html>"
BLOCKED_HTML = "<html><body>Robot Check Enter the characters you see below to continue.</body></html>"
EMPTY_HTML = "<html><body><div>lorem ipsum nothing useful</div></body></html>"


def test_ok_page_is_ok():
    r = parse_product_page(OK_HTML)
    assert r.verdict == "ok"
    assert r.title and "Sony" in r.title
    assert r.extracted_price == "$328.00"


def test_unavailable_page():
    r = parse_product_page(UNAVAIL_HTML)
    assert r.verdict == "unavailable"
    assert "unavailable" in r.evidence.lower()


def test_dead_page():
    r = parse_product_page(DEAD_HTML)
    assert r.verdict == "dead"


def test_blocked_botwall():
    r = parse_product_page(BLOCKED_HTML)
    assert r.verdict == "blocked"
    assert r.matched_signal is not None


def test_no_signal_refuses_to_assert_ok():
    # 200 body that is neither a product nor a known error => blocked (recheck),
    # never a fabricated 'ok'.
    r = parse_product_page(EMPTY_HTML)
    assert r.verdict == "blocked"


def test_price_anomaly_only_with_claim():
    html = OK_HTML.replace("$328.00", "$400.00")
    # no claim -> just 'ok' with the live price surfaced for the Judge
    assert parse_product_page(html).verdict == "ok"
    # claim $200, live $400 >= 1.5x -> price_anomaly
    r = parse_product_page(html, claimed_price="$200.00")
    assert r.verdict == "price_anomaly"
    assert r.extracted_price == "$400.00"


def test_price_within_tolerance_is_ok():
    r = parse_product_page(OK_HTML, claimed_price="$300.00")  # 328 < 300*1.5
    assert r.verdict == "ok"


def test_block_beats_dead_beats_unavailable():
    # a page carrying both a bot-wall and a 404 phrase resolves to blocked
    mixed = BLOCKED_HTML + DEAD_HTML
    assert parse_product_page(mixed).verdict == "blocked"


def test_extract_helpers():
    assert extract_price(OK_HTML) == "$328.00"
    assert extract_title(OK_HTML) and "Sony" in extract_title(OK_HTML)
    assert extract_price("<html>no money here</html>") is None


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
