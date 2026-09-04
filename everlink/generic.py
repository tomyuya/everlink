"""Generic read-only adapter: any site -> LinkSlot[] (spec §4.1).

The three first-party adapters read Phase-A CSV snapshots (see adapters.py).
This module is the *portable* path a judge or new user points at their OWN site:
give it a sitemap URL, a page URL, or a list of URLs and it crawls **read-only**,
extracts outbound links, and returns typed LinkSlot objects for the Scanner to
probe. It NEVER writes back (spec: `generic` = read-only report, for judge
try-outs and the demo video).

Crucially, detection (L1/L2) needs no LLM — so a real dead-link report on any
site runs with zero AWS credentials.

Everything network-free is a PURE function (parse_sitemap, extract_links,
classify_slot_type, absolutize_url) so the adapter is unit-testable offline
against fixture XML/HTML; only the thin crawl layer touches the network.

Politeness: descriptive UA, <=1 request per link, `rate_delay` between pages,
`max_pages` / `max_slots` caps, and optional robots.txt (fail-open).
"""
from __future__ import annotations

import gzip
import hashlib
import os
import re
import time
from html import unescape
from html.parser import HTMLParser
from typing import Iterable, Optional
from urllib.parse import parse_qs, urldefrag, urljoin, urlparse
from urllib.robotparser import RobotFileParser

import httpx

from .model import LinkSlot, SlotType
from .probes import AFFILIATE_PARAMS
from .ssrf import httpx_request_guard

DEFAULT_UA = ("EverLinkBot/1.0 (+https://github.com/tomyuya/everlink) "
              "read-only link-rot checker")
SKIP_SCHEMES = ("mailto:", "tel:", "javascript:", "ftp:", "data:", "sms:")
# Hosts whose outbound links are commercial / affiliate (highest link-rot value).
COMMERCIAL_DOMAINS = (
    "amazon.", "amzn.to", "aliexpress.", "s.click.aliexpress", "ebay.", "etsy.",
    "walmart.", "target.com", "bestbuy.", "shareasale", "cj.com", "awin",
    "rakuten", "linksynergy", "avantlink", "pepperjam", "partnerstack",
    "impactradius", "anrdoezrs", "clickbank", "commission-junction", "shopstyle",
    "skimlinks", "tgtag.io", "tkqlhce", "dpbolvw", "kqzyfj", "jdoqocy",
)
_LOC_RE = re.compile(r"<loc>\s*(.*?)\s*</loc>", re.I | re.S)


# --------------------------------------------------------------------------- #
# pure functions (offline-testable)
# --------------------------------------------------------------------------- #
def parse_sitemap(xml_text: str) -> list[str]:
    """PURE: pull every <loc> URL out of a sitemap OR sitemap-index XML."""
    return [unescape(m).strip() for m in _LOC_RE.findall(xml_text or "") if m.strip()]


def is_sitemap_index(xml_text: str) -> bool:
    """PURE: a sitemap-index's <loc>s are sub-sitemaps, not pages."""
    return "<sitemapindex" in (xml_text or "").lower()


def absolutize_url(href: str, base_url: str) -> Optional[str]:
    """PURE: resolve an href against base_url; drop fragments & non-HTTP schemes.

    Returns None for anything we should not treat as a crawlable link
    (empty, pure #anchor, mailto:/tel:/javascript:, relative non-http).
    """
    h = (href or "").strip()
    if not h or h.startswith("#"):
        return None
    low = h.lower()
    if any(low.startswith(s) for s in SKIP_SCHEMES):
        return None
    absu = urljoin(base_url, unescape(h))
    absu, _frag = urldefrag(absu)
    if not absu.startswith(("http://", "https://")):
        return None
    return absu


