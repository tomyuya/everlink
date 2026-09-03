"""Database helpers for EverLink's OWN operational store (spec §5).

Two connection modes:
  * source sites  -> read-only (`read_only=True`); we never write to them here.
  * EverLink store -> read-write, but ONLY into our own tables.

SAFETY GUARD: the source sites' production databases are under a strict
read-only constraint. This module refuses to run schema creation or any write
against a DSN whose host matches a configured source-site host (or an explicit
deny-fragment), so a misconfigured EVERLINK_DATABASE_URL cannot corrupt
production. No production hostname is hardcoded here — the deny-list is derived
from the source-site DSNs in the environment (see .env.example).
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import psycopg

from .model import CheckResult, LinkSlot

# Auto-load everlink/.env so the operator's DSN survives shells that mangle the
# '&' inside Neon query params. Silent no-op if python-dotenv is absent (real
# environment variables still work). Never overrides already-set env vars.
try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:
    pass

# Env vars whose DB hosts are automatically write-forbidden for EverLink.
SOURCE_DSN_VARS = (
    "AETHELGEM_DATABASE_URL", "SANDCART_DATABASE_URL", "HOTDEALS_DATABASE_URL",
)

SLOT_COLUMNS = [
    "id", "site", "article_id", "article_title", "block_id", "block_type",
    "slot_type", "role", "anchor_text", "url", "target_url",
    "surrounding_sentence", "regions", "protected", "status",
]


class ProductionWriteRefused(RuntimeError):
    """Raised when a write/DDL targets a forbidden source/production host."""


def _host_of(dsn: str) -> str:
    """Return the bare lowercase host (no userinfo, no port) of a DSN."""
    try:
        return (urlparse(dsn or "").hostname or "").lower()
    except ValueError:
        return ""


def _forbidden_fragments() -> set[str]:
    """Deny-list = configured source-site hosts + explicit EVERLINK_FORBIDDEN_HOSTS."""
    frags: set[str] = set()
    for var in SOURCE_DSN_VARS:
        h = _host_of(os.environ.get(var, ""))
        if h:
            frags.add(h)
    for frag in os.environ.get("EVERLINK_FORBIDDEN_HOSTS", "").split(","):
        frag = frag.strip().lower()
        if frag:
            frags.add(frag)
    return frags


def _assert_writable(dsn: str) -> None:
    low = (dsn or "").lower()
    host = _host_of(dsn)
    for frag in _forbidden_fragments():
        if frag and (host == frag or frag in low):
            raise ProductionWriteRefused(
                f"refusing EverLink schema/write against read-only source host '{frag}'. "
                f"EVERLINK_DATABASE_URL must point at EverLink's own database, "
                f"never a source site's production instance."
            )


def everlink_dsn() -> str:
    dsn = os.environ.get("EVERLINK_DATABASE_URL", "")
    if not dsn:
        raise RuntimeError(
            "EVERLINK_DATABASE_URL is not set. Point it at EverLink's own Postgres "
            "(see .env.example). It must NOT be a source site's production instance."
        )
    return dsn


def connect(dsn: str, *, read_only: bool = False, connect_timeout: int = 20):
    """Open a psycopg connection. read_only=True sets a session-level guard."""
    conn = psycopg.connect(dsn, connect_timeout=connect_timeout)
    if read_only:
        with conn.cursor() as cur:
            cur.execute("SET default_transaction_read_only = on")
    return conn


def ensure_schema(conn, schema_path: str | os.PathLike | None = None) -> None:
    """Create EverLink tables (idempotent). Refuses forbidden production hosts."""
    dsn = conn.info.dsn or ""
    _assert_writable(dsn)
    path = Path(schema_path) if schema_path else (
        Path(__file__).resolve().parent.parent / "schema.sql"
    )
    sql = path.read_text(encoding="utf-8")
    with conn.cursor() as cur:
        cur.execute(sql)
    conn.commit()


def upsert_link_slots(conn, slots: list[LinkSlot]) -> int:
    """Idempotent insert/update of link_slots rows. Returns rows processed."""
    _assert_writable(conn.info.dsn or "")
    if not slots:
        return 0
    placeholders = ", ".join(["%s"] * len(SLOT_COLUMNS))
    updates = ", ".join(
        f"{c} = EXCLUDED.{c}" for c in SLOT_COLUMNS if c not in ("id",)
    )
    sql = (
        f"INSERT INTO link_slots ({', '.join(SLOT_COLUMNS)}) VALUES ({placeholders}) "
        f"ON CONFLICT (id) DO UPDATE SET {updates}, updated_at = now()"
    )
    rows = [
        (
            s.id, s.site, str(s.article_id), s.article_title, str(s.block_id),
            s.block_type, s.slot_type, s.role, s.anchor_text, s.url, s.target_url,
            s.surrounding_sentence, s.regions, int(s.protected), s.status,
        )
        for s in slots
    ]
    with conn.cursor() as cur:
        cur.executemany(sql, rows)
    conn.commit()
    return len(rows)


def insert_slot_check(conn, result: CheckResult) -> None:
    """Append one probe outcome to slot_checks."""
    import json

    _assert_writable(conn.info.dsn or "")
    chain_json = json.dumps([h.model_dump() for h in result.redirect_chain])
    sql = (
        "INSERT INTO slot_checks (slot_id, l1_status, l1_redirect_chain, "
        "l2_verdict, l2_evidence, final_verdict) "
        "VALUES (%s, %s, %s, %s, %s, %s) "
        "ON CONFLICT (slot_id, checked_at) DO NOTHING"
    )
    with conn.cursor() as cur:
        cur.execute(
            sql,
            (
                result.slot_id, result.l1_status, chain_json,
                result.l2_verdict, result.l2_evidence, result.final_verdict,
            ),
        )
    conn.commit()


def count_slots(conn, site: str | None = None) -> int:
    with conn.cursor() as cur:
        if site:
            cur.execute("SELECT COUNT(*) FROM link_slots WHERE site = %s", (site,))
        else:
            cur.execute("SELECT COUNT(*) FROM link_slots")
        return cur.fetchone()[0]


def insert_audit(conn, agent: str, event: str, payload: str | None = None) -> None:
    """Append one row to audit_log (spec §5).

    ``event`` is one of: tool_call | tool_result | steering_guide | steering_cancel
    | interrupt | write | rollback | notify. Used by the Phase-D ``audit`` hook (pd1),
    the push layer (pd4 ``notify``), and every later write/rollback path — the audit
    trail is append-only.
    """
    _assert_writable(conn.info.dsn or "")
    sql = "INSERT INTO audit_log (agent, event, payload) VALUES (%s, %s, %s)"
    with conn.cursor() as cur:
        cur.execute(sql, (agent, event, payload))
    conn.commit()


def decision_status(conn, decision_id: str) -> Optional[str]:
    """Return a decision card's status (pending|approved|rejected|expired) or None.

    Used by the ``write_gate`` steering hook (spec §4.3-4): a write is refused
    unless the referenced decision_id is exactly ``approved``.
    """
    with conn.cursor() as cur:
        cur.execute("SELECT status FROM decisions WHERE id = %s", (decision_id,))
        row = cur.fetchone()
        return row[0] if row else None
