"""Writer engine (spec §4.1 Phase E / §5 write_snapshots / §12-3 acceptance).

The Writer is EverLink's ONLY mutating component, and it is deliberately narrow and
honest about what "write-back" means for a hackathon project whose source sites are
strictly read-only:

  * It writes to EverLink's OWN operational store — the ``link_slots`` mirror row and
    the ``write_snapshots`` audit of before/after — NEVER to a source site's production
    database. Those are read-only for this project (see ``db._assert_writable`` and
    schema.sql's header: "gated content write-back ... targets a non-production / test
    instance"). A real production CMS adapter is explicitly OUT OF SCOPE; what ships is
    the complete write *machinery*: a single-transaction snapshot -> apply -> verify ->
    rollback, gated on a human-approved decision.
  * Every write is GATED. ``apply_fix`` re-checks the decision is ``approved`` (the
    deterministic twin of steering's ``write_gate`` hook) and re-runs the disclosure /
    scope oracle, so even a human-approved card cannot mutate a protected slot or
    re-point a reference link.
  * It only touches ``aethelgem`` slots (the one site with a non-production write-back
    path). Any other site is *skipped* (out of scope) — never silently written.
  * ``verify_fix`` re-probes a replacement URL for REAL (L1 + selective L2 via
    ``detect.check_slot``) and records the outcome to ``slot_checks``. A replacement
    that does not survive verification is rolled back and the card dead-letters to
    ``rejected`` with an honest reason, so the async worker never loops on it.

Pure decision logic (``compute_after`` / ``writing_violations`` / ``interpret_verify``)
is separated from the DB orchestration so the engine is testable offline against a fake
cursor, exactly like ``queue.py`` / ``db.py``.
"""
from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Optional

from . import db, detect, policy, steering
from .model import CheckResult, Decision, LinkSlot, Proposal
from .queue import DecisionStore

# Only this site has a (non-production) write-back path; every other site is skipped.
WRITEBACK_SITES = ("aethelgem",)

# A replacement is "verified" ONLY on this verdict — the Writer never claims success it
# cannot prove (spec §4.1: "never fabricates a healthy verdict").
_VERIFY_OK = ("healthy",)

# Injectable re-probe: (candidate_slot, timeout=, use_l2=) -> CheckResult.
Probe = Callable[..., CheckResult]


class WriteRefused(RuntimeError):
    """A guard refused the write; the surrounding transaction is rolled back so NOTHING
    is written (no partial state)."""


# --------------------------------------------------------------------------- #
# results
# --------------------------------------------------------------------------- #
@dataclass
class SlotWrite:
    """Outcome of applying (or refusing/skipping) one slot's fix."""

    slot_id: str
    site: str = ""
    action: str = ""
    status: str = "refused"        # applied | refused | skipped | rolled_back
    snapshot_id: int = 0
    before: dict = field(default_factory=dict)
    after: dict = field(default_factory=dict)
    reason: str = ""


@dataclass
class VerifyResult:
    """Outcome of re-probing a replacement URL (spec §12-3 "verify_fix green")."""

    slot_id: str
    verified: bool
    probed: bool = False           # False => no new URL to re-probe (editorial fix)
    verdict: Optional[str] = None
    check: Optional[CheckResult] = None
    reason: str = ""


@dataclass
class FixOutcome:
    """The whole per-decision result the worker/handler reasons about."""

    decision_id: str
    writes: list[SlotWrite] = field(default_factory=list)
    verifies: list[VerifyResult] = field(default_factory=list)
    rolled_back: list[str] = field(default_factory=list)
    dead_letter: str = ""          # non-empty => the card must terminally reject

    @property
    def applied_slots(self) -> list[str]:
        return [w.slot_id for w in self.writes if w.status == "applied"]

    @property
    def ok(self) -> bool:
        """True iff something was applied and nothing was rolled back / dead-lettered."""
        return bool(self.applied_slots) and not self.rolled_back and not self.dead_letter