class _AnchorParser(HTMLParser):
    """Streaming collector: every <a href> with its anchor text, plus <title>."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title: Optional[str] = None
        self.links: list[tuple[str, str]] = []
        self._in_a = False
        self._href: Optional[str] = None
        self._buf: list[str] = []
        self._in_title = False
        self._title_buf: list[str] = []

    def handle_starttag(self, tag, attrs):  # noqa: ANN001
        if tag == "a":
            self._in_a, self._buf, self._href = True, [], None
            for k, v in attrs:
                if k == "href":
                    self._href = v
        elif tag == "title" and self.title is None:
            self._in_title, self._title_buf = True, []

    def handle_endtag(self, tag):  # noqa: ANN001
        if tag == "a" and self._in_a:
            text = re.sub(r"\s+", " ", "".join(self._buf)).strip()
            if self._href:
                self.links.append((self._href, text))
            self._in_a = False
        elif tag == "title" and self._in_title:
            self.title = re.sub(r"\s+", " ", "".join(self._title_buf)).strip()[:200]
            self._in_title = False

    def handle_data(self, data):  # noqa: ANN001
        if self._in_a:
            self._buf.append(data)
        if self._in_title:
            self._title_buf.append(data)


def extract_links(html: str, base_url: str) -> tuple[Optional[str], list[tuple[str, str]]]:
    """PURE: html -> (page_title, [(absolute_url, anchor_text), ...])."""
    p = _AnchorParser()
    try:
        p.feed(html or "")
    except Exception:  # noqa: BLE001  (malformed html -> keep what we got)
        pass
    out: list[tuple[str, str]] = []
    for href, text in p.links:
        absu = absolutize_url(href, base_url)
        if absu:
            out.append((absu, text))
    return p.title, out


def classify_slot_type(url: str, base_host: str) -> SlotType:
    """PURE: internal (same site) / commercial (affiliate/merchant) / reference."""
    host = (urlparse(url).hostname or "").lower()
    base = (base_host or "").lower()
    if host and base and (host == base or host.endswith("." + base) or base.endswith("." + host)):
        return "internal"
    q = {k.lower() for k in parse_qs(urlparse(url).query)}
    if (q & AFFILIATE_PARAMS) or any(d in host for d in COMMERCIAL_DOMAINS):
        return "commercial"
    return "reference"


# --------------------------------------------------------------------------- #
# thin network layer
# --------------------------------------------------------------------------- #
def _trust_env() -> bool:
    """Mirror probes._trust_env: direct by default (hermetic + true signal)."""
    return os.environ.get("EVERLINK_HTTP_TRUST_ENV", "").strip().lower() in (
        "1", "true", "yes", "on",
    )


def _headers(ua: Optional[str] = None) -> dict[str, str]:
    return {"User-Agent": ua or DEFAULT_UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"}


def _client(timeout: float, headers: Optional[dict] = None) -> httpx.Client:
    return httpx.Client(timeout=timeout, headers=headers or _headers(),
                        follow_redirects=True, trust_env=_trust_env(),
                        event_hooks={"request": [httpx_request_guard]})


def _decode_body(content: bytes) -> str:
    """gzip-aware decode (sitemap files are frequently served gzipped)."""
    if content[:2] == b"\x1f\x8b":
        try:
            content = gzip.decompress(content)
        except Exception:  # noqa: BLE001
            pass
    return content.decode("utf-8", errors="replace")


def _get(url: str, client: httpx.Client) -> tuple[Optional[int], str, Optional[str]]:
    try:
        r = client.get(url)
    except Exception as e:  # noqa: BLE001  (transport/timeout -> honest error)
        return None, "", f"{type(e).__name__}: {e}"
    return r.status_code, _decode_body(r.content), None


def _robots_allows(page_url: str, client: httpx.Client,
                   cache: dict[str, RobotFileParser], ua: str) -> bool:
    """robots.txt check, fail-open (a missing/unreadable robots.txt allows all)."""
    parsed = urlparse(page_url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    rp = cache.get(origin)
    if rp is None:
        rp = RobotFileParser()
        try:
            _status, text, err = _get(origin + "/robots.txt", client)
            if not err and text:
                rp.parse(text.splitlines())
        except Exception:  # noqa: BLE001
            pass
        cache[origin] = rp
    try:
        return rp.can_fetch(ua, page_url)
    except Exception:  # noqa: BLE001
        return True


def _make_slot(*, site: str, page_url: str, page_title: Optional[str],
               target: str, anchor: str, slot_type: SlotType) -> LinkSlot:
    slug = re.sub(r"[^a-z0-9]+", "-", (urlparse(page_url).hostname or site).lower())
    slug = slug.strip("-")[:40] or "site"
    digest = hashlib.sha1(f"{page_url}|{target}".encode("utf-8")).hexdigest()[:12]
    return LinkSlot(
        id=f"gen-{slug}-{digest}",
        site=site,
        article_id=page_url,
        article_title=page_title or "",
        block_id="",
        block_type="generic-html",
        slot_type=slot_type,
        role=None,
        anchor_text=(anchor or None),
        url=target,
        target_url=target,
        surrounding_sentence=None,
        regions=None,
        protected=0,
        status="active",
    )


def slots_from_page(url: str, *, site: Optional[str] = None,
                    client: Optional[httpx.Client] = None, timeout: float = 20.0,
                    include_internal: bool = False, max_slots: int = 200,
                    respect_robots: bool = True,
                    robots_cache: Optional[dict] = None) -> list[LinkSlot]:
    """Crawl ONE page read-only and return its outbound LinkSlot[] (deduped)."""
    own = client is None
    cli = client or _client(timeout)
    cache = robots_cache if robots_cache is not None else {}
    ua = cli.headers.get("User-Agent", DEFAULT_UA)
    try:
        if respect_robots and not _robots_allows(url, cli, cache, ua):
            return []
        _status, html_text, err = _get(url, cli)
        if err or not html_text:
            return []
        base_host = (urlparse(url).hostname or "").lower()
        site = site or base_host or "generic"
        title, links = extract_links(html_text, url)
        slots: list[LinkSlot] = []
        seen: set[str] = set()
        for absu, anchor in links:
            st = classify_slot_type(absu, base_host)
            if st == "internal" and not include_internal:
                continue
            if absu in seen:
                continue
            seen.add(absu)
            slots.append(_make_slot(site=site, page_url=url, page_title=title,
                                    target=absu, anchor=anchor, slot_type=st))
            if len(slots) >= max_slots:
                break
        return slots
    finally:
        if own:
            cli.close()


def slots_from_sitemap(sitemap_url: str, *, site: Optional[str] = None,
                       max_pages: int = 25, max_slots: int = 500,
                       rate_delay: float = 1.0, timeout: float = 20.0,
                       include_internal: bool = False, respect_robots: bool = True,
                       headers: Optional[dict] = None) -> list[LinkSlot]:
    """Expand a sitemap (or one level of sitemap-index) then crawl its pages."""
    cli = _client(timeout, headers)
    ua = cli.headers.get("User-Agent", DEFAULT_UA)
    cache: dict[str, RobotFileParser] = {}
    slots: list[LinkSlot] = []
    try:
        _status, xml_text, err = _get(sitemap_url, cli)
        if err or not xml_text:
            return []
        locs = parse_sitemap(xml_text)
        page_urls: list[str] = []
        if is_sitemap_index(xml_text):
            for sub in locs:
                if sub.lower().endswith(".gz"):     # v1: skip gzipped sub-sitemaps
                    continue
                _s2, x2, e2 = _get(sub, cli)
                if not e2 and x2:
                    page_urls.extend(parse_sitemap(x2))
                if rate_delay:
                    time.sleep(rate_delay)
                if len(page_urls) >= max_pages:
                    break
        else:
            page_urls = locs
        base_host = (urlparse(sitemap_url).hostname or "").lower()
        site = site or base_host or "generic"
        for pu in page_urls[:max_pages]:
            slots.extend(slots_from_page(
                pu, site=site, client=cli, timeout=timeout,
                include_internal=include_internal, max_slots=max_slots,
                respect_robots=respect_robots, robots_cache=cache))
            if len(slots) >= max_slots:
                break
            if rate_delay:
                time.sleep(rate_delay)
    finally:
        cli.close()
    return slots[:max_slots]


def slots_from_urls(urls: Iterable[str], *, site: Optional[str] = None,
                    max_pages: int = 25, max_slots: int = 500,
                    rate_delay: float = 1.0, timeout: float = 20.0,
                    include_internal: bool = False, respect_robots: bool = True,
                    headers: Optional[dict] = None) -> list[LinkSlot]:
    """Treat each URL as a page and crawl it read-only."""
    urls = list(urls)[:max_pages]
    if not urls:
        return []
    cli = _client(timeout, headers)
    cache: dict[str, RobotFileParser] = {}
    base_host = (urlparse(urls[0]).hostname or "").lower()
    site = site or base_host or "generic"
    slots: list[LinkSlot] = []
    try:
        for u in urls:
            slots.extend(slots_from_page(
                u, site=site, client=cli, timeout=timeout,
                include_internal=include_internal, max_slots=max_slots,
                respect_robots=respect_robots, robots_cache=cache))
            if len(slots) >= max_slots:
                break
            if rate_delay:
                time.sleep(rate_delay)
    finally:
        cli.close()
    return slots[:max_slots]


def extract_slots_generic(source, *, site: Optional[str] = None, max_pages: int = 25,
                          max_slots: int = 500, rate_delay: float = 1.0,
                          timeout: float = 20.0, include_internal: bool = False,
                          respect_robots: bool = True,
                          headers: Optional[dict] = None) -> list[LinkSlot]:
    """Auto-detect the source kind and return read-only LinkSlot[].

    ``source`` may be a sitemap URL (contains 'sitemap' or ends .xml/.xml.gz),
    a single page URL, or a list/tuple of page URLs.
    """
    if isinstance(source, (list, tuple)):
        return slots_from_urls(source, site=site, max_pages=max_pages,
                               max_slots=max_slots, rate_delay=rate_delay,
                               timeout=timeout, include_internal=include_internal,
                               respect_robots=respect_robots, headers=headers)
    s = (source or "").strip()
    low = s.lower()
    if "sitemap" in low or low.endswith((".xml", ".xml.gz")):
        return slots_from_sitemap(s, site=site, max_pages=max_pages, max_slots=max_slots,
                                  rate_delay=rate_delay, timeout=timeout,
                                  include_internal=include_internal,
                                  respect_robots=respect_robots, headers=headers)
    return slots_from_page(s, site=site, timeout=timeout, max_slots=max_slots,
                           include_internal=include_internal,
                           respect_robots=respect_robots)
