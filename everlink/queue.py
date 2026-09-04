"""The durable decision queue (spec §5 ``decisions``) — the ASYNC human-in-the-loop
track (README: "an asynchronous durable decision-queue track for production").

Flow::

    scan -> Judge proposals -> build_decision_cards -> enqueue(pending)
         -> [board / notifications surface the card]  (pd3 / pd4)
         -> human approve / reject                     (pd3 panel)
         -> worker claims approved -> writer applies   (pe1) -> mark_applied

Two implementations share ONE interface (``DecisionStore``) so the worker, the
board backend and the tests are storage-agnostic:
  * ``InMemoryDecisionStore`` — offline dev / CI / demos (no DB).
  * ``DbDecisionStore``       — production, backed by the ``decisions`` table.

Card lifecycle: pending -> approved -> applied  (or -> rejected / -> expired).
``applied`` is the terminal success state that stops the worker re-claiming a card.
Claiming is at-least-once: ``claim_next_approved`` does NOT change status, so a
handler crash leaves the card approved and it is retried on the next poll; the
worker calls ``mark_applied`` only after the handler succeeds.
"""
from __future__ import annotations

import abc
import json
from datetime import datetime, timezone
from typing import Optional

from .model import Decision, Proposal

# statuses a card can occupy (spec §5 + EverLink's terminal 'applied')
PENDING, APPROVED, REJECTED, EXPIRED, APPLIED = (
    "pending", "approved", "rejected", "expired", "applied")


# --------------------------------------------------------------------------- #
# pure (de)serialization — shared by the DB store and its tests
# --------------------------------------------------------------------------- #
def decision_to_row(card: Decision) -> tuple:
    """Flatten a Decision into the ``decisions`` column order (JSON where needed)."""
    return (
        card.id,
        json.dumps(card.affected_slot_ids),
        json.dumps(card.proposal.model_dump()),
        card.status,
        card.reject_reason,
    )


def row_to_decision(row) -> Decision:
    """Rebuild a Decision from a SELECT of (id, affected_slot_ids, proposal,
    status, reject_reason). affected_slot_ids/proposal are JSON text."""
    dec_id, slot_ids, proposal, status, reject_reason = row[0], row[1], row[2], row[3], row[4]
    if isinstance(slot_ids, str):
        slot_ids = json.loads(slot_ids)
    if isinstance(proposal, str):
        proposal = json.loads(proposal)
    return Decision(
        id=dec_id,
        affected_slot_ids=list(slot_ids),
        proposal=Proposal.model_validate(proposal),
        status=status,
        reject_reason=reject_reason,
    )


# --------------------------------------------------------------------------- #
# interface
# --------------------------------------------------------------------------- #
class DecisionStore(abc.ABC):
    """Storage-agnostic decision queue. All methods are synchronous."""

    @abc.abstractmethod
    def enqueue(self, cards: list[Decision]) -> int:
        """Insert pending cards; idempotent by id (an existing card is left as-is so
        a re-scan never resurrects a decided card). Returns newly-enqueued count."""

    @abc.abstractmethod
    def list_pending(self, limit: int = 50) -> list[Decision]:
        """FIFO list of pending cards (the board inbox)."""

    @abc.abstractmethod
    def list_by_status(self, status: Optional[str] = None, limit: int = 100) -> list[Decision]:
        """Cards filtered by ``status`` (None = all), oldest first — the board's read
        model (pd3) and the CLI's ``decisions`` inspection surface."""

    @abc.abstractmethod
    def get(self, decision_id: str) -> Optional[Decision]:
        """One card by id, or None."""

    @abc.abstractmethod
    def approve(self, decision_id: str) -> bool:
        """pending -> approved. Returns False if not found / not pending."""

    @abc.abstractmethod
    def reject(self, decision_id: str, reason: str = "") -> bool:
        """pending -> rejected (records the reason). False if not found / not pending."""

    @abc.abstractmethod
    def reject_approved(self, decision_id: str, reason: str = "") -> bool:
        """approved -> rejected (terminal DEAD-LETTER). The pe1 writer handler calls
        this when a decisive failure (write refused by the guard, or rolled back after
        verify_fix failed) means the card must NOT be retried: it flips the claimed
        card to ``rejected`` with an honest machine reason, so the worker's subsequent
        ``mark_applied`` is a no-op instead of an infinite retry loop. False if not
        found / not approved."""

    @abc.abstractmethod
    def claim_next_approved(self) -> Optional[Decision]:
        """Oldest approved card (FIFO) WITHOUT changing its status, or None."""

    @abc.abstractmethod
    def mark_applied(self, decision_id: str) -> bool:
        """approved -> applied (terminal). False if not found / not approved."""

    @abc.abstractmethod
    def counts(self) -> dict[str, int]:
        """{status: n} across all cards."""