# --------------------------------------------------------------------------- #
# PURE decision logic (offline-testable; no DB, no network)
# --------------------------------------------------------------------------- #
def _content_changes(proposal: Proposal) -> dict:
    """The content diff an action implies (subset of ``db.CONTENT_FIELDS``).

    DROP_BLOCK *archives* (status='archived') rather than deletes — reversible by
    rollback, nothing destroyed. ESCALATE_HUMAN / a content-less action yields no diff.
    """
    action = proposal.action
    if action == "REPLACE_URL" and (proposal.new_url or "").strip():
        return {"url": proposal.new_url, "target_url": proposal.new_url}
    if action == "REWRITE_ANCHOR" and proposal.new_anchor is not None:
        return {"anchor_text": proposal.new_anchor}
    if action == "REWRITE_SENTENCE" and proposal.new_sentence is not None:
        return {"surrounding_sentence": proposal.new_sentence}
    if action == "DROP_BLOCK":
        return {"status": "archived"}
    return {}


def compute_after(before: dict, proposal: Proposal) -> dict:
    """PURE: the COMPLETE slot content after applying ``proposal`` (before + diff).

    ``after == before`` means the action changed nothing (a no-op the caller refuses).
    """
    return {**before, **_content_changes(proposal)}


def writing_violations(slot: LinkSlot, proposal: Proposal) -> list[str]:
    """PURE: every HARD reason the Writer must refuse to write this (slot, proposal).

    Defense in depth at WRITE time — even a human-approved card is re-checked against
    the SAME oracle the Judge/Evals use (``policy.proposal_violations``: disclosure +
    scope), plus ESCALATE_HUMAN is not an applicable write. The write-back *site* scope
    is handled separately in ``apply_fix`` (a skip, not a refusal).
    """
    out: list[str] = []
    if proposal.action == "ESCALATE_HUMAN":
        out.append("ESCALATE_HUMAN is not an applicable write; it needs a human, "
                   "not the Writer.")
    out.extend(policy.proposal_violations(slot, proposal))   # disclosure + scope oracle
    return out


def interpret_verify(check: CheckResult) -> tuple[bool, str]:
    """PURE: did the re-probe PROVE the replacement is live? Only ``healthy`` counts.

    dead / offer_changed / program_ended => the replacement is ALSO bad (roll back);
    needs_human_recheck (blocked/timeout) is inconclusive and, fail-safe, NOT verified.
    """
    v = check.final_verdict
    if v in _VERIFY_OK:
        return True, f"replacement re-probed '{v}' (L1 {check.l1_status})."
    return False, (f"replacement re-probed '{v}' (L1 {check.l1_status}, "
                   f"L2 {check.l2_verdict}); NOT verified.")


# --------------------------------------------------------------------------- #
# DB orchestration — EverLink's OWN store only (never a source site)
# --------------------------------------------------------------------------- #
def snapshot_block(conn, slot_id: str) -> Optional[dict]:
    """Read a slot's current mutable content — the write-snapshot ``before`` state.

    The explicit ``snapshot_block`` tool (spec §6). ``apply_fix`` re-reads this INSIDE
    its own transaction so the snapshot and the write are atomic.
    """
    return db.fetch_slot_content(conn, slot_id)


def apply_fix(conn, decision: Decision, slot_id: str, *,
              is_approved: Callable[[str], bool]) -> SlotWrite:
    """Snapshot + apply ONE slot's fix in a SINGLE transaction (spec §5 "write-back is
    a single transaction").

    Guards — each causes a clean rollback and a non-applied result, never a partial
    write: the decision must be ``approved``; the slot's site must be in
    ``WRITEBACK_SITES`` (else *skipped*); the (slot, proposal) must pass
    ``writing_violations``; and the fix must actually change something (no-op => refused).
    On success it updates the slot content and records a before/after ``write_snapshot``.
    """
    proposal = decision.proposal
    if not is_approved(decision.id):
        return SlotWrite(slot_id=slot_id, action=proposal.action, status="refused",
                         reason=f"decision '{decision.id}' is not approved.")
    try:
        with conn.transaction():
            slot = db.fetch_slot(conn, slot_id)
            if slot is None:
                raise WriteRefused(f"slot '{slot_id}' not found in EverLink's store.")
            if slot.site not in WRITEBACK_SITES:
                # Out-of-scope site: a SKIP (not a guard refusal) — does NOT dead-letter
                # the card, because this slot was simply never writable by EverLink.
                return SlotWrite(slot_id=slot_id, site=slot.site, action=proposal.action,
                                 status="skipped",
                                 reason=f"site '{slot.site}' is outside the "
                                        f"{WRITEBACK_SITES} write-back scope.")
            violations = writing_violations(slot, proposal)
            if violations:
                raise WriteRefused(" ".join(violations))
            before = db.fetch_slot_content(conn, slot_id) or {}
            after = compute_after(before, proposal)
            if after == before:
                raise WriteRefused(f"{proposal.action} produced no content change (no-op).")
            db.update_slot_content(conn, slot_id, after)
            snap_id = db.insert_write_snapshot(conn, slot_id, decision.id, before, after)
        return SlotWrite(slot_id=slot_id, site=slot.site, action=proposal.action,
                         status="applied", snapshot_id=snap_id, before=before, after=after)
    except WriteRefused as e:
        return SlotWrite(slot_id=slot_id, action=proposal.action, status="refused",
                         reason=str(e))


