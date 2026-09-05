"""L2 page parsing — layer 2 of the detection pyramid (spec §4.1).

L1 (probes.py) answers "is the URL reachable, and did the affiliate redirect
chain drop its tracking tag?". L2 answers "is the *offer* still live on the
page?" — an HTTP 200 Amazon page can still be "Currently unavailable", a soft
404, or a bot-wall. L2 parses the fetched HTML into a verdict + human-readable
evidence.

Design for testability & the spec circuit-breaker:
  * ``parse_product_page(html)`` is a PURE function (no I/O) — fully unit-tested
    against fixture HTML. This is the durable value of L2.
  * ``fetch_page(url)`` is the I/O layer: httpx by default, Scrapling "stealthy"
    engine when installed (spec §4.1). If neither works / the page is a bot-wall
    / it times out, the result is ``blocked`` → upstream maps to
    ``needs_human_recheck`` (the agent knows its limits, never fabricates).
"""
from __future__ import annotations

import os
import re
from typing import Literal, Optional

from pydantic import BaseModel

from .ssrf import SsrfBlocked, guard_url, httpx_request_guard

L2Verdict = Literal["ok", "dead", "price_anomaly", "unavailable", "blocked"]

# Lowercased substring signals. Ordered by precedence inside each class.
BLOCKED_PHRASES = [
    "robot check", "enter the characters you see", "validatecaptcha",
    "type the characters you see", "sorry, we just need to make sure",
    "automated access", "unusual traffic", "are you a robot", "please enable js",
    "access denied", "captcha",
]
DEAD_PHRASES = [
    "page not found", "sorry! we couldn't find that page", "we can't find that page",
    "doesn't exist", "no longer exists", "has been removed", "item not found",
    "product not found", "this page is no longer available",
]
# NOTE: a bare "404" is deliberately NOT a phrase. As a substring it matches review
# ids, model numbers and CSS classes on perfectly healthy pages; a genuine 404 is
# caught by L1's HTTP status (and by probe_l2's status fallback) instead.
UNAVAILABLE_PHRASES = [
    "currently unavailable", "temporarily out of stock", "out of stock",
    "no longer available", "this item is not available", "sold out",
    "not available for purchase", "product unavailable", "we don't know when or if this item will be back in stock",
]
# Structural (id/class) hints that outweigh prose, common on Amazon PDPs.
# NOTE: id="availability" is deliberately excluded — that container is present on
# *healthy* pages too ("In Stock"). And only the STRUCTURAL buybox element
# id="outOfStock" is trusted: the bare token "outofstock" is NOT a marker, because
# as a whole-page substring it matches JS config flags, swatch data-attributes and
# CSS class names on perfectly LIVE pages — the same false-positive class as a bare
# "404" (real incident: live Amazon PDPs misjudged offer_changed). A genuine
# out-of-stock state renders id="outOfStock" and/or says so in the availability
# region, both of which are still caught below.
UNAVAILABLE_MARKERS = ['id="outofstock"']

_PRICE_RE = re.compile(
    r"(?:\$|£|€|¥|USD|GBP|EUR)\s?(\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{1,2})?)", re.I
)
_TITLE_RE = re.compile(
    r'id="productTitle"[^>]*>\s*(.+?)\s*<', re.I | re.S
)
_GENERIC_TITLE_RE = re.compile(r"<title[^>]*>\s*(.+?)\s*</title>", re.I | re.S)


class L2Result(BaseModel):
    """Outcome of parsing one fetched page (feeds CheckResult.l2_*)."""

    verdict: L2Verdict
    evidence: str = ""
    title: Optional[str] = None
    extracted_price: Optional[str] = None
    matched_signal: Optional[str] = None


def _norm(html: str) -> str:
    return re.sub(r"\s+", " ", (html or "")).lower()


def _first_match(needle_list: list[str], low: str) -> Optional[str]:
    for p in needle_list:
        if p in low:
            return p
    return None


_SCRIPT_STYLE_RE = re.compile(r"<(script|style|noscript|iframe)\b.*?</\1>", re.I | re.S)
_TAG_RE = re.compile(r"<[^>]+>", re.S)
_BODY_RE = re.compile(r"<body\b[^>]*>", re.I)
_AVAIL_RE = re.compile(r"id=[\"']availability[\"']", re.I)
_SHELL_RE = re.compile(r"id=[\"']producttitle[\"']", re.I)


def _visible_text(html: str) -> str:
    """Tag-stripped visible text (scripts/styles removed) — a human's reading order."""
    stripped = _SCRIPT_STYLE_RE.sub(" ", html or "")
    m = _BODY_RE.search(stripped)
    if m:
        stripped = stripped[m.end():]
    return _TAG_RE.sub(" ", stripped)