# --------------------------------------------------------------------------- #
# in-memory implementation (offline dev / CI / demos)
# --------------------------------------------------------------------------- #
class InMemoryDecisionStore(DecisionStore):
    """Dict-backed store preserving insertion order. Not persistent, not shared.

    Mirrors ``DbDecisionStore``'s claim ordering (FIFO by *decision* time, tie-break
    by creation): ``Decision`` carries no timestamp, so approval order is tracked in
    a side sequence — ``claim_next_approved`` returns the earliest-approved card, not
    merely the first approved one in insertion order.
    """

    def __init__(self) -> None:
        self._cards: dict[str, Decision] = {}
        self._decided_seq: dict[str, int] = {}   # decision_id -> approval order
        self._seq = 0

    def enqueue(self, cards: list[Decision]) -> int:
        added = 0
        for c in cards:
            if c.id in self._cards:
                continue                      # idempotent: never overwrite a decided card
            self._cards[c.id] = c.model_copy(deep=True)
            added += 1
        return added

    def list_pending(self, limit: int = 50) -> list[Decision]:
        out = [c for c in self._cards.values() if c.status == PENDING]
        return out[:max(0, limit)]

    def list_by_status(self, status: Optional[str] = None, limit: int = 100) -> list[Decision]:
        out = [c for c in self._cards.values() if status is None or c.status == status]
        return out[:max(0, limit)]

    def get(self, decision_id: str) -> Optional[Decision]:
        return self._cards.get(decision_id)

    def approve(self, decision_id: str) -> bool:
        c = self._cards.get(decision_id)
        if c is None or c.status != PENDING:
            return False
        c.status = APPROVED
        self._seq += 1
        self._decided_seq[decision_id] = self._seq   # approval time, for FIFO claim
        return True

    def reject(self, decision_id: str, reason: str = "") -> bool:
        c = self._cards.get(decision_id)
        if c is None or c.status != PENDING:
            return False
        c.status = REJECTED
        c.reject_reason = reason or None
        return True

    def reject_approved(self, decision_id: str, reason: str = "") -> bool:
        c = self._cards.get(decision_id)
        if c is None or c.status != APPROVED:
            return False
        c.status = REJECTED
        c.reject_reason = reason or None
        self._decided_seq.pop(decision_id, None)   # drop the claim-ordering entry
        return True

    def claim_next_approved(self) -> Optional[Decision]:
        # FIFO by approval time (decided_seq), tie-break by enqueue order — matches the
        # DB store's ORDER BY decided_at, created_at. Does NOT mutate status.
        approved = [(self._decided_seq.get(c.id, self._seq + 1), i, c)
                    for i, c in enumerate(self._cards.values()) if c.status == APPROVED]
        if not approved:
            return None
        approved.sort(key=lambda t: (t[0], t[1]))
        return approved[0][2]

    def mark_applied(self, decision_id: str) -> bool:
        c = self._cards.get(decision_id)
        if c is None or c.status != APPROVED:
            return False
        c.status = APPLIED
        return True

    def counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for c in self._cards.values():
            out[c.status] = out.get(c.status, 0) + 1
        return out


# --------------------------------------------------------------------------- #
# DB implementation (production) — decisions table (spec §5)
# --------------------------------------------------------------------------- #
_SELECT_COLS = "id, affected_slot_ids, proposal, status, reject_reason"


