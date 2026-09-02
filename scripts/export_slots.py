"""Phase A: export LinkSlot CSV snapshots from the three production sites.

Read-only SELECTs against the original projects' DBs (connection strings parsed
from their .env files at runtime; never stored here). Output: data/slots_*.csv
(gitignored) + data/slots_summary.json (committed, for demo/repo transparency).

LinkSlot columns mirror the Spec §5 link_slots table.
"""
import csv
import json
import os
import re
import sys
import time
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

MD_LINK = re.compile(r"\[([^\]]*)\]\((https?://[^)\s]+)\)")
HTML_LINK = re.compile(r"<a\s+[^>]*href=[\"']([^\"']+)[\"'][^>]*>(.*?)</a>", re.S)
TAG = re.compile(r"<[^>]+>")
AFF_HINT = (
    "amazon.", "amzn.", "aliexpress.", "s.click", "pjtra.com", "impactradius",
    "shareasale", "cj.com", "awin", "rakuten", "dp/",
)
DISCLOSURE_KW = ("affiliate", "commission", "partner link", "sponsored", "disclosure")

FIELDS = [
    "id", "site", "article_id", "article_title", "block_id", "block_type",
    "slot_type", "role", "anchor_text", "url", "regions", "protected",
]


def parse_env(path: str, key: str) -> str:
    raw = Path(path).read_text(encoding="utf-8")
    m = re.search(rf'^{key}="?(.+?)"?\s*$', raw, re.M)
    return m.group(1) if m else ""


def classify(url: str) -> str:
    if url.startswith("/"):
        return "internal"
    low = url.lower()
    return "commercial" if any(h in low for h in AFF_HINT) else "reference"


def links_in_text(text: str):
    """Yield (anchor, url) from markdown + html links."""
    if not text:
        return
    for anchor, url in MD_LINK.findall(text):
        yield anchor.strip(), url
    for url, inner in HTML_LINK.findall(text):
        yield TAG.sub("", inner).strip(), url


def protected_flag(*texts) -> int:
    blob = " ".join(t or "" for t in texts).lower()
    return 1 if any(k in blob for k in DISCLOSURE_KW) else 0


def extract_aeg(cur) -> list:
    rows = []
    cur.execute(
        """
        SELECT a.id, a.title, b.id, b.block_type, b.content, b.cta_button_url, b.product_ids
        FROM content_articleblock b
        JOIN content_article a ON a.id = b.article_id
        WHERE a.status = 'published'
          AND (b.block_type IN ('product_card', 'inline_product', 'product_grid', 'cta_box')
               OR COALESCE(b.content, '') ~ 'https?://'
               OR COALESCE(b.cta_button_url, '') <> '')
        """
    )
    blocks = cur.fetchall()
    prod_ids = {pid for _, _, _, _, _, _, pids in blocks for pid in (pids or [])}
    products = {}
    if prod_ids:
        cur.execute(
            "SELECT id, name, affiliate_url, deep_link, amazon_url "
            "FROM content_product WHERE id = ANY(%s)",
            (list(prod_ids),),
        )
        for pid, name, aff, deep, amz in cur.fetchall():
            products[pid] = (name or f"product:{pid}", aff or deep or amz or "")
    for aid, title, bid, btype, content, cta_url, pids in blocks:
        prot = protected_flag(content, cta_url)
        if btype in ("product_card", "inline_product", "product_grid"):
            for i, pid in enumerate(pids or []):
                name, url = products.get(pid, (f"product:{pid}", ""))
                if not url:
                    continue
                rows.append({
                    "id": f"aethelgem:{aid}:{bid}:{i}", "site": "aethelgem",
                    "article_id": aid, "article_title": title, "block_id": bid,
                    "block_type": btype, "slot_type": "component", "role": "",
                    "anchor_text": name[:120], "url": url, "regions": "", "protected": prot,
                })
        elif btype == "cta_box" and cta_url:
            rows.append({
                "id": f"aethelgem:{aid}:{bid}:cta", "site": "aethelgem",
                "article_id": aid, "article_title": title, "block_id": bid,
                "block_type": btype, "slot_type": classify(cta_url), "role": "",
                "anchor_text": (content or "")[:80], "url": cta_url,
                "regions": "", "protected": prot,
            })
        else:
            for i, (anchor, url) in enumerate(links_in_text(content)):
                rows.append({
                    "id": f"aethelgem:{aid}:{bid}:{i}", "site": "aethelgem",
                    "article_id": aid, "article_title": title, "block_id": bid,
                    "block_type": btype, "slot_type": classify(url), "role": "",
                    "anchor_text": anchor[:120], "url": url, "regions": "",
                    "protected": prot,
                })
    return rows


