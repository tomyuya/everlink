"""Adapter CSV loading: a first-party site's INTERNAL relative URLs are absolutized
against the site's PUBLIC ORIGIN, which the DEPLOYER configures via env — never
hardcoded in this open-source repo.

Regression history: 76 sandcart/FlashDeals slots were exported as bare `/products/...`
paths (no scheme). Stored as-is, every probe hit the SSRF guard's "scheme '' not
allowed" wall -> needs_human_recheck, and the Judge proposed destructive edits for a
"broken link" that was never broken. The fix resolves each relative URL against the
site's configured origin at ingestion. "sandcart" is the maintainer's internal codename
for the FlashDeals dropshipping storefront — a dogfooding EXAMPLE key, not an Amazon
affiliate; a deployer substitutes their own site key + origin.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from everlink import adapters  # noqa: E402

_HDR = ("id,site,article_id,article_title,block_id,block_type,slot_type,role,"
        "anchor_text,url,regions,protected")
_ORIGIN = "https://flashdeals.today"


def _write_csv(tmp_path, name, rows):
    p = tmp_path / name
    p.write_text(_HDR + "\n" + "\n".join(rows) + "\n", encoding="utf-8")
    return p


def test_absolutize_prefixes_relative_and_passes_absolute_through():
    # relative internal link gains the configured origin
    assert adapters.absolutize_slot_url("/products/waist-fan-6000mah", _ORIGIN) == (
        "https://flashdeals.today/products/waist-fan-6000mah")
    # an already-absolute URL is untouched (no double-prefix, no clobber)
    assert adapters.absolutize_slot_url(
        "https://www.amazon.de/dp/B00BCE30RS?tag=x", _ORIGIN) == (
        "https://www.amazon.de/dp/B00BCE30RS?tag=x")
    # no configured origin (None) => returned as-is; empty url => empty
    assert adapters.absolutize_slot_url("/p", None) == "/p"
    assert adapters.absolutize_slot_url("", _ORIGIN) == ""


def test_resolve_origin_reads_env_symmetric_with_dsn(monkeypatch):
    monkeypatch.setenv("SANDCART_PUBLIC_ORIGIN", _ORIGIN)
    assert adapters.resolve_origin("sandcart") == _ORIGIN
    monkeypatch.delenv("SANDCART_PUBLIC_ORIGIN", raising=False)
    # unset => None (the repo never guesses a domain)
    assert adapters.resolve_origin("sandcart") is None


def test_relative_url_absolutized_on_load_when_origin_configured(tmp_path, monkeypatch):
    monkeypatch.setenv("SANDCART_PUBLIC_ORIGIN", _ORIGIN)
    _write_csv(tmp_path, "slots_sandcart.csv", [
        'sandcart:a1:sec0:pl,sandcart,a1,"Best Portable Fans 2026",sec0,'
        'section_product_link,internal,,quiet 40dBA waist fan,'
        '/products/waist-fan-6000mah,,0',
    ])
    slots = adapters.load_slots("sandcart", data_dir=tmp_path)
    assert len(slots) == 1
    assert slots[0].url == "https://flashdeals.today/products/waist-fan-6000mah"


def test_relative_url_left_as_is_when_origin_unconfigured(tmp_path, monkeypatch):
    # HONEST behaviour: with no origin configured the relative URL is NOT guessed —
    # it stays relative so the missing-config surfaces instead of a fabricated domain.
    monkeypatch.delenv("SANDCART_PUBLIC_ORIGIN", raising=False)
    _write_csv(tmp_path, "slots_sandcart.csv", [
        'sandcart:a1:sec0:pl,sandcart,a1,"T",sec0,section_product_link,internal,,'
        'fan,/products/waist-fan-6000mah,,0',
    ])
    slots = adapters.load_slots("sandcart", data_dir=tmp_path)
    assert slots[0].url == "/products/waist-fan-6000mah"


def test_aethelgem_absolute_affiliate_url_survives_load_unchanged(tmp_path, monkeypatch):
    monkeypatch.delenv("AETHELGEM_PUBLIC_ORIGIN", raising=False)
    _write_csv(tmp_path, "slots_aethelgem.csv", [
        'aethelgem:1:2:0,aethelgem,1,"T",2,product_card,component,,desk,'
        'https://www.amazon.de/dp/B00BCE30RS?tag=aethelgem2026-20,,0',
    ])
    slots = adapters.load_slots("aethelgem", data_dir=tmp_path)
    assert slots[0].url == "https://www.amazon.de/dp/B00BCE30RS?tag=aethelgem2026-20"


def test_merged_all_csv_absolutizes_per_row_site(tmp_path, monkeypatch):
    # slots_all.csv mixes sites; each row resolves by ITS OWN site's origin.
    monkeypatch.setenv("SANDCART_PUBLIC_ORIGIN", _ORIGIN)
    monkeypatch.delenv("AETHELGEM_PUBLIC_ORIGIN", raising=False)
    _write_csv(tmp_path, "slots_all.csv", [
        'sandcart:a1:sec0:pl,sandcart,a1,"Fans",sec0,section_product_link,internal,,'
        'fan,/products/waist-fan-6000mah,,0',
        'aethelgem:1:2:0,aethelgem,1,"T",2,product_card,component,,desk,'
        'https://www.amazon.de/dp/B00BCE30RS?tag=aethelgem2026-20,,0',
    ])
    by_site = {s.site: s.url for s in adapters.load_all(data_dir=tmp_path)}
    assert by_site["sandcart"] == "https://flashdeals.today/products/waist-fan-6000mah"
    assert by_site["aethelgem"] == "https://www.amazon.de/dp/B00BCE30RS?tag=aethelgem2026-20"
