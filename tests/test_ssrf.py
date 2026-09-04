"""SSRF guard unit tests — PURE classify_blocked (no network, no DNS).

Tests the pure function ``classify_blocked`` with allow_localnet=False/True.
The production DNS-resolving ``guard_url`` is implicitly tested by the existing
integration tests (test_generic/test_evals/test_agents) which run through
fixtures.make_server (ALLOW_LOCALNET=1) and would break if the guard's
scheme check were over-aggressive.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from everlink.ssrf import classify_blocked  # noqa: E402


# ---- blocked schemes --------------------------------------------------------
def test_blocks_file_scheme():
    assert classify_blocked("file:///etc/passwd") is not None


def test_blocks_gopher_scheme():
    assert classify_blocked("gopher://evil.com/payload") is not None


def test_blocks_data_scheme():
    assert classify_blocked("data:text/html,<script>alert(1)</script>") is not None


def test_blocks_javascript_scheme():
    assert classify_blocked("javascript:void(0)") is not None


def test_blocks_ftp_scheme():
    assert classify_blocked("ftp://internal.corp/secrets") is not None


# ---- blocked IPs (production mode: allow_localnet=False) ---------------------
def test_blocks_loopback_ipv4():
    assert classify_blocked("http://127.0.0.1/admin") is not None


def test_blocks_loopback_ipv4_alt():
    assert classify_blocked("http://127.0.0.2:8080/") is not None


def test_blocks_private_10():
    assert classify_blocked("http://10.0.0.1/internal") is not None


def test_blocks_private_172():
    assert classify_blocked("http://172.16.0.1/") is not None


def test_blocks_private_192():
    assert classify_blocked("http://192.168.1.1/router") is not None


def test_blocks_link_local_metadata():
    """The #1 cloud SSRF target: AWS/GCP/Azure instance metadata."""
    assert classify_blocked("http://169.254.169.254/latest/meta-data/") is not None


def test_blocks_ipv6_loopback():
    assert classify_blocked("http://[::1]/admin") is not None


def test_blocks_ipv6_link_local():
    assert classify_blocked("http://[fe80::1]/") is not None


def test_blocks_zero_address():
    assert classify_blocked("http://0.0.0.0/") is not None


# ---- allowed URLs (production mode) ------------------------------------------
def test_allows_public_https():
    assert classify_blocked("https://www.amazon.com/dp/B09XS7JWHH") is None


def test_allows_public_http():
    assert classify_blocked("http://example.com/page") is None


def test_allows_hostname_url():
    """Non-IP hostnames pass the pure check (DNS resolution is guard_url's job)."""
    assert classify_blocked("https://some-random-site.io/page") is None


# ---- allow_localnet mode (fixture/demo) --------------------------------------
def test_localnet_allows_loopback():
    assert classify_blocked("http://127.0.0.1:8787/ok", allow_localnet=True) is None


def test_localnet_allows_private():
    assert classify_blocked("http://192.168.1.100/", allow_localnet=True) is None


def test_localnet_still_blocks_bad_scheme():
    """Even in localnet mode, non-http(s) schemes are refused."""
    assert classify_blocked("file:///etc/shadow", allow_localnet=True) is not None


def test_localnet_still_blocks_gopher():
    assert classify_blocked("gopher://127.0.0.1:25/", allow_localnet=True) is not None


# ---- edge cases --------------------------------------------------------------
def test_blocks_empty_hostname():
    assert classify_blocked("http:///path") is not None


def test_allows_https_with_port():
    assert classify_blocked("https://example.com:8443/api") is None


ALL = [v for k, v in sorted(globals().items()) if k.startswith("test_")]

if __name__ == "__main__":
    failed = 0
    for fn in ALL:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception as e:
            failed += 1
            print(f"FAIL {fn.__name__}: {e}")
    print(f"\n{len(ALL)-failed}/{len(ALL)} passed")
    sys.exit(1 if failed else 0)
