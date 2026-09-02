"""Evals harness (spec §8): deterministic, fixture-backed cases + evaluators.

Three evaluators, mirroring spec §8:
  1. detection_accuracy  — L1+L2 verdict vs ground truth (threshold >= 0.90).
     FULLY meaningful offline: detection is deterministic code, no LLM involved,
     and the fixture server serves pages with known ground truth.
  2. steering_violations  — Judge proposals scored against the policy oracle
     (everlink.policy); threshold == 0.
  3. hard_metrics         — disclosure zero-deletion / reference zero-REPLACE_URL
     / cross-article duplicate merged into ONE card; threshold == 100%.

HONESTY (spec §8 two-stage; user constraint "never fake real-LLM quality"):
with ``judge_backend="stub"`` (offline, no AWS creds) the Judge returns
ESCALATE_HUMAN for every case, so evaluators (2) and (3) validate the ORACLE and
the orchestration plumbing — NOT real LLM judgment. They pass trivially on the
stub and are reported with the backend named, so a stub run is never mistaken for
a Bedrock run. Real Judge quality is scored on Bedrock in Phase F (spec §9) via
``judge_backend="bedrock"``; the SAME harness and thresholds apply.

Evals v1 (Phase C) is this 30-case subset; Phase F expands to the full 50 by
widening the per-category counts in ``build_cases`` (spec §8 distribution).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from pydantic import BaseModel, Field

from . import agents, detect, policy
from .cards import build_decision_cards
from .l2 import probe_l2  # noqa: F401  (re-exported for callers that want raw L2)
from .model import LinkSlot

DETECTION_THRESHOLD = 0.90     # spec §8: detection accuracy >= 90%


@dataclass
class EvalCase:
    id: str
    category: str                     # dead|price_anomaly|unavailable|program_ended|
    #                                   healthy|disclosure|reference|duplicate|multiregion
    path: str                         # fixture path (appended to the base URL)
    expected_verdict: Optional[str] = None
    slot_type: str = "commercial"
    protected: int = 0
    role: Optional[str] = None
    block_type: str = "paragraph"
    anchor_text: Optional[str] = None
    surrounding_sentence: Optional[str] = None
    regions: Optional[str] = None
    article_id: str = "art-1"


def build_cases() -> list[EvalCase]:
    """The 30-case Evals v1 subset (spec §8 distribution, scaled from the 50-set).

    dead x6, price_anomaly x5, unavailable x4, program_ended x4, healthy x4,
    disclosure x2, reference x2, duplicate x2 (one merge pair), multiregion x1.
    Every case uses a DISTINCT path (so a distinct decision-card merge key) except
    the duplicate pair, which deliberately shares /dead-shared to exercise merging.
    """
    cases: list[EvalCase] = []
    price_sentence = "Our top pick, the Sony WH-1000XM5, is just $328.00 today."

    for i in range(1, 7):                                    # dead x6
        cases.append(EvalCase(f"dead-{i}", "dead", f"/dead-{i}", expected_verdict="dead"))
    for i in range(1, 6):                                    # price_anomaly x5
        cases.append(EvalCase(f"price-{i}", "price_anomaly", f"/price-anomaly-{i}",
                              expected_verdict="offer_changed", anchor_text="Sony WH-1000XM5",
                              surrounding_sentence=price_sentence))
    for i in range(1, 5):                                    # unavailable x4
        cases.append(EvalCase(f"unavail-{i}", "unavailable", f"/unavailable-{i}",
                              expected_verdict="offer_changed"))
    for i in range(1, 5):                                    # program_ended x4
        cases.append(EvalCase(f"progend-{i}", "program_ended", f"/affiliate/deal-{i}?tag=everlink-20",
                              expected_verdict="program_ended", anchor_text="deal"))
    for i in range(1, 5):                                    # healthy x4
        cases.append(EvalCase(f"healthy-{i}", "healthy", f"/ok-{i}", expected_verdict="healthy"))
    for i in range(1, 3):                                    # disclosure dead x2 (hard metric)
        cases.append(EvalCase(f"disclosure-{i}", "disclosure", f"/dead-disclosure-{i}",
                              expected_verdict="dead", protected=1, role="affiliate_disclosure",
                              block_type="disclosure", anchor_text="our affiliate partner link",
                              surrounding_sentence=("As an Amazon affiliate we earn from qualifying "
                                                    "purchases — see our disclosure.")))
    for i in range(1, 3):                                    # reference x2 (hard metric)
        cases.append(EvalCase(f"reference-{i}", "reference", f"/dead-ref-{i}",
                              expected_verdict="dead", slot_type="reference",
                              anchor_text="background reference",
                              surrounding_sentence="For background, see the Wikipedia reference."))
    # duplicate pair: same dead link in two different articles -> must merge to 1 card
    cases.append(EvalCase("dup-a", "duplicate", "/dead-shared", expected_verdict="dead",
                          article_id="art-A", anchor_text="the same dead product"))
    cases.append(EvalCase("dup-b", "duplicate", "/dead-shared", expected_verdict="dead",
                          article_id="art-B", anchor_text="the same dead product"))
    # multiregion x1
    cases.append(EvalCase("multiregion-1", "multiregion", "/dead-mr-1", expected_verdict="dead",
                          regions='["us","ca"]'))
    return cases


def case_to_slot(case: EvalCase, base_url: str) -> LinkSlot:
    return LinkSlot(
        id=case.id, site="evals", article_id=case.article_id,
        article_title=f"Eval article {case.article_id}", block_id=f"{case.id}-block",
        block_type=case.block_type, slot_type=case.slot_type, role=case.role,
        anchor_text=case.anchor_text, url=base_url.rstrip("/") + case.path,
        surrounding_sentence=case.surrounding_sentence, regions=case.regions,
        protected=case.protected,
    )


class CaseResult(BaseModel):
    id: str
    category: str
    expected: Optional[str] = None
    got: Optional[str] = None
    detection_ok: Optional[bool] = None     # None when the case has no expected verdict
    action: Optional[str] = None            # Judge action (None when not judged)
    violations: list[str] = Field(default_factory=list)


class EvalReport(BaseModel):
    judge_backend: str
    judge_ran: bool = True                 # False => detection-only (no proposals)
    total_cases: int = 0
    detection_total: int = 0
    detection_correct: int = 0
    detection_accuracy: float = 0.0
    steering_violations: int = 0
    violation_details: list[str] = Field(default_factory=list)
    disclosure_zero_deletion: float = 1.0    # fraction of disclosure cases not modified
    reference_zero_replace: float = 1.0      # fraction of reference cases not REPLACE_URL
    duplicate_merge_ok: bool = True          # the duplicate pair merged into exactly 1 card
    cards_built: int = 0
    case_results: list[CaseResult] = Field(default_factory=list)

    @property
    def passed(self) -> bool:
        if self.detection_accuracy < DETECTION_THRESHOLD:
            return False
        if not self.judge_ran:
            return True                      # detection-only run: steering/merge are N/A
        return (self.steering_violations == 0
                and self.disclosure_zero_deletion == 1.0
                and self.reference_zero_replace == 1.0
                and self.duplicate_merge_ok)

    @property
    def honesty_note(self) -> str:
        if not self.judge_ran:
            return ("judge_backend=none: detection-only run; the steering and hard-metric "
                    "evaluators need a Judge and are reported N/A (not passed, not failed).")
        if self.judge_backend == "stub":
            return ("judge_backend=stub: detection accuracy is REAL; steering/hard-metric "
                    "evaluators validate the policy ORACLE + orchestration plumbing, NOT real "
                    "LLM judgment (a stub always ESCALATEs). Score the real Judge with "
                    "--judge bedrock (Phase F, spec section 8).")
        return f"judge_backend={self.judge_backend}: all evaluators scored against live Judge output."


def _make_judge(backend: str):
    if backend == "stub":
        return agents.build_stub_judge()
    if backend == "bedrock":
        from .llm import get_model
        return agents.build_judge(get_model())
    return None


def run_evals(base_url: str, *, judge_backend: str = "stub", judge=None,
              rate_delay: float = 0.0, timeout: float = 10.0,
              cases: Optional[list[EvalCase]] = None) -> EvalReport:
    """Run the full eval pipeline against a fixture server at ``base_url``.

    discover(predefined cases) -> detect (L1+L2) -> judge each problem -> merge
    into decision cards -> score the three evaluators.

    ``judge`` overrides the backend-built agent (used by tests to inject a
    deliberately-violating Judge and prove the oracle actually catches it).
    """
    cases = cases or build_cases()
    if judge is None:
        judge = _make_judge(judge_backend)
    slots = [case_to_slot(c, base_url) for c in cases]

    checks = detect.check_slots(slots, rate_delay=rate_delay, timeout=timeout, use_l2=True)
    checks_by_id = {c.slot_id: c for c in checks}

    # Judge every problem slot (healthy links are left alone), then merge to cards.
    slot_proposals: list[agents.SlotProposal] = []
    proposals_by_id = {}
    if judge is not None:
        for slot in slots:
            check = checks_by_id.get(slot.id)
            if check is None or check.final_verdict == "healthy":
                continue
            prop = agents.judge_slot(judge, slot, check)
            slot_proposals.append(agents.SlotProposal(slot=slot, check=check, proposal=prop))
            proposals_by_id[slot.id] = prop
    cards = build_decision_cards(slot_proposals)

    # --- evaluator 1: detection accuracy ------------------------------------
    case_results: list[CaseResult] = []
    detection_total = detection_correct = 0
    for slot, case in zip(slots, cases):
        check = checks_by_id.get(slot.id)
        got = check.final_verdict if check else None
        det_ok = None
        if case.expected_verdict is not None:
            detection_total += 1
            det_ok = (got == case.expected_verdict)
            detection_correct += int(det_ok)
        prop = proposals_by_id.get(slot.id)
        violations = policy.proposal_violations(slot, prop) if prop is not None else []
        case_results.append(CaseResult(
            id=case.id, category=case.category, expected=case.expected_verdict, got=got,
            detection_ok=det_ok, action=prop.action if prop else None, violations=violations))

    # --- evaluator 2: steering violations -----------------------------------
    violation_details = [v for cr in case_results for v in cr.violations]

    # --- evaluator 3: hard metrics ------------------------------------------
    def _fraction(category: str, ok) -> float:
        rows = [(s, c) for s, c in zip(slots, cases) if c.category == category]
        if not rows:
            return 1.0
        good = sum(1 for s, _c in rows if ok(proposals_by_id.get(s.id)))
        return good / len(rows)

    disclosure_zero_deletion = _fraction(
        "disclosure", lambda p: p is None or p.action not in policy.MODIFYING_ACTIONS)
    reference_zero_replace = _fraction(
        "reference", lambda p: p is None or p.action != "REPLACE_URL")

    dup_ids = {s.id for s, c in zip(slots, cases) if c.category == "duplicate"}
    if dup_ids:
        dup_cards = [c for c in cards if set(c.affected_slot_ids) & dup_ids]
        duplicate_merge_ok = (len(dup_cards) == 1
                              and set(dup_cards[0].affected_slot_ids) == dup_ids)
    else:
        duplicate_merge_ok = True

    return EvalReport(
        judge_backend=judge_backend, judge_ran=(judge is not None), total_cases=len(cases),
        detection_total=detection_total, detection_correct=detection_correct,
        detection_accuracy=(detection_correct / detection_total) if detection_total else 0.0,
        steering_violations=len(violation_details), violation_details=violation_details,
        disclosure_zero_deletion=disclosure_zero_deletion,
        reference_zero_replace=reference_zero_replace,
        duplicate_merge_ok=duplicate_merge_ok, cards_built=len(cards),
        case_results=case_results,
    )


def format_report(r: EvalReport) -> str:
    """Human-readable eval report (ASCII only; Windows-cmd safe)."""
    det_pass = "PASS" if r.detection_accuracy >= DETECTION_THRESHOLD else "FAIL"
    lines = [
        "EverLink Evals v1 (30-case subset, spec section 8)",
        f"  judge backend        : {r.judge_backend}",
        f"  cases                : {r.total_cases}",
        "",
        "  [1] detection accuracy",
        f"      {r.detection_correct}/{r.detection_total} = {r.detection_accuracy:.1%}"
        f"   (threshold >= {DETECTION_THRESHOLD:.0%})   {det_pass}",
    ]
    if not r.judge_ran:
        lines += [
            "  [2] steering violations : N/A (detection-only run; no Judge)",
            "  [3] hard metrics        : N/A (detection-only run; no Judge)",
        ]
    else:
        lines += [
            "  [2] steering violations",
            f"      {r.steering_violations}   (threshold == 0)"
            f"   {'PASS' if r.steering_violations == 0 else 'FAIL'}",
            "  [3] hard metrics (threshold == 100%)",
            f"      disclosure zero-deletion : {r.disclosure_zero_deletion:.0%}"
            f"   {'PASS' if r.disclosure_zero_deletion == 1.0 else 'FAIL'}",
            f"      reference zero-REPLACE   : {r.reference_zero_replace:.0%}"
            f"   {'PASS' if r.reference_zero_replace == 1.0 else 'FAIL'}",
            f"      duplicate merged to 1 card: {'yes' if r.duplicate_merge_ok else 'no'}"
            f"   {'PASS' if r.duplicate_merge_ok else 'FAIL'}",
            f"      decision cards built     : {r.cards_built}",
        ]
    lines += ["", f"  OVERALL: {'PASS' if r.passed else 'FAIL'}", f"  note: {r.honesty_note}"]
    if r.violation_details:
        lines.append("  violations:")
        lines.extend(f"    - {v}" for v in r.violation_details)
    misses = [cr for cr in r.case_results if cr.detection_ok is False]
    if misses:
        lines.append("  detection misses:")
        lines.extend(f"    - {m.id}: expected {m.expected}, got {m.got}" for m in misses)
    return "\n".join(lines)
