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

import json
import os
from datetime import datetime, timezone
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
    | interrupt | notify | write | write_refused | verify | rollback | dead_letter
    | worker_error. Used by the Phase-D ``audit`` hook (pd1), the push layer (pd4
    ``notify``), and the Writer / worker path (pe1: ``write`` / ``write_refused`` /
    ``verify`` / ``rollback`` / ``dead_letter``) — the audit trail is append-only.
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


# --------------------------------------------------------------------------- #
# Writer write-path (spec §5 write_snapshots). The MUTATING helpers below run
# inside the CALLER's transaction (``with conn.transaction():``) and deliberately
# DO NOT commit — so snapshot + apply + rollback are atomic (spec §5: "write-back
# is a single transaction"; no half-written state). All are EverLink-own-DB only.
# --------------------------------------------------------------------------- #
CONTENT_FIELDS = ("url", "target_url", "anchor_text", "surrounding_sentence", "status")


def _row_to_slot(row) -> LinkSlot:
    cols = SLOT_COLUMNS + ["created_at", "updated_at"]
    raw = dict(zip(cols, row)) if not isinstance(row, dict) else row
    return LinkSlot(
        id=raw["id"], site=raw["site"], article_id=str(raw.get("article_id") or ""),
        article_title=raw.get("article_title") or "", block_id=str(raw.get("block_id") or ""),
        block_type=raw.get("block_type") or "", slot_type=raw["slot_type"],
        role=raw.get("role"), anchor_text=raw.get("anchor_text"), url=raw["url"],
        target_url=raw.get("target_url"), surrounding_sentence=raw.get("surrounding_sentence"),
        regions=raw.get("regions"), protected=int(raw.get("protected") or 0),
        status=raw.get("status") or "active",
    )


def fetch_slot(conn, slot_id: str) -> Optional[LinkSlot]:
    """Read ONE link_slots row from EverLink's own store (read-only)."""
    cols = ", ".join(SLOT_COLUMNS)
    with conn.cursor() as cur:
        cur.execute(f"SELECT {cols} FROM link_slots WHERE id = %s", (slot_id,))
        row = cur.fetchone()
        return _row_to_slot(row) if row else None


def fetch_slot_content(conn, slot_id: str) -> Optional[dict]:
    """The mutable content fields of a slot (the write-snapshot ``before`` state)."""
    cols = ", ".join(CONTENT_FIELDS)
    with conn.cursor() as cur:
        cur.execute(f"SELECT {cols} FROM link_slots WHERE id = %s", (slot_id,))
        row = cur.fetchone()
        return dict(zip(CONTENT_FIELDS, row)) if row else None


def update_slot_content(conn, slot_id: str, content: dict) -> bool:
    """UPDATE a slot's mutable content fields. Runs in the caller's transaction."""
    _assert_writable(conn.info.dsn or "")
    keys = [k for k in CONTENT_FIELDS if k in content]
    if not keys:
        return False
    assigns = ", ".join(f"{k} = %s" for k in keys)
    sql = f"UPDATE link_slots SET {assigns}, updated_at = now() WHERE id = %s"
    params = tuple(content[k] for k in keys) + (slot_id,)
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.rowcount > 0


def insert_write_snapshot(conn, slot_id: str, decision_id: str,
                          before: dict, after: dict) -> int:
    """Record a before/after write snapshot; returns its id. Caller's transaction."""
    _assert_writable(conn.info.dsn or "")
    sql = ("INSERT INTO write_snapshots (slot_id, decision_id, before_json, after_json) "
           "VALUES (%s, %s, %s, %s) RETURNING id")
    with conn.cursor() as cur:
        cur.execute(sql, (slot_id, decision_id,
                          json.dumps(before, default=str), json.dumps(after, default=str)))
        row = cur.fetchone()
        return int(row[0]) if row else 0


def fetch_latest_snapshot(conn, decision_id: str, slot_id: str) -> Optional[dict]:
    """The most recent write_snapshot for (decision, slot), or None (read-only)."""
    sql = ("SELECT id, before_json, after_json, applied_at, rolled_back_at "
           "FROM write_snapshots WHERE decision_id = %s AND slot_id = %s "
           "ORDER BY id DESC LIMIT 1")
    with conn.cursor() as cur:
        cur.execute(sql, (decision_id, slot_id))
        row = cur.fetchone()
        if not row:
            return None
        return {"id": row[0], "before_json": row[1], "after_json": row[2],
                "applied_at": row[3], "rolled_back_at": row[4]}


