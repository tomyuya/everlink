"""Fixture server: deterministic replay pages for Evals + demo (spec §4.1/§8).

Serves local snapshots of every link-rot scenario so the L1+L2 pipeline and the
Judge can be exercised — and the demo can inject faults — without hitting live
merchant sites. The demo labels these "replay snapshot" (spec §9 extra breaker).

Scenarios (path -> behavior):
  /ok                    200 live product page              -> L2 ok
  /unavailable           200 "Currently unavailable"        -> L2 unavailable (soft-404)
  /price-anomaly         200 price jumped                   -> L2 price_anomaly (w/ claim)
  /blocked               200 bot-wall / captcha             -> L2 blocked -> recheck
  /dead                  404 not-found                      -> L1/L2 dead
  /disclosure-dead       404 (slot carries disclosure kw)   -> DisclosurePolicy protects
  /affiliate/deal?tag=.. 302 -> /  (tracking tag dropped)   -> L1 program_ended
  /                      200 homepage (redirect landing)

Run standalone:  python scripts/fixture_server.py [--port 8787]
Use in tests:    srv = make_server(port=0); thread it; srv.server_address[1].
"""
from __future__ import annotations

import argparse
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

FIXTURE_PORT_DEFAULT = 8787
HOST = "127.0.0.1"

_PAGE = """<!doctype html><html lang="en"><head><title>{title}</title></head>
<body>{body}</body></html>"""

OK_HTML = _PAGE.format(
    title="Amazon | Sony WH-1000XM5",
    body=('<div id="dp-container"><span id="productTitle">Sony WH-1000XM5 Wireless '
          'Noise-Canceling Headphones</span><span class="a-price"><span class="a-offscreen">'
          '$328.00</span></span><div id="availability">In Stock</div>'
          '<button id="add-to-cart">Add to Cart</button></div>'),
)
UNAVAILABLE_HTML = _PAGE.format(
    title="Amazon | Product",
    body=('<div id="dp-container"><span id="productTitle">Discontinued Gadget</span>'
          '<div id="outOfStock">Currently unavailable. We don\'t know when or if this '
          'item will be back in stock.</div></div>'),
)
PRICE_ANOMALY_HTML = _PAGE.format(
    title="Amazon | Sony WH-1000XM5",
    body=('<div id="dp-container"><span id="productTitle">Sony WH-1000XM5 Wireless '
          'Noise-Canceling Headphones</span><span class="a-price"><span class="a-offscreen">'
          '$599.00</span></span><div id="availability">In Stock</div></div>'),
)
BLOCKED_HTML = _PAGE.format(
    title="Robot Check",
    body=('<div>Sorry, we just need to make sure you\'re not a robot. Enter the characters '
          'you see below to continue.</div>'),
)
DEAD_HTML = _PAGE.format(
    title="Page Not Found",
    body=('<div><h1>Page Not Found</h1>Sorry! We couldn\'t find that page. '
          'Try searching for something else.</div>'),
)
HOMEPAGE_HTML = _PAGE.format(
    title="Store Home",
    body=('<div id="nav-home"><h1>Welcome to the Store</h1>'
          '<a href="/deals">Today\'s Deals</a></div>'),
)

# A "real blog post" with outbound links of each class, for the generic adapter
# (spec §4.1): commercial (Amazon affiliate w/ tag), reference (Wikipedia),
# internal (/about), plus mailto + bare-fragment anchors that must be skipped.
BLOG_POST_HTML = _PAGE.format(
    title="My Blog | Best Headphones 2026",
    body=(
        '<article><h1>Best Headphones 2026</h1>'
        '<p>Our top pick is the <a href="https://www.amazon.com/dp/B0TEST?tag=everlink-20">'
        'Sony WH-1000XM5 on Amazon</a> - superb noise cancellation.</p>'
        '<p>For background, see <a href="https://en.wikipedia.org/wiki/Headphones">'
        'the Wikipedia article on headphones</a>.</p>'
        '<p>Read <a href="/about">about us</a> or '
        '<a href="mailto:hi@myblog.example">email us</a>. Jump to <a href="#specs">specs</a>.</p>'
        '</article>'
    ),
)
BLOG_POST2_HTML = _PAGE.format(
    title="My Blog | AliExpress Finds",
    body=(
        '<article><h1>AliExpress Finds</h1>'
        '<p>Grab this <a href="https://s.click.aliexpress.com/e/_deadaff?aff=xyz">gadget deal</a>.</p>'
        '<p>Also a <a href="https://example.org/reference/page">reference link</a>.</p>'
        '</article>'
    ),
)
ROBOTS_TXT = "User-agent: *\nDisallow:\n"

# A same-host "link farm" pointing at every scenario page, so scan_site.py can be
# smoked end-to-end hermetically (--include-internal): dead / ok / unavailable /
# price-anomaly / a dropped-tag affiliate redirect — no live external sites.
LINK_FARM_HTML = _PAGE.format(
    title="Link Farm",
    body=(
        '<div><a href="/dead">a dead link</a> '
        '<a href="/ok">a live product</a> '
        '<a href="/unavailable">an unavailable offer</a> '
        '<a href="/price-anomaly">a repriced item</a> '
        '<a href="/affiliate/deal?tag=everlink-20">an affiliate deal</a></div>'
    ),
)

