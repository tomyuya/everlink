"""Weekly report aggregation — the Python MIRROR of the board's ``weeklyStats``.

``board/lib/queries.ts`` computes the /report page's numbers with five aggregates over
the last N days (its own comment: "pe3 mirrors this SQL"). This module runs the SAME
five queries — same tables, same time windows, same GROUP BYs, same null-handling — so
the agent's scheduled digest (cli ``report``) reports numbers IDENTICAL to the board's
/report page and /api/report route. One SQL shape, two consumers: no drift between what
the operator sees in the inbox and what the weekly email says.

HONESTY: these are plain read-only COUNT/SUM aggregates over EverLink's OWN store
(``decisions`` + ``audit_log``). No figure is invented or extrapolated; an empty window
yields zeros and the composer reports "nothing to report" rather than padding. Reads are
always safe, so this never needs the write guard (``db._assert_writable``).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from . import notify


def _since(days: int) -> datetime:
    """Window start = now - ``days`` (UTC), mirroring the board's ``Date.now() - days*86400s``."""
    return datetime.now(timezone.utc) - timedelta(days=max(1, int(days)))


def _group_counts(conn, sql: str, since: datetime) -> dict[str, int]:
    """Run a ``SELECT key, count(*) ... GROUP BY key`` and fold it into ``{key: n}``.

    A NULL key becomes ``"unknown"`` — exactly the board's ``String(r[key] ?? "unknown")``.
    """
    with conn.cursor() as cur:
        cur.execute(sql, (since,))
        out: dict[str, int] = {}
        for row in cur.fetchall():
            key = row[0] if row[0] is not None else "unknown"
            out[str(key)] = int(row[1] or 0)
        return out


def build_weekly_report(conn, *, days: int = 7) -> notify.WeeklyReport:
    """Aggregate the last ``days`` of EverLink activity into a ``notify.WeeklyReport``.

    The five queries below are line-for-line the board's ``weeklyStats``:
      1. decisions by status   (created_at in window)
      2. decisions by action   (created_at in window; ``proposal::jsonb ->> 'action'``)
      3. audit_log by event    (ts in window)
      4. links healed + slots  (status='applied', decided_at in window)
      5. decisions decided     (decided_at in window; approved/rejected/applied)
    ``decisions_created`` is the sum of the by-status counts, matching the board exactly.
    """
    since = _since(days)
    by_status = _group_counts(
        conn,
        "SELECT status, count(*) FROM decisions WHERE created_at >= %s GROUP BY status",
        since)
    by_action = _group_counts(
        conn,
        "SELECT proposal::jsonb ->> 'action', count(*) FROM decisions "
        "WHERE created_at >= %s GROUP BY 1",
        since)
    audit_events = _group_counts(
        conn,
        "SELECT event, count(*) FROM audit_log WHERE ts >= %s GROUP BY event",
        since)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT count(*), COALESCE(sum(jsonb_array_length(affected_slot_ids::jsonb)), 0) "
            "FROM decisions WHERE status = 'applied' AND decided_at >= %s", (since,))
        healed_row = cur.fetchone() or (0, 0)
        cur.execute(
            "SELECT count(*) FROM decisions WHERE decided_at >= %s "
            "AND status IN ('approved', 'rejected', 'applied')", (since,))
        decided_row = cur.fetchone() or (0,)
    return notify.WeeklyReport(
        window_days=max(1, int(days)),
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        by_status=by_status,
        by_action=by_action,
        audit_events=audit_events,
        links_healed=int(healed_row[0] or 0),
        slots_affected_by_applied=int(healed_row[1] or 0),
        decisions_created=sum(by_status.values()),
        decisions_decided=int(decided_row[0] or 0),
    )