class DbDecisionStore(DecisionStore):
    """Postgres-backed store over the ``decisions`` table via a psycopg ``conn``.

    Writes go through ``db._assert_writable`` (the same guard that forbids any
    source-site host), so a misconfigured DSN cannot touch production content.
    """

    def __init__(self, conn) -> None:
        from . import db

        self._conn = conn
        self._db = db
        db._assert_writable(conn.info.dsn or "")

    def _cur(self):
        return self._conn.cursor()

    def enqueue(self, cards: list[Decision]) -> int:
        if not cards:
            return 0
        ids = [c.id for c in cards]
        with self._cur() as cur:
            cur.execute("SELECT id FROM decisions WHERE id = ANY(%s)", (ids,))
            existing = {r[0] for r in cur.fetchall()}
        new = [c for c in cards if c.id not in existing]
        if not new:
            return 0
        # ON CONFLICT DO NOTHING is a race safety-net; a decided card is never overwritten.
        sql = ("INSERT INTO decisions (id, affected_slot_ids, proposal, status, reject_reason) "
               "VALUES (%s, %s, %s, %s, %s) ON CONFLICT (id) DO NOTHING")
        with self._cur() as cur:
            cur.executemany(sql, [decision_to_row(c) for c in new])
        self._conn.commit()
        return len(new)

    def list_pending(self, limit: int = 50) -> list[Decision]:
        sql = (f"SELECT {_SELECT_COLS} FROM decisions WHERE status = %s "
               f"ORDER BY created_at ASC LIMIT %s")
        with self._cur() as cur:
            cur.execute(sql, (PENDING, limit))
            return [row_to_decision(r) for r in cur.fetchall()]

    def list_by_status(self, status: Optional[str] = None, limit: int = 100) -> list[Decision]:
        if status is None:
            sql = f"SELECT {_SELECT_COLS} FROM decisions ORDER BY created_at ASC LIMIT %s"
            params: tuple = (limit,)
        else:
            sql = (f"SELECT {_SELECT_COLS} FROM decisions WHERE status = %s "
                   f"ORDER BY created_at ASC LIMIT %s")
            params = (status, limit)
        with self._cur() as cur:
            cur.execute(sql, params)
            return [row_to_decision(r) for r in cur.fetchall()]

    def get(self, decision_id: str) -> Optional[Decision]:
        sql = f"SELECT {_SELECT_COLS} FROM decisions WHERE id = %s"
        with self._cur() as cur:
            cur.execute(sql, (decision_id,))
            row = cur.fetchone()
            return row_to_decision(row) if row else None

    def approve(self, decision_id: str) -> bool:
        return self._transition(decision_id, PENDING, APPROVED)

    def reject(self, decision_id: str, reason: str = "") -> bool:
        sql = ("UPDATE decisions SET status = %s, decided_at = %s, reject_reason = %s "
               "WHERE id = %s AND status = %s")
        with self._cur() as cur:
            cur.execute(sql, (REJECTED, _now(), reason or None, decision_id, PENDING))
            n = cur.rowcount
        self._conn.commit()
        return n > 0

    def reject_approved(self, decision_id: str, reason: str = "") -> bool:
        # approved -> rejected dead-letter. COALESCE keeps the human's approval time as
        # decided_at while recording the machine reason; scope to status=approved so a
        # concurrent worker transition (applied) can never be clobbered.
        sql = ("UPDATE decisions SET status = %s, decided_at = COALESCE(decided_at, %s), "
               "reject_reason = %s WHERE id = %s AND status = %s")
        with self._cur() as cur:
            cur.execute(sql, (REJECTED, _now(), reason or None, decision_id, APPROVED))
            n = cur.rowcount
        self._conn.commit()
        return n > 0

    def claim_next_approved(self) -> Optional[Decision]:
        # FIFO by decision time.  SKIP LOCKED avoids *blocking* when multiple workers
        # poll concurrently (each sees a different row), but because we commit
        # immediately after the SELECT the row-lock lifetime is microseconds — so
        # true double-claim prevention relies on at-least-once semantics + the
        # idempotent mark_applied/reject_approved transitions downstream.
        sql = (f"SELECT {_SELECT_COLS} FROM decisions WHERE status = %s "
               f"ORDER BY decided_at ASC, created_at ASC LIMIT 1 FOR UPDATE SKIP LOCKED")
        with self._cur() as cur:
            cur.execute(sql, (APPROVED,))
            row = cur.fetchone()
        self._conn.commit()
        return row_to_decision(row) if row else None

    def mark_applied(self, decision_id: str) -> bool:
        return self._transition(decision_id, APPROVED, APPLIED)

    def _transition(self, decision_id: str, frm: str, to: str) -> bool:
        sql = ("UPDATE decisions SET status = %s, decided_at = COALESCE(decided_at, %s) "
               "WHERE id = %s AND status = %s")
        with self._cur() as cur:
            cur.execute(sql, (to, _now(), decision_id, frm))
            n = cur.rowcount
        self._conn.commit()
        return n > 0

    def counts(self) -> dict[str, int]:
        with self._cur() as cur:
            cur.execute("SELECT status, count(*) FROM decisions GROUP BY status")
            return {row[0]: int(row[1]) for row in cur.fetchall()}


def _now() -> datetime:
    return datetime.now(timezone.utc)