def verify_fix(conn, decision: Decision, slot_id: str, *, timeout: float = 15.0,
               use_l2: bool = True, probe: Optional[Probe] = None) -> VerifyResult:
    """Re-probe a replacement URL for REAL and record it to ``slot_checks`` (spec §12-3).

    Only ``REPLACE_URL`` claims a NEW live link, so only it needs re-probing: build a
    candidate slot whose url is the proposal's ``new_url``, run ``detect.check_slot``
    (L1 + selective L2), persist the CheckResult, and interpret it. Editorial fixes
    (REWRITE_* / DROP_BLOCK) claim no new URL, so verification is an honest trivial pass
    ("nothing to re-probe") — NOT a fabricated green checkmark. ``probe`` is injectable
    so tests run offline; production uses ``detect.check_slot``.
    """
    proposal = decision.proposal
    new_url = (proposal.new_url or "").strip()
    if proposal.action != "REPLACE_URL" or not new_url:
        return VerifyResult(slot_id=slot_id, verified=True, probed=False,
                            reason=f"{proposal.action} claims no new URL; nothing to re-probe.")
    base = db.fetch_slot(conn, slot_id)
    if base is not None:
        candidate = base.model_copy(update={"url": new_url, "target_url": new_url})
    else:
        candidate = LinkSlot(id=slot_id, site="", article_id="", article_title="",
                             block_id="", block_type="", slot_type="commercial", url=new_url)
    check = (probe or detect.check_slot)(candidate, timeout=timeout, use_l2=use_l2)
    db.insert_slot_check(conn, check)          # honest record of the re-probe
    ok, reason = interpret_verify(check)
    return VerifyResult(slot_id=slot_id, verified=ok, probed=True,
                        verdict=check.final_verdict, check=check, reason=reason)


def rollback(conn, decision: Decision, slot_id: str) -> SlotWrite:
    """Restore a slot from its latest write_snapshot (spec §12-3 "rollback recovers").

    Single transaction: read the snapshot's before-state, write it back, stamp
    ``rolled_back_at``. If there is no snapshot there is nothing to restore.
    """
    snap = db.fetch_latest_snapshot(conn, decision.id, slot_id)
    if snap is None:
        return SlotWrite(slot_id=slot_id, action=decision.proposal.action,
                         status="refused", reason="no write_snapshot to roll back.")
    raw = snap.get("before_json")
    before = json.loads(raw) if isinstance(raw, str) else (raw or {})
    try:
        with conn.transaction():
            db.update_slot_content(conn, slot_id, before)
            db.mark_snapshot_rolled_back(conn, int(snap["id"]))
        return SlotWrite(slot_id=slot_id, action=decision.proposal.action,
                         status="rolled_back", snapshot_id=int(snap["id"]), before=before)
    except Exception as e:  # noqa: BLE001 - report, never crash the worker
        return SlotWrite(slot_id=slot_id, action=decision.proposal.action,
                         status="refused", reason=f"rollback failed: {e!r}")


