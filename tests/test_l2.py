"""Offline tests for L2 page parsing (everlink.l2). Pure HTML -> verdict."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from everlink.l2 import (  # noqa: E402
    extract_price, extract_title, parse_product_page, signal_regions,
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


# --- False-positive regressions (real production incidents) ---------------- #
# dec-43dcbc9770: a LIVE Amazon PDP was judged "dead" because one customer
# review far below the fold said "doesn't exist". A page that renders the
# product shell (#productTitle) must NEVER be prose-judged dead/blocked,
# whatever user-generated content (reviews / Q&A / JS strings) happens to say.
_PAD = "<p>Product description filler text. " * 120 + "</p>"  # >2000 chars, keeps UGC out of the availability window
NOISY_HEALTHY_PDP = (
    '<html><head><title>Amazon.com: Smart Projector with WiFi 6</title></head><body>'
    '<span id="productTitle">Smart Projector, 4K Support, Auto Focus, Dolby Audio</span>'
    '<span class="a-offscreen">$129.99</span>'
    '<div id="availability">In Stock.</div>'
    '<button>Add to Cart</button>'
    + _PAD +
    '<div id="reviews">'
    "<p>One star. This listing doesn't exist anymore, page not found on my bookmark.</p>"
    "<p>Seller said the item has been removed and is out of stock for good.</p>"
    "<p>Got a robot check / captcha wall when opening on my phone.</p>"
    '</div>'
    '<script>var s = "404 validatecaptcha unusual traffic";</script>'
    '</body></html>'
)
# A genuine dead page has NO product shell — the phrase is the whole story.
SHELL_LESS_DEAD = (
    '<html><head><title>Amazon.com: Page Not Found</title></head><body>'
    "<h1>Sorry! We couldn't find that page.</h1>"
    "<p>The link you followed doesn't exist or has been removed.</p>"
    '</body></html>'
)
# Shell present but a STRUCTURAL out-of-stock marker still wins (ids never
# appear in prose, so this signal is safe even on a product page).
SHELL_OUTOFSTOCK = (
    '<html><body><span id="productTitle">Some Product</span>'
    '<span class="a-offscreen">$10.00</span>'
    '<div id="outOfStock">Currently unavailable.</div>'
    '</body></html>'
)
# A LIVE PDP that merely *mentions* the concatenated token "outofstock" in JS
# config, swatch data-attributes and CSS class names — with the buybox saying
# "In Stock" and NO structural id="outOfStock". A whole-page substring match on
# the bare token false-positived offer_changed on real Amazon cards (the
# aethelgem flippers) whenever bot-mitigation served a noisy-but-live page.
SHELL_OUTOFSTOCK_NOISE = (
    '<html><head><title>Amazon.com: Rose-Cut Diamond Stud Earrings</title></head><body>'
    '<span id="productTitle">Rose-Cut Diamond Stud Earrings, 14k White Gold</span>'
    '<span class="a-offscreen">$249.00</span>'
    '<div id="availability">In Stock.</div>'
    '<button>Add to Cart</button>'
    + _PAD +
    '<script>var P = {"outOfStockThreshold":0,"isOutOfStock":false,"outofstockRedirect":true};</script>'
    '<div id="similarities"><ul>'
    '<li class="swatch" data-outofstock="1">Alternative A</li>'
    '<li class="outofstock-hidden">Alternative B</li>'
    '</ul></div>'
    '</body></html>'
)


def test_noisy_healthy_pdp_is_ok_not_dead():
    # The dec-43dcbc9770 regression: UGC poison must not flip a live PDP to dead.
    r = parse_product_page(NOISY_HEALTHY_PDP)
    assert r.verdict == "ok", f"live PDP misjudged as {r.verdict}: {r.evidence}"
    assert r.title and "Smart Projector" in r.title
    assert r.extracted_price == "$129.99"


def test_signal_regions_detects_shell():
    regions = signal_regions(NOISY_HEALTHY_PDP)
    assert regions["shell"] is True
    assert "smart projector" in regions["title"]
    # the review prose is real, but the shell flag is what neutralizes it
    assert regions["shell"] and "doesn't exist" not in regions["early"][:200]


def test_shell_less_dead_page_still_dead():
    # No product shell => the not-found prose is the page's actual message.
    r = parse_product_page(SHELL_LESS_DEAD)
    assert r.verdict == "dead"


def test_structural_outofstock_beats_shell():
    # A product page can still be genuinely unavailable via a structural marker.
    r = parse_product_page(SHELL_OUTOFSTOCK)
    assert r.verdict == "unavailable"
    assert "structural marker" in r.evidence


def test_shell_page_with_outofstock_noise_is_ok():
    # The aethelgem-flipper regression: a LIVE PDP whose buybox says "In Stock"
    # must NOT be judged unavailable just because the bare token "outofstock"
    # appears somewhere in its JS/related-items markup. Only the STRUCTURAL
    # id="outOfStock" element (or an availability-region phrase) may assert it.
    r = parse_product_page(SHELL_OUTOFSTOCK_NOISE)
    assert r.verdict == "ok", f"live PDP misjudged as {r.verdict}: {r.evidence}"
    assert r.extracted_price == "$249.00"


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
