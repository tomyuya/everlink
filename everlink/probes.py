"""L1 detection: HTTP status + redirect-chain analysis (spec §4.1).

L1 needs no product API. Its highest-value signal is redirect-chain analysis:
an affiliate hop that silently drops its tracking parameter, or bounces back to
the network's own homepage instead of the advertiser's product page, means the
program likely ended. Anything blocked / rate-limited / errored is honestly
flagged `needs_human_recheck` (handed to L2 Scrapling or a human) — L1 never
fabricates a healthy verdict it cannot prove.

The classification logic is split into pure functions (`analyze_chain`,
`classify_l1`) so it can be unit-tested offline without any network access.
"""
from __future__ import annotations

import time
from urllib.parse import urlparse, parse_qs

import httpx

from .model import CheckResult, LinkSlot, RedirectHop, Verdict

# Query params that carry affiliate/tracking attribution.
AFFILIATE_PARAMS = {
    "tag", "aff", "affid", "affiliate", "affsub", "affsub1", "click", "clickid",
    "sub", "subid", "sub1", "pid", "irclickid", "ranmid", "ransiteid",
    "utm_source", "utm_medium", "utm_campaign", "u1", "u2", "src",
}
# Domains that are affiliate networks / redirectors (not the advertiser itself).
NETWORK_DOMAINS = (
    "amzn.to", "s.click.aliexpress.com", "aliexpress.com/e", "pjtra.com",
    "impactradius", "irclickid", "shareasale", "cj.com", "awin", "anrdoezrs",
    "rakuten", "linksynergy", "avantlink", "pepperjam", "partnerstack",
)
DEAD_STATUS = {404, 410, 451}
BLOCKED_STATUS = {401, 403, 429, 500, 502, 503, 504}
DEFAULT_HEADERS = {
    # A real browser UA; many retailers 403/503 obvious non-browser clients.
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


def _aff_params(url: str) -> set[str]:
    q = parse_qs(urlparse(url).query)
    return {k.lower() for k in q} & AFFILIATE_PARAMS


def _host(url: str) -> str:
    return (urlparse(url).netloc or "").lower()


def _path(url: str) -> str:
    return urlparse(url).path or "/"


def _is_network_domain(url: str) -> bool:
    h = _host(url)
    return any(h == d or h.endswith("." + d) or d in h for d in NETWORK_DOMAINS)


def analyze_chain(original_url: str, chain: list[RedirectHop]):
    """Pure function: detect affiliate-attribution loss / program-ended signals.

    Returns (hint, evidence) where hint is 'program_ended' or None.
    """
    if not chain:
        return None, None
    final = chain[-1].url
    orig_aff = _aff_params(original_url)
    final_aff = _aff_params(final)

    # Signal 1: chain ends back on an affiliate-network domain (never reached
    # the advertiser) => the redirect target is gone / program ended.
    if _is_network_domain(final) and _host(final) != _host(original_url):
        return "program_ended", f"redirect chain ends on network domain {_host(final)}"

    # Signal 2: original carried tracking params but the final URL dropped them
    # all AND landed on a bare homepage => attribution stripped, offer likely dead.
    if orig_aff and not final_aff and _path(final) in ("/", ""):
        return "program_ended", (
            f"tracking params {sorted(orig_aff)} lost; landed on homepage {final}"
        )

    # Signal 3: tracking params lost mid-chain (weaker) — record as evidence only.
    if orig_aff and not final_aff:
        return None, f"tracking params {sorted(orig_aff)} not present on final URL"
    return None, None


def classify_l1(status: int | None, chain: list[RedirectHop], original_url: str,
                error: str | None = None) -> tuple[Verdict, str | None]:
    """Pure function: map an L1 probe outcome to a final verdict."""
    if error:
        return "needs_human_recheck", f"transport error: {error}"
    if status is None:
        return "needs_human_recheck", "no status resolved"
    if status in DEAD_STATUS:
        return "dead", f"HTTP {status}"
    if status in BLOCKED_STATUS:
        # Retailers (esp. Amazon) frequently 403/503 headless clients; do not
        # guess dead — escalate to L2 / human.
        return "needs_human_recheck", f"HTTP {status} (blocked/rate-limited)"
    hint, evidence = analyze_chain(original_url, chain)
    if hint == "program_ended":
        return "program_ended", evidence
    if 200 <= status < 400:
        # L1 can only assert "reachable"; offer_changed / unavailable are L2's job.
        return "healthy", evidence
    return "needs_human_recheck", f"HTTP {status}"


def probe_url(url: str, slot_id: str = "", *, timeout: float = 15.0,
              max_hops: int = 6, headers: dict | None = None,
              client: httpx.Client | None = None) -> CheckResult:
    """Follow redirects manually to capture the full chain, then classify."""
    hdrs = {**DEFAULT_HEADERS, **(headers or {})}
    chain: list[RedirectHop] = []
    error: str | None = None
    status: int | None = None
    current = url
    own = client is None
    cli = client or httpx.Client(follow_redirects=False, headers=hdrs, timeout=timeout)
    try:
        for _ in range(max_hops):
            try:
                resp = cli.get(current)
            except httpx.HTTPError as e:
                error = f"{type(e).__name__}: {e}"
                break
            status = resp.status_code
            chain.append(RedirectHop(url=current, status=status))
            if status in (301, 302, 303, 307, 308):
                loc = resp.headers.get("location")
                if not loc:
                    break
                current = str(httpx.URL(current).join(loc))
                continue
            break
        else:
            error = f"too many redirects (>{max_hops})"
    finally:
        if own:
            cli.close()
    verdict, evidence = classify_l1(status, chain, url, error)
    return CheckResult(
        slot_id=slot_id, l1_status=status, redirect_chain=chain,
        final_verdict=verdict, error=error,
        l2_evidence=evidence,
    )


def probe_slots(slots: list[LinkSlot], *, rate_delay: float = 1.0,
                timeout: float = 15.0, max_hops: int = 6,
                limit: int | None = None):
    """Probe slots politely: <=1 request per link, `rate_delay` seconds apart."""
    client = httpx.Client(follow_redirects=False, headers=DEFAULT_HEADERS, timeout=timeout)
    try:
        for i, slot in enumerate(slots):
            if limit is not None and i >= limit:
                break
            yield probe_url(slot.url, slot.id, timeout=timeout,
                            max_hops=max_hops, client=client)
            if rate_delay:
                time.sleep(rate_delay)
    finally:
        client.close()