def extract_sandcart(cur) -> list:
    rows = []
    cur.execute('SELECT id, slug, title, content FROM blog_post')
    for pid, slug, title, content in cur.fetchall():
        sections = (content or {}).get("sections", []) if isinstance(content, dict) else []
        for i, sec in enumerate(sections):
            if not isinstance(sec, dict):
                continue
            plink = sec.get("product_link") or ""
            if plink:
                rows.append({
                    "id": f"sandcart:{pid}:sec{i}:pl", "site": "sandcart",
                    "article_id": pid, "article_title": title, "block_id": f"sec{i}",
                    "block_type": "section_product_link", "slot_type": "internal",
                    "role": "", "anchor_text": sec.get("anchor_text") or "",
                    "url": plink, "regions": "", "protected": 0,
                })
            for j, (anchor, url) in enumerate(links_in_text(sec.get("content") or "")):
                rows.append({
                    "id": f"sandcart:{pid}:sec{i}:{j}", "site": "sandcart",
                    "article_id": pid, "article_title": title, "block_id": f"sec{i}",
                    "block_type": "section_content", "slot_type": classify(url),
                    "role": "", "anchor_text": anchor[:120], "url": url,
                    "regions": "", "protected": protected_flag(sec.get("content")),
                })
    return rows


AMZ_DOMAIN = {
    "us": "amazon.com", "ca": "amazon.ca", "uk": "amazon.co.uk", "es": "amazon.es",
    "de": "amazon.de", "fr": "amazon.fr", "it": "amazon.it", "jp": "amazon.co.jp",
}


def extract_hotdeals(cur) -> list:
    """hotdeals link assets live in products[] jsonb (asin -> amazon dp URL at
    render time), not in content HTML. SQL-side expansion over ~1k articles is
    cheap. Also capture the rare inline <a href> links in content."""
    rows = []
    # 1) product component slots from products[] (region-aware amazon domain)
    cur.execute(
        """
        SELECT g.id, left(g.title, 200),
               (t.p)->>'asin',
               left(COALESCE((t.p)->>'title', (t.p)->>'brand', ''), 120),
               COALESCE((t.p)->>'region', ''),
               t.ord
        FROM generated_articles g
        CROSS JOIN LATERAL jsonb_array_elements(g.products)
             WITH ORDINALITY AS t(p, ord)
        WHERE g.status = 'published'
          AND jsonb_typeof(g.products) = 'array'
          AND COALESCE((t.p)->>'asin', '') <> ''
          AND COALESCE((t.p)->>'network', '') = 'amazon'
        """
    )
    for aid, title, asin, anchor, region, idx in cur.fetchall():
        domain = AMZ_DOMAIN.get((region or "us").lower(), "amazon.com")
        url = f"https://www.{domain}/dp/{asin}"
        rows.append({
            "id": f"hotdeals:{aid}:p{idx}", "site": "hotdeals",
            "article_id": aid, "article_title": title, "block_id": f"products[{idx}]",
            "block_type": "product_entry", "slot_type": "component", "role": "",
            "anchor_text": anchor or asin, "url": url,
            "regions": region or "", "protected": 0,
        })
    # 2) rare inline <a href> links in content HTML
    cur.execute(
        """
        SELECT g.id, left(g.title, 200),
               m[1], regexp_replace(m[2], '<[^>]+>', '', 'g'),
               (CASE WHEN m[2] ~* 'affiliate|commission|partner link|sponsored|disclosure'
                     THEN 1 ELSE 0 END)
        FROM generated_articles g
        CROSS JOIN LATERAL regexp_matches(
            g.content, '<a\\s[^>]*href=["'']([^"'']+)["''][^>]*>(.*?)</a>', 'g') AS m
        WHERE g.status = 'published' AND COALESCE(g.content, '') <> ''
        """
    )
    for n, (aid, title, url, anchor, prot) in enumerate(cur.fetchall()):
        rows.append({
            "id": f"hotdeals:{aid}:html:{n}", "site": "hotdeals",
            "article_id": aid, "article_title": title, "block_id": f"html:{n}",
            "block_type": "html_content", "slot_type": classify(url),
            "role": "", "anchor_text": (anchor or "")[:120], "url": url,
            "regions": "", "protected": prot,
        })
    return rows