# --------------------------------------------------------------------------- #
# per-decision core (shared by the async handler and the CLI)
# --------------------------------------------------------------------------- #
def run_fix(conn, decision: Decision, *, is_approved: Callable[[str], bool],
            timeout: float = 15.0, use_l2: bool = True,
            probe: Optional[Probe] = None) -> FixOutcome:
    """Apply + verify (+ rollback on failed verify) ONE decision across all its slots.

    Per slot: ``apply_fix`` (single tx) -> ``verify_fix`` (real re-probe). A slot whose
    replacement fails verification is rolled back and contributes a dead-letter reason;
    a guard refusal does too. If nothing was writable at all (every slot skipped) that
    is also a dead-letter — the card is honestly rejected rather than falsely 'applied'.
    """
    outcome = FixOutcome(decision_id=decision.id)
    failures: list[str] = []
    for slot_id in decision.affected_slot_ids:
        w = apply_fix(conn, decision, slot_id, is_approved=is_approved)
        outcome.writes.append(w)
        if w.status == "refused":
            failures.append(f"slot '{slot_id}' refused: {w.reason}")
            continue
        if w.status != "applied":          # skipped (out of write-back scope)
            continue
        v = verify_fix(conn, decision, slot_id, timeout=timeout, use_l2=use_l2, probe=probe)
        outcome.verifies.append(v)
        if v.probed and not v.verified:
            rb = rollback(conn, decision, slot_id)
            if rb.status == "rolled_back":
                outcome.rolled_back.append(slot_id)
                w.status = "rolled_back"
                failures.append(f"slot '{slot_id}' {v.reason} (rolled back)")
            else:
                failures.append(f"slot '{slot_id}' {v.reason} (ROLLBACK FAILED: {rb.reason})")
    if not outcome.applied_slots and not failures:
        failures.append(f"no slot was writable ({len(outcome.writes)} skipped, 0 applied); "
                        f"nothing to do.")
    outcome.dead_letter = "; ".join(failures).strip()
    return outcome


def make_writer_handler(conn, store: DecisionStore, *,
                        is_approved: Optional[Callable[[str], bool]] = None,
                        audit_sink: Optional[Callable[[dict], None]] = None,
                        timeout: float = 15.0, use_l2: bool = True,
                        probe: Optional[Probe] = None):
    """Build the async-track Writer handler (spec §6: worker -> writer applies).

    This is the seam ``hitl.null_handler`` left for pe1. For a claimed APPROVED decision
    it runs ``run_fix`` and audits the per-slot trail (write / write_refused / verify /
    rollback). On a decisive failure it calls ``store.reject_approved`` so the card
    terminally rejects and the worker's subsequent ``mark_applied`` no-ops — a dead-letter
    instead of an infinite retry loop. It returns normally in every decisive case (only a
    genuine crash propagates, leaving the card approved for retry).
    """
    approve_check = is_approved or steering.db_decision_approval(conn)
    emit = audit_sink or (lambda _rec: None)

    def _rec(event: str, **extra) -> None:
        try:
            emit({"agent": "writer", "event": event, **extra})
        except Exception:
            pass  # auditing is best-effort; never break the worker

    def handler(decision: Decision) -> None:
        outcome = run_fix(conn, decision, is_approved=approve_check,
                          timeout=timeout, use_l2=use_l2, probe=probe)
        for w in outcome.writes:
            if w.snapshot_id:                       # a write WAS recorded (even if later
                _rec("write", decision_id=decision.id, slot_id=w.slot_id, site=w.site,
                     action=w.action, snapshot_id=w.snapshot_id,
                     final_status=w.status, after=w.after)   # rolled back — audit both)
            elif w.status == "refused":
                _rec("write_refused", decision_id=decision.id, slot_id=w.slot_id,
                     action=w.action, reason=w.reason)
        for v in outcome.verifies:
            _rec("verify", decision_id=decision.id, slot_id=v.slot_id, probed=v.probed,
                 verified=v.verified, verdict=v.verdict, reason=v.reason)
        for sid in outcome.rolled_back:
            _rec("rollback", decision_id=decision.id, slot_id=sid)
        if outcome.dead_letter:
            store.reject_approved(decision.id, outcome.dead_letter)
    return handler
