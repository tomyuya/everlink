"""SSRF guard: refuse to fetch URLs that resolve to internal/private networks.

The scanner follows links discovered in crawled articles — those URLs are
externally controlled.  Without this guard an attacker could plant a link to
``http://169.254.169.254/latest/meta-data/`` (cloud metadata) or
``http://127.0.0.1:PORT/...`` (internal services) and EverLink would dutifully
fetch it on their behalf.

Design:
  * ``classify_blocked(url, allow_localnet=)`` — PURE function (no DNS, no I/O).
    Checks scheme and literal-IP hostnames.  Returns a reason string when blocked,
    ``None`` when the URL passes.
  * ``guard_url(url)`` — production entry-point.  Calls classify_blocked, then
    resolves the hostname and re-checks the resolved IP(s).  Raises
    ``SsrfBlocked`` on violation.
  * ``httpx_request_guard`` — an httpx ``event_hooks["request"]`` callback that
    calls guard_url before each outgoing request (including redirect hops when
    ``follow_redirects=True``).

Environment:
  ``EVERLINK_ALLOW_LOCALNET=1`` disables the IP-range check (but still enforces
  http/https scheme).  The fixture server (``fixtures.make_server``) sets this
  automatically so the offline test-suite and local demos keep working; it is
  NEVER set in production (Railway/Docker).
"""
from __future__ import annotations

import ipaddress
import os
import socket
from urllib.parse import urlparse

# --------------------------------------------------------------------------- #
# exception
# --------------------------------------------------------------------------- #


class SsrfBlocked(Exception):
    """Raised when a URL is refused by the SSRF guard."""

    def __init__(self, url: str, reason: str) -> None:
        self.url = url
        self.reason = reason
        super().__init__(f"SSRF blocked: {reason} ({url})")


# --------------------------------------------------------------------------- #
# configuration
# --------------------------------------------------------------------------- #

_ALLOWED_SCHEMES = {"http", "https"}

# Networks that must never be fetched in production.
_BLOCKED_NETWORKS = [
    ipaddress.ip_network("0.0.0.0/8"),        # "this" network
    ipaddress.ip_network("10.0.0.0/8"),        # RFC 1918 private
    ipaddress.ip_network("100.64.0.0/10"),     # carrier-grade NAT
    ipaddress.ip_network("127.0.0.0/8"),       # loopback
    ipaddress.ip_network("169.254.0.0/16"),    # link-local (incl. cloud metadata)
    ipaddress.ip_network("172.16.0.0/12"),     # RFC 1918 private
    ipaddress.ip_network("192.0.0.0/24"),      # IETF protocol assignments
    ipaddress.ip_network("192.0.2.0/24"),      # documentation (TEST-NET-1)
    ipaddress.ip_network("192.168.0.0/16"),    # RFC 1918 private
    ipaddress.ip_network("198.18.0.0/15"),     # benchmarking
    ipaddress.ip_network("198.51.100.0/24"),   # documentation (TEST-NET-2)
    ipaddress.ip_network("203.0.113.0/24"),    # documentation (TEST-NET-3)
    ipaddress.ip_network("224.0.0.0/4"),       # multicast
    ipaddress.ip_network("240.0.0.0/4"),       # reserved
    ipaddress.ip_network("255.255.255.255/32"),  # broadcast
    # IPv6
    ipaddress.ip_network("::1/128"),           # loopback
    ipaddress.ip_network("fc00::/7"),          # unique local
    ipaddress.ip_network("fe80::/10"),         # link-local
    ipaddress.ip_network("::ffff:0:0/96"),     # IPv4-mapped (checked after unwrap)
]


def _allow_localnet() -> bool:
    """Read the env toggle. True => skip private-IP checks (fixture/demo mode)."""
    return os.environ.get("EVERLINK_ALLOW_LOCALNET", "").strip().lower() in (
        "1", "true", "yes", "on",
    )


def _is_blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """True if *ip* falls inside any blocked network."""
    # Unwrap IPv4-mapped IPv6 (e.g. ::ffff:127.0.0.1) to plain IPv4 for checking.
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return any(ip in net for net in _BLOCKED_NETWORKS)


# --------------------------------------------------------------------------- #
# pure classifier (no DNS, no I/O — unit-testable offline)
# --------------------------------------------------------------------------- #


def classify_blocked(url: str, *, allow_localnet: bool = False) -> str | None:
    """Pure function: return a reason string if *url* is obviously blocked.

    Checks:
      1. Scheme must be http or https.
      2. If the hostname is a literal IP, check it against the blocked list
         (unless *allow_localnet* is True).

    Does NOT resolve DNS — use ``guard_url`` for the full production check.
    Returns ``None`` when the URL passes.
    """
    try:
        parsed = urlparse(url)
    except Exception:
        return "unparseable URL"

    scheme = (parsed.scheme or "").lower()
    if scheme not in _ALLOWED_SCHEMES:
        return f"scheme '{scheme}' not allowed (only http/https)"

    hostname = parsed.hostname or ""
    if not hostname:
        return "empty hostname"

    # Check literal IPs (fast path, no DNS needed).
    if not allow_localnet:
        try:
            ip = ipaddress.ip_address(hostname)
            if _is_blocked_ip(ip):
                return f"resolves to blocked IP {ip}"
        except ValueError:
            pass  # not a literal IP — fine, guard_url will resolve it

    return None


# --------------------------------------------------------------------------- #
# production guard (DNS resolution + IP check)
# --------------------------------------------------------------------------- #


def guard_url(url: str) -> None:
    """Raise ``SsrfBlocked`` if *url* must not be fetched.

    Steps:
      1. Pure classify (scheme + literal IP).
      2. If ALLOW_LOCALNET, stop here (fixture mode trusts localhost).
      3. Resolve hostname via DNS; check ALL returned IPs.
         DNS failure is fail-open (a domain that cannot resolve is harmless —
         the subsequent HTTP request will also fail naturally).
    """
    localnet = _allow_localnet()
    reason = classify_blocked(url, allow_localnet=localnet)
    if reason:
        raise SsrfBlocked(url, reason)

    if localnet:
        return  # fixture/demo mode: skip DNS resolution checks

    # Full DNS resolution check.
    parsed = urlparse(url)
    hostname = parsed.hostname or ""
    try:
        infos = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
    except (socket.gaierror, OSError):
        # DNS failure is fail-open: the actual HTTP request will fail too, and
        # we do not want to block legitimate external URLs during a DNS blip.
        return

    for info in infos:
        ip_str = info[4][0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            continue
        if _is_blocked_ip(ip):
            raise SsrfBlocked(url, f"hostname '{hostname}' resolves to blocked IP {ip}")


# --------------------------------------------------------------------------- #
# httpx integration
# --------------------------------------------------------------------------- #


def httpx_request_guard(request) -> None:
    """An httpx ``event_hooks["request"]`` callback.

    Validates every outgoing request URL (including each redirect hop when
    ``follow_redirects=True``).  Raises ``SsrfBlocked`` (which httpx surfaces
    as the request exception) if the target is internal.
    """
    guard_url(str(request.url))
