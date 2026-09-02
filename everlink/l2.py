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
    "product not found", "404", "this page is no longer available",
]
UNAVAILABLE_PHRASES = [
    "currently unavailable", "temporarily out of stock", "out of stock",
    "no longer available", "this item is not available", "sold out",
    "not available for purchase", "product unavailable", "we don't know when or if this item will be back in stock",
]
# Structural (id/class) hints that outweigh prose, common on Amazon PDPs.
# NOTE: id="availability" is deliberately excluded — that container is present on
# *healthy* pages too ("In Stock"); the real out-of-stock state is id="outOfStock".
UNAVAILABLE_MARKERS = ['id="outofstock"', "outofstock"]

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
    ``price_anomaly`` is only asserted when a ``claimed_price`` (from the
    surrounding sentence) is supplied and the live price is materially higher.
    """
    low = _norm(html)
    title = extract_title(html)
    price = extract_price(html)

    sig = _first_match(BLOCKED_PHRASES, low)
    if sig:
        return L2Result(verdict="blocked", evidence=f"bot-wall / captcha signal: '{sig}'",
                        title=title, extracted_price=price, matched_signal=sig)

    sig = _first_match(DEAD_PHRASES, low)
    if sig:
        return L2Result(verdict="dead", evidence=f"page-not-found signal: '{sig}'",
                        title=title, extracted_price=price, matched_signal=sig)

    sig = _first_match(UNAVAILABLE_PHRASES, low)
    marker = next((m for m in UNAVAILABLE_MARKERS if m in low), None)
    if sig or marker:
        ev = f"availability signal: '{sig or marker}'"
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


def fetch_page(url: str, *, timeout: float = 20.0, engine: str = "auto",
               headers: Optional[dict] = None) -> tuple[Optional[int], str, Optional[str]]:
    """Fetch a page's HTML. Returns (status, html, error).

    engine: "auto" tries Scrapling's stealthy fetch when installed, else httpx;
    "httpx" forces httpx; "scrapling" forces Scrapling. Any transport failure is
    returned as (None, "", error_text) so callers can flag needs_human_recheck
    rather than guessing.
    """
    hdrs = headers or _stealthy_headers()

    if engine in ("auto", "scrapling"):
        try:
            from scrapling.fetchers import StealthyFetcher  # type: ignore

            resp = StealthyFetcher.fetch(url, timeout=int(timeout * 1000))
            status = getattr(resp, "status", 200)
            return status, resp.html or "", None
        except ImportError:
            if engine == "scrapling":
                return None, "", "scrapling not installed"
        except Exception as e:  # noqa: BLE001
            if engine == "scrapling":
                return None, "", f"scrapling fetch failed: {type(e).__name__}: {e}"
            # auto: fall through to httpx

    try:
        import httpx

        with httpx.Client(timeout=timeout, headers=hdrs, follow_redirects=True,
                          trust_env=_trust_env()) as client:
            r = client.get(url)
            return r.status_code, r.text, None
    except Exception as e:  # noqa: BLE001
        return None, "", f"httpx fetch failed: {type(e).__name__}: {e}"


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