# path -> (status, html)
PAGES = {
    "/ok": (200, OK_HTML),
    "/unavailable": (200, UNAVAILABLE_HTML),
    "/price-anomaly": (200, PRICE_ANOMALY_HTML),
    "/blocked": (200, BLOCKED_HTML),
    "/dead": (404, DEAD_HTML),
    "/disclosure-dead": (404, DEAD_HTML),
    "/blog/post1": (200, BLOG_POST_HTML),
    "/blog/post2": (200, BLOG_POST2_HTML),
    "/link-farm": (200, LINK_FARM_HTML),
    "/robots.txt": (200, ROBOTS_TXT),
    "/": (200, HOMEPAGE_HTML),
}

# Sitemap routes are generated per-request so their <loc>s point back at whatever
# ephemeral port the test server bound (spec §4.1 generic-adapter fixtures).
SITEMAP_PATHS = {"/sitemap.xml", "/sitemap-index.xml", "/sub-sitemap.xml"}


def _sitemap_urlset(base: str, locs: list[str]) -> str:
    items = "".join(f"<url><loc>{l}</loc></url>" for l in locs)
    return ('<?xml version="1.0" encoding="UTF-8"?>'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            f'{items}</urlset>')


def _sitemap_index_xml(base: str, subs: list[str]) -> str:
    items = "".join(f"<sitemap><loc>{s}</loc></sitemap>" for s in subs)
    return ('<?xml version="1.0" encoding="UTF-8"?>'
            '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            f'{items}</sitemapindex>')

# Redirect scenarios: path -> (status, Location builder given query params).
# /affiliate/deal?tag=everlink-20 -> 302 to "/" (the tag is silently dropped),
# which is exactly the L1 "program_ended" signal (tracking lost, lands homepage).
REDIRECTS = {
    "/affiliate/deal": lambda q: "/",
    "/affiliate/network": lambda q: "/ok",
}


class FixtureHandler(BaseHTTPRequestHandler):
    """Serves the deterministic fixtures above. Silences request logging."""

    server_version = "EverLinkFixture/1.0"

    def _send(self, status: int, body: str,
              content_type: str = "text/html; charset=utf-8") -> None:
        raw = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        if path in REDIRECTS:
            location = REDIRECTS[path](query)
            self.send_response(302)
            self.send_header("Location", location)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return

        if path in SITEMAP_PATHS:
            base = f"http://{self.headers.get('Host') or HOST}"
            if path == "/sitemap.xml":
                body = _sitemap_urlset(base, [base + "/blog/post1", base + "/blog/post2"])
            elif path == "/sitemap-index.xml":
                body = _sitemap_index_xml(base, [base + "/sub-sitemap.xml"])
            else:  # /sub-sitemap.xml
                body = _sitemap_urlset(base, [base + "/blog/post1"])
            self._send(200, body, content_type="application/xml; charset=utf-8")
            return

        # Prefix routes for the Evals suite (spec §8): many DISTINCT paths share
        # one scenario page, so each eval case gets a unique URL (hence a unique
        # decision-card merge key) while exercising the same detection outcome.
        # Exact routes above still win; these results are identical for the bare
        # paths, so existing tests are unaffected.
        if path.startswith("/dead"):
            self._send(404, DEAD_HTML)
            return
        if path.startswith("/price-anomaly"):
            self._send(200, PRICE_ANOMALY_HTML)
            return
        if path.startswith("/unavailable"):
            self._send(200, UNAVAILABLE_HTML)
            return
        if path.startswith("/affiliate/deal"):
            self.send_response(302)
            self.send_header("Location", "/")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return

        status, html = PAGES.get(path, (200, OK_HTML))
        self._send(status, html)

    def log_message(self, *args) -> None:  # keep test/demo output clean
        pass


def make_server(port: int = FIXTURE_PORT_DEFAULT, host: str = HOST) -> ThreadingHTTPServer:
    """Build (but do not start) a fixture HTTP server. port=0 -> ephemeral.

    Side-effect: sets ``EVERLINK_ALLOW_LOCALNET=1`` so the SSRF guard permits
    requests to 127.0.0.1 (the fixture server itself). Production never calls
    this function, so the env var stays unset and the guard is fully active.
    """
    os.environ.setdefault("EVERLINK_ALLOW_LOCALNET", "1")
    return ThreadingHTTPServer((host, port), FixtureHandler)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=FIXTURE_PORT_DEFAULT)
    args = ap.parse_args()
    srv = make_server(args.port)
    host, port = srv.server_address[0], srv.server_address[1]
    print(f"EverLink fixture server on http://{host}:{port}")
    print("scenarios:", ", ".join(sorted(k for k in PAGES if k != "/")))
    print("redirects:", ", ".join(sorted(REDIRECTS)))
    print("Ctrl-C to stop.")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nstopping.")
    finally:
        srv.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