def signal_regions(html: str) -> dict:
    """PURE: the page regions a rot signal may legitimately come from.

    A megabyte-scale retail PDP carries user reviews, Q&A threads and JS strings
    that mention "doesn't exist", "out of stock", even "captcha" — on a perfectly
    HEALTHY page. Whole-page substring matching therefore false-positives (real
    incident: a live Amazon PDP judged dead because one review said "doesn't
    exist"). Signals are accepted only from:

      * ``title``          — the <title> tag (error pages say so there);
      * ``early``          — the first screen of visible text (main content
                             precedes UGC in reading order);
      * ``availability``   — Amazon's #availability container (offer state);
      * ``shell``          — structural flag: a #productTitle marker exists, i.e.
                             the page IS a product page (ids cannot appear in
                             prose, so this marker is safe page-wide).

    When ``shell`` is true, prose dead/blocked phrases are treated as UGC noise:
    a product page that renders its title and buybox is not a 404 and not a
    captcha wall, whatever a review happens to say.
    """
    html = html or ""
    title_m = _GENERIC_TITLE_RE.search(html)
    visible = _norm(_visible_text(html))
    avail = ""
    m = _AVAIL_RE.search(html)
    if m:
        avail = _norm(_TAG_RE.sub(" ", html[m.start(): m.start() + 2000]))
    return {
        "title": _norm(title_m.group(1)) if title_m else "",
        "early": visible[:4000],
        "availability": avail,
        "shell": bool(_SHELL_RE.search(html)),
    }


def extract_price(html: str) -> Optional[str]:
    """Best-effort current price from the page (for Judge-side drift compare)."""
    # Prefer Amazon's screen-reader price span, else the first currency amount.
    m = re.search(r'class="a-offscreen"[^>]*>\s*([^<]{1,20})\s*<', html or "", re.I)
    if m:
        return m.group(1).strip()
    m = _PRICE_RE.search(html or "")
    return m.group(0).strip() if m else None


def extract_title(html: str) -> Optional[str]:
    m = _TITLE_RE.search(html or "")
    if m:
        return re.sub(r"\s+", " ", m.group(1)).strip()[:200]
    m = _GENERIC_TITLE_RE.search(html or "")
    if m:
        return re.sub(r"\s+", " ", m.group(1)).strip()[:200]
    return None


def _to_number(price: Optional[str]) -> Optional[float]:
    if not price:
        return None
    m = re.search(r"(\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{1,2})?)", price)
    if not m:
        return None
    num = m.group(1).replace(",", "")
    try:
        return float(num)
    except ValueError:
        return None


def parse_product_page(
    html: str, *, claimed_price: Optional[str] = None, price_drift_ratio: float = 1.5
) -> L2Result:
    """PURE: classify a fetched product page into an L2 verdict + evidence.

    Precedence: blocked > dead > unavailable > price_anomaly > ok.
    Every prose signal is REGION-SCOPED via ``signal_regions`` (title / first
    screen of visible text / availability container), and a page that carries a
    product shell (``#productTitle``) can never be prose-judged dead or blocked —
    see ``signal_regions`` for the false-positive incident this prevents.
    ``price_anomaly`` is only asserted when a ``claimed_price`` (from the
    surrounding sentence) is supplied and the live price is materially higher.
    """
    regions = signal_regions(html)
    title = extract_title(html)
    price = extract_price(html)
    prose = (regions["title"], regions["early"])

    sig = next((s for s in (_first_match(BLOCKED_PHRASES, r) for r in prose) if s), None)
    if sig and not regions["shell"]:
        return L2Result(verdict="blocked",
                        evidence=f"bot-wall / captcha signal: '{sig}' (probe-side block; "
                                 f"user accessibility unknown)",
                        title=title, extracted_price=price, matched_signal=sig)

    sig = next((s for s in (_first_match(DEAD_PHRASES, r) for r in prose)
                if s and not regions["shell"]), None)
    if sig:
        return L2Result(verdict="dead",
                        evidence=f"page-not-found signal: '{sig}' in title/main content "
                                 f"(no product shell on the page)",
                        title=title, extracted_price=price, matched_signal=sig)

    marker = next((m for m in UNAVAILABLE_MARKERS if m in _norm(html)), None)
    sig = _first_match(UNAVAILABLE_PHRASES, regions["availability"]) or (
        None if regions["shell"] else _first_match(UNAVAILABLE_PHRASES, regions["early"]))
    if sig or marker:
        where = "structural marker" if marker else "availability region"
        ev = f"unavailable signal: '{sig or marker}' ({where})"
        return L2Result(verdict="unavailable", evidence=ev,
                        title=title, extracted_price=price, matched_signal=sig or marker)

    if claimed_price:
        claimed_n, live_n = _to_number(claimed_price), _to_number(price)
        if claimed_n and live_n and live_n >= claimed_n * price_drift_ratio:
            return L2Result(
                verdict="price_anomaly",
                evidence=f"live price {price} >= {price_drift_ratio}x claimed {claimed_price}",
                title=title, extracted_price=price, matched_signal="price_drift",
            )

    if not title and not price:
        # Fetched *something* 200 but it looks like neither a product nor a known
        # error page — don't claim health.
        return L2Result(verdict="blocked",
                        evidence="no product title/price and no known signal; refusing to assert 'ok'",
                        title=None, extracted_price=None, matched_signal=None)

    return L2Result(verdict="ok", evidence=f"live product page (title/price present)",
                    title=title, extracted_price=price, matched_signal=None)


