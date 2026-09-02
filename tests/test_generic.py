"""Tests for the generic read-only adapter (everlink.generic).

Two layers:
  * PURE offline tests of parse_sitemap / absolutize_url / extract_links /
    classify_slot_type (no network).
  * Integration tests that spin up the fixture server and crawl its /blog/post*,
    /sitemap.xml and /sitemap-index.xml — read-only, nothing written back.
"""
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from everlink.fixtures import make_server  # noqa: E402
from everlink.generic import (  # noqa: E402
    absolutize_url, classify_slot_type, extract_links, extract_slots_generic,
    is_sitemap_index, parse_sitemap, slots_from_page, slots_from_sitemap,
)

_server = None
_thread = None
_base = None


def setup_module(module):  # noqa: ARG001
    global _server, _thread, _base
    _server = make_server(port=0)
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


# ---- pure: sitemap parsing -------------------------------------------------
def test_parse_sitemap_urlset():
    xml = ('<?xml version="1.0"?><urlset xmlns="s">'
           '<url><loc>https://a.com/p1</loc></url>'
           '<url><loc>https://a.com/p2</loc></url></urlset>')
    assert parse_sitemap(xml) == ["https://a.com/p1", "https://a.com/p2"]
    assert not is_sitemap_index(xml)


def test_parse_sitemap_index_detected():
    xml = ('<sitemapindex xmlns="s"><sitemap><loc>https://a.com/s1.xml</loc>'
           '</sitemap></sitemapindex>')
    assert is_sitemap_index(xml)
    assert parse_sitemap(xml) == ["https://a.com/s1.xml"]


def test_parse_sitemap_unescapes_ampersand():
    xml = '<urlset><url><loc>https://a.com/p?x=1&amp;y=2</loc></url></urlset>'
    assert parse_sitemap(xml) == ["https://a.com/p?x=1&y=2"]


# ---- pure: url handling ----------------------------------------------------
def test_absolutize_url():
    assert absolutize_url("/about", "https://a.com/blog/p") == "https://a.com/about"
    assert absolutize_url("https://b.com/x", "https://a.com/p") == "https://b.com/x"
    assert absolutize_url("https://a.com/p#frag", "https://a.com/") == "https://a.com/p"
    assert absolutize_url("#top", "https://a.com/p") is None
    assert absolutize_url("mailto:x@y.com", "https://a.com/p") is None
    assert absolutize_url("tel:+123", "https://a.com/p") is None
    assert absolutize_url("javascript:void(0)", "https://a.com/p") is None
    assert absolutize_url("", "https://a.com/p") is None


def test_extract_links_and_title():
    html = ('<html><head><title>My Post</title></head><body>'
            '<a href="https://amzn.to/x">Buy</a>'
            '<a href="/local">Local</a>'
            '<a href="mailto:a@b.c">mail</a></body></html>')
    title, links = extract_links(html, "https://a.com/blog")
    assert title == "My Post"
    urls = [u for u, _ in links]
    assert "https://amzn.to/x" in urls
    assert "https://a.com/local" in urls          # relative -> absolute
    assert all(not u.startswith("mailto:") for u in urls)


def test_classify_slot_type():
    assert classify_slot_type("https://a.com/x", "a.com") == "internal"
    assert classify_slot_type("https://www.a.com/x", "a.com") == "internal"
    assert classify_slot_type("https://amazon.com/dp/1?tag=foo-20", "a.com") == "commercial"
    assert classify_slot_type("https://b.com/x?aff=1", "a.com") == "commercial"
    assert classify_slot_type("https://en.wikipedia.org/wiki/X", "a.com") == "reference"


# ---- integration: crawl the fixture server (read-only) ---------------------
def test_slots_from_page_external_only():
    slots = slots_from_page(f"{_base}/blog/post1")
    urls = {s.url for s in slots}
    types = {s.url: s.slot_type for s in slots}
    assert any("amazon.com" in u for u in urls)
    assert any("wikipedia.org" in u for u in urls)
    # internal /about excluded by default; mailto / #fragment never extracted
    assert not any(u.endswith("/about") for u in urls)
    assert not any(u.startswith("mailto:") for u in urls)
    amz = next(u for u in urls if "amazon.com" in u)
    assert types[amz] == "commercial"
    # page title + anchor text captured for the Judge's context
    assert slots[0].article_title and "Headphones" in slots[0].article_title
    assert all(s.anchor_text for s in slots)


def test_slots_from_page_include_internal():
    slots = slots_from_page(f"{_base}/blog/post1", include_internal=True)
    assert any(u.endswith("/about") for u in {s.url for s in slots})


def test_slots_from_sitemap_crawls_pages():
    slots = slots_from_sitemap(f"{_base}/sitemap.xml", rate_delay=0)
    types = {s.slot_type for s in slots}
    blob = " ".join(s.url for s in slots)
    assert "amazon.com" in blob and "aliexpress" in blob and "wikipedia.org" in blob
    assert "commercial" in types and "reference" in types


def test_slots_from_sitemap_index_expands():
    slots = slots_from_sitemap(f"{_base}/sitemap-index.xml", rate_delay=0)
    assert any("amazon.com" in s.url for s in slots)   # via sub-sitemap -> post1


def test_extract_slots_generic_autodetect():
    assert extract_slots_generic(f"{_base}/sitemap.xml", rate_delay=0)          # sitemap
    pg = extract_slots_generic(f"{_base}/blog/post1")                            # page
    assert any("amazon.com" in s.url for s in pg)
    lst = extract_slots_generic([f"{_base}/blog/post1", f"{_base}/blog/post2"],  # list
                                rate_delay=0)
    assert any("amazon.com" in s.url for s in lst)
    assert any("aliexpress" in s.url for s in lst)


def test_slot_ids_unique_and_namespaced():
    slots = slots_from_sitemap(f"{_base}/sitemap.xml", rate_delay=0)
    ids = [s.id for s in slots]
    assert len(ids) == len(set(ids))
    assert all(i.startswith("gen-") for i in ids)


def test_generic_adapter_is_read_only():
    # The adapter only issues GETs to *discover* links and exposes no write path;
    # returned slots are plain in-memory LinkSlot objects (status active, unlocked).
    slots = slots_from_page(f"{_base}/blog/post1")
    assert slots and all(s.status == "active" and s.protected == 0 for s in slots)


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