def main() -> int:
    DATA.mkdir(exist_ok=True)
    force = os.environ.get("EVERLINK_FORCE") == "1" or "--force" in sys.argv
    # Source .env paths are supplied via environment (see .env.example) so this
    # public repo never hardcodes the maintainer's local filesystem layout.
    sources = [
        ("aethelgem", os.environ.get("EVERLINK_AEG_ENV", ""), "DATABASE_URL", extract_aeg),
        ("sandcart", os.environ.get("EVERLINK_SANDCART_ENV", ""), "DATABASE_URL", extract_sandcart),
        ("hotdeals", os.environ.get("EVERLINK_HOTDEALS_ENV", ""), "DATABASE_URL", extract_hotdeals),
    ]
    for site, env_path, key, fn in sources:
        out = DATA / f"slots_{site}.csv"
        if out.exists() and out.stat().st_size > 0 and not force:
            print(f"[cache] {site}: {out.name} exists, skipping "
                  f"(set EVERLINK_FORCE=1 or --force to re-export)", flush=True)
            continue
        if not env_path or not Path(env_path).exists():
            print(f"[skip] {site}: set EVERLINK_{site.split('_')[0].upper()}_ENV "
                  f"to that project's .env path (got {env_path!r})", flush=True)
            continue
        url = parse_env(env_path, key)
        if not url:
            print(f"[skip] {site}: no {key} in {env_path}", flush=True)
            continue
        t0 = time.time()
        with psycopg.connect(url, connect_timeout=20) as conn:
            with conn.cursor() as cur:
                cur.execute("SET default_transaction_read_only = on")
                rows = fn(cur)
        with open(out, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=FIELDS)
            w.writeheader()
            w.writerows(rows)
        print(f"[ok] {site}: {len(rows)} slots -> {out.name} ({time.time()-t0:.1f}s)", flush=True)

    # Aggregate from the per-site CSVs (so cached sites are included too).
    summary = {}
    total = 0
    with open(DATA / "slots_all.csv", "w", newline="", encoding="utf-8") as fa:
        wall = csv.DictWriter(fa, fieldnames=FIELDS)
        wall.writeheader()
        for site, _, _, _ in sources:
            p = DATA / f"slots_{site}.csv"
            if not p.exists():
                continue
            with open(p, encoding="utf-8", newline="") as f:
                rows = list(csv.DictReader(f))
            if not rows:
                continue
            by_type = {}
            for r in rows:
                by_type[r["slot_type"]] = by_type.get(r["slot_type"], 0) + 1
                wall.writerow({k: r.get(k, "") for k in FIELDS})
            summary[site] = {
                "slots": len(rows),
                "by_slot_type": by_type,
                "protected": sum(int(r["protected"]) for r in rows if r.get("protected")),
            }
            total += len(rows)
    summary["_total"] = {"slots": total}
    (DATA / "slots_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8")
    print(f"[ok] total {total} slots across {len(summary)-1} sites; "
          f"summary -> data/slots_summary.json", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