def _trust_env() -> bool:
    """Whether httpx honors ambient proxy env / OS proxy settings (default False).

    Mirrors probes._trust_env: direct connections give an accurate link-rot
    signal and keep the localhost fixture Evals hermetic. Set
    EVERLINK_HTTP_TRUST_ENV=1 to use a required corporate/CI egress proxy.
    """
    return os.environ.get("EVERLINK_HTTP_TRUST_ENV", "").strip().lower() in (
        "1", "true", "yes", "on",
    )


def _stealthy_headers() -> dict[str, str]:
    return {
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
        "Accept": ("text/html,application/xhtml+xml,application/xml;q=0.9,"
                   "image/avif,image/webp,*/*;q=0.8"),
        "Accept-Language": "en-US,en;q=0.9",
    }


def _fetch_httpx(url: str, timeout: float,
                 hdrs: dict) -> tuple[Optional[int], str, Optional[str]]:
    """Fast, quiet httpx GET (the common case)."""
    try:
        import httpx

        with httpx.Client(timeout=timeout, headers=hdrs, follow_redirects=True,
                          trust_env=_trust_env(),
                          event_hooks={"request": [httpx_request_guard]}) as client:
            r = client.get(url)
            return r.status_code, r.text, None
    except SsrfBlocked as e:
        return None, "", f"ssrf_blocked: {e.reason}"
    except Exception as e:  # noqa: BLE001
        return None, "", f"httpx fetch failed: {type(e).__name__}: {e}"


def _fetch_scrapling(url: str, timeout: float) -> tuple[Optional[int], str, Optional[str]]:
    """Stealthy browser fetch — defeats bot-walls. Silences Scrapling's loguru."""
    try:
        from loguru import logger as _loguru  # type: ignore
        _loguru.disable("scrapling")
    except Exception:  # noqa: BLE001
        pass
    try:
        from scrapling.fetchers import StealthyFetcher  # type: ignore

        resp = StealthyFetcher.fetch(url, timeout=int(timeout * 1000))
        return getattr(resp, "status", 200), resp.html or "", None
    except ImportError:
        return None, "", "scrapling not installed"
    except Exception as e:  # noqa: BLE001
        return None, "", f"scrapling fetch failed: {type(e).__name__}: {e}"


def fetch_page(url: str, *, timeout: float = 20.0, engine: str = "auto",
               headers: Optional[dict] = None) -> tuple[Optional[int], str, Optional[str]]:
    """Fetch a page's HTML. Returns (status, html, error).

    engine:
      * "httpx"      — force the fast, quiet httpx GET.
      * "scrapling"  — force the stealthy browser fetch.
      * "auto" (default) — httpx first (cheap, quiet); escalate to Scrapling
        stealthy ONLY when httpx fails or the body looks like a bot-wall. This
        keeps L2 fast and log-clean while preserving the spec §4.1 stealthy
        fallback exactly where it earns its cost.
    Any transport failure returns (None, "", error_text) so callers flag
    needs_human_recheck rather than guessing.
    """
    hdrs = headers or _stealthy_headers()

    # SSRF pre-check: refuse internal targets before any network I/O.
    try:
        guard_url(url)
    except SsrfBlocked as e:
        return None, "", f"ssrf_blocked: {e.reason}"

    if engine == "scrapling":
        return _fetch_scrapling(url, timeout)
    if engine == "httpx":
        return _fetch_httpx(url, timeout, hdrs)

    # engine == "auto": cheap httpx first, stealthy escalation only when needed.
    status, html, err = _fetch_httpx(url, timeout, hdrs)
    if err or not html:
        s2, h2, _e2 = _fetch_scrapling(url, timeout)
        return (s2, h2, None) if h2 else (status, html, err)
    if parse_product_page(html).verdict == "blocked":
        s2, h2, _e2 = _fetch_scrapling(url, timeout)
        if h2:
            return s2, h2, None
    return status, html, None


def probe_l2(url: str, *, claimed_price: Optional[str] = None,
             timeout: float = 20.0, engine: str = "auto") -> L2Result:
    """fetch + parse. Transport errors / bot-walls collapse to 'blocked'."""
    status, html, err = fetch_page(url, timeout=timeout, engine=engine)
    if err or not html:
        return L2Result(verdict="blocked",
                        evidence=f"fetch failed: {err or 'empty body'}",
                        matched_signal="fetch_error")
    result = parse_product_page(html, claimed_price=claimed_price)
    # A hard 404/410 body that somehow lacks our phrases is still dead.
    if status in (404, 410) and result.verdict == "ok":
        return L2Result(verdict="dead", evidence=f"HTTP {status}", matched_signal="http_status")
    return result