def mark_snapshot_rolled_back(conn, snapshot_id: int) -> bool:
    """Stamp ``rolled_back_at`` on a snapshot. Runs in the caller's transaction."""
    _assert_writable(conn.info.dsn or "")
    sql = "UPDATE write_snapshots SET rolled_back_at = now() WHERE id = %s AND rolled_back_at IS NULL"
    with conn.cursor() as cur:
        cur.execute(sql, (snapshot_id,))
        return cur.rowcount > 0


# --------------------------------------------------------------------------- #
# Control plane (board /settings + the nightly cron gate). All writes stay in
# EverLink's OWN store; the settings row is the operator's single knob panel.
# --------------------------------------------------------------------------- #
DEFAULT_SETTINGS = {
    "rotation_cycle_days": 30,   # full-pass window: every active slot probed once
    "run_hour_utc": 3,           # which hourly heartbeat actually runs the chain
    "enabled": True,             # board kill-switch for the cron
    "run_requested_at": None,    # board "run now" request (consumed by next fire)
    "run_requested_by": None,
}


def default_settings() -> dict:
    return dict(DEFAULT_SETTINGS)


def get_settings(conn) -> dict:
    """The single 'main' settings row merged over defaults (missing row = defaults)."""
    with conn.cursor() as cur:
        cur.execute("SELECT value FROM settings WHERE id = 'main'")
        row = cur.fetchone()
    if not row:
        return default_settings()
    try:
        stored = json.loads(row[0])
    except (TypeError, ValueError):
        return default_settings()
    merged = default_settings()
    merged.update({k: v for k, v in stored.items() if k in merged})
    return merged


def set_settings(conn, patch: dict, by: str = "agent") -> dict:
    """Read-modify-write the 'main' settings row; unknown keys are ignored."""
    _assert_writable(conn.info.dsn or "")
    current = get_settings(conn)
    for k, v in patch.items():
        if k in current:
            current[k] = v
    current["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    current["updated_by"] = by
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO settings (id, value, updated_at) VALUES ('main', %s, now()) "
            "ON CONFLICT (id) DO UPDATE SET value = EXCLUDED.value, updated_at = now()",
            (json.dumps(current, default=str),))
    conn.commit()
    return current


def count_active_slots(conn) -> dict:
    """site -> active slot count (the rotation budget denominator)."""
    with conn.cursor() as cur:
        cur.execute("SELECT site, count(*) FROM link_slots WHERE status = 'active' "
                    "GROUP BY site")
        return {r[0]: int(r[1]) for r in cur.fetchall()}


def fetch_due_slots(conn, site: str, limit: int) -> list[LinkSlot]:
    """Least-recently-checked active slots first (never-checked = most due)."""
    cols = ", ".join(SLOT_COLUMNS)
    sql = (f"SELECT {cols} FROM link_slots WHERE site = %s AND status = 'active' "
           "ORDER BY last_checked_at NULLS FIRST, id LIMIT %s")
    with conn.cursor() as cur:
        cur.execute(sql, (site, max(1, int(limit))))
        return [_row_to_slot(r) for r in cur.fetchall()]


def touch_last_checked(conn, slot_ids: list) -> int:
    """Stamp ``last_checked_at = now()`` on the slots a scan just probed."""
    _assert_writable(conn.info.dsn or "")
    if not slot_ids:
        return 0
    with conn.cursor() as cur:
        cur.execute("UPDATE link_slots SET last_checked_at = now() WHERE id = ANY(%s)",
                    (list(slot_ids),))
        return cur.rowcount


def insert_run(conn, kind: str, status: str, reason: str = "") -> int:
    """Open a nightly_runs row (kind: run | heartbeat); returns its id."""
    _assert_writable(conn.info.dsn or "")
    with conn.cursor() as cur:
        cur.execute("INSERT INTO nightly_runs (kind, status, reason) "
                    "VALUES (%s, %s, %s) RETURNING id", (kind, status, reason))
        run_id = int(cur.fetchone()[0])
    conn.commit()
    return run_id


def finish_run(conn, run_id: int, status: str, summary: dict | None = None) -> None:
    """Close a nightly_runs row with its final status + JSON summary."""
    _assert_writable(conn.info.dsn or "")
    with conn.cursor() as cur:
        cur.execute("UPDATE nightly_runs SET status = %s, finished_at = now(), "
                    "summary = %s WHERE id = %s",
                    (status,
                     json.dumps(summary, default=str) if summary is not None else None,
                     run_id))
    conn.commit()

