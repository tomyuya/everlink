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
``judge_backend="mantle"`` (the deployed production path — qwen through the Bedrock
Mantle gateway) or ``judge_backend="bedrock"`` (direct Claude); the SAME harness and
thresholds apply.

``build_cases(full=False)`` is the 30-case v1 subset (Phase C); ``build_cases(full=True)``
is the FULL 50-case Phase F set (spec §8 distribution). Both run through the SAME harness
and thresholds — the only difference is the per-category counts, so a v1 pass and a full
pass are directly comparable.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from pydantic import BaseModel, Field

from . import agents, detect, policy, tracing
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


# spec §8 case distribution. v1 (Phase C) is the 30-case baseline subset used to check the
# Judge early; the FULL Phase F set widens every category to the spec's 50-case distribution.
# The 'duplicate' category is always exactly ONE merge pair (2 cases) in both sets, so it is
# not a count knob. dead+price+unavail+progend+healthy+disclosure+reference+dup+multiregion.
_V1_COUNTS = dict(dead=6, price=5, unavail=4, progend=4, healthy=4,
                  disclosure=2, reference=2, multiregion=1)          # + dup pair = 30
_FULL_COUNTS = dict(dead=10, price=8, unavail=6, progend=6, healthy=8,
                    disclosure=4, reference=4, multiregion=2)         # + dup pair = 50


def build_cases(full: bool = False) -> list[EvalCase]:
    """The Evals case set (spec §8 distribution).

    ``full=False`` -> the 30-case v1 baseline (Phase C): dead x6, price_anomaly x5,
    unavailable x4, program_ended x4, healthy x4, disclosure x2, reference x2, duplicate x2
    (one merge pair), multiregion x1.
    ``full=True`` -> the FULL 50-case Phase F set: dead x10, price_anomaly x8, unavailable
    x6, program_ended x6, healthy x8, disclosure x4, reference x4, duplicate x2, multiregion
    x2 (spec §8 line 249).

    Every case uses a DISTINCT path (so a distinct decision-card merge key) except the
    duplicate pair, which deliberately shares /dead-shared to exercise merging. The fixture
    server serves all of them via its scenario prefix routes (/dead*, /price-anomaly*,
    /unavailable*, /affiliate/deal*) plus the /ok* default, so no fixture change is needed.
    """
    n = _FULL_COUNTS if full else _V1_COUNTS
    cases: list[EvalCase] = []
    price_sentence = "Our top pick, the Sony WH-1000XM5, is just $328.00 today."

    for i in range(1, n["dead"] + 1):                                    # dead
        cases.append(EvalCase(f"dead-{i}", "dead", f"/dead-{i}", expected_verdict="dead"))
    for i in range(1, n["price"] + 1):                                   # price_anomaly
        cases.append(EvalCase(f"price-{i}", "price_anomaly", f"/price-anomaly-{i}",
                              expected_verdict="offer_changed", anchor_text="Sony WH-1000XM5",
                              surrounding_sentence=price_sentence))
    for i in range(1, n["unavail"] + 1):                                 # unavailable (soft-404)
        cases.append(EvalCase(f"unavail-{i}", "unavailable", f"/unavailable-{i}",
                              expected_verdict="offer_changed"))
    for i in range(1, n["progend"] + 1):                                 # program_ended
        cases.append(EvalCase(f"progend-{i}", "program_ended", f"/affiliate/deal-{i}?tag=everlink-20",
                              expected_verdict="program_ended", anchor_text="deal"))
    for i in range(1, n["healthy"] + 1):                                 # healthy
        cases.append(EvalCase(f"healthy-{i}", "healthy", f"/ok-{i}", expected_verdict="healthy"))
    for i in range(1, n["disclosure"] + 1):                              # disclosure dead (hard metric)
        cases.append(EvalCase(f"disclosure-{i}", "disclosure", f"/dead-disclosure-{i}",
                              expected_verdict="dead", protected=1, role="affiliate_disclosure",
                              block_type="disclosure", anchor_text="our affiliate partner link",
                              surrounding_sentence=("As an Amazon affiliate we earn from qualifying "
                                                    "purchases — see our disclosure.")))
    for i in range(1, n["reference"] + 1):                               # reference (hard metric)
        cases.append(EvalCase(f"reference-{i}", "reference", f"/dead-ref-{i}",
                              expected_verdict="dead", slot_type="reference",
                              anchor_text="background reference",
                              surrounding_sentence="For background, see the Wikipedia reference."))
    # duplicate pair: same dead link in two different articles -> must merge to 1 card
    cases.append(EvalCase("dup-a", "duplicate", "/dead-shared", expected_verdict="dead",
                          article_id="art-A", anchor_text="the same dead product"))
    cases.append(EvalCase("dup-b", "duplicate", "/dead-shared", expected_verdict="dead",
                          article_id="art-B", anchor_text="the same dead product"))
    for i in range(1, n["multiregion"] + 1):                             # multiregion
        cases.append(EvalCase(f"multiregion-{i}", "multiregion", f"/dead-mr-{i}",
                              expected_verdict="dead", regions='["us","ca"]'))
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
                    "--judge mantle (the deployed Bedrock path; --judge bedrock is the "
                    "direct-Claude route) — same harness, same thresholds.")
        return f"judge_backend={self.judge_backend}: all evaluators scored against live Judge output."


def _make_judge(backend: str):
    if backend == "stub":
        return agents.build_stub_judge()
    if backend == "bedrock":
        from .llm import get_model
        return agents.build_judge(get_model())
    if backend == "mantle":
        from .llm import get_mantle_model
        return agents.build_judge(get_mantle_model())
    return None


def run_evals(base_url: str, *, judge_backend: str = "stub", judge=None,
              rate_delay: float = 0.0, timeout: float = 10.0, full: bool = False,
              cases: Optional[list[EvalCase]] = None) -> EvalReport:
    """Run the full eval pipeline against a fixture server at ``base_url``.

    discover(predefined cases) -> detect (L1+L2) -> judge each problem -> merge
    into decision cards -> score the three evaluators. Each stage is wrapped in an
    OPTIONAL OpenTelemetry span (everlink.tracing): with tracing off they are
    zero-cost no-ops, with ``--trace`` they emit a run -> {detect,judge,score} tree.

    ``full=True`` runs the FULL 50-case Phase F set (spec §8); the default is the
    30-case v1 subset. ``judge`` overrides the backend-built agent (used by tests to
    inject a deliberately-violating Judge and prove the oracle actually catches it).
    """
    cases = cases or build_cases(full=full)
    if judge is None:
        judge = _make_judge(judge_backend)
    slots = [case_to_slot(c, base_url) for c in cases]

    with tracing.span("everlink.evals.run", cases=len(cases),
                      judge_backend=judge_backend, full=full):
        with tracing.span("everlink.evals.detect", slots=len(slots)):
            checks = detect.check_slots(slots, rate_delay=rate_delay, timeout=timeout,
                                        use_l2=True)
        checks_by_id = {c.slot_id: c for c in checks}

        # Judge every problem slot (healthy links are left alone), then merge to cards.
        slot_proposals: list[agents.SlotProposal] = []
        proposals_by_id = {}
        with tracing.span("everlink.evals.judge", problem_slots=len(slots)):
            if judge is not None:
                for slot in slots:
                    check = checks_by_id.get(slot.id)
                    if check is None or check.final_verdict == "healthy":
                        continue
                    prop = agents.judge_slot(judge, slot, check)
                    slot_proposals.append(
                        agents.SlotProposal(slot=slot, check=check, proposal=prop))
                    proposals_by_id[slot.id] = prop
            cards = build_decision_cards(slot_proposals)

        # --- evaluator 1: detection accuracy --------------------------------
        with tracing.span("everlink.evals.score", cards=len(cards)):
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
                    id=case.id, category=case.category, expected=case.expected_verdict,
                    got=got, detection_ok=det_ok,
                    action=prop.action if prop else None, violations=violations))

            # --- evaluator 2: steering violations ---------------------------
            violation_details = [v for cr in case_results for v in cr.violations]

            # --- evaluator 3: hard metrics ----------------------------------
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
            detection_accuracy=((detection_correct / detection_total)
                                if detection_total else 0.0),
            steering_violations=len(violation_details), violation_details=violation_details,
            disclosure_zero_deletion=disclosure_zero_deletion,
            reference_zero_replace=reference_zero_replace,
            duplicate_merge_ok=duplicate_merge_ok, cards_built=len(cards),
            case_results=case_results,
        )


def format_report(r: EvalReport) -> str:
    """Human-readable eval report (ASCII only; Windows-cmd safe)."""
    det_pass = "PASS" if r.detection_accuracy >= DETECTION_THRESHOLD else "FAIL"
    suite = ("full 50-case Phase F set" if r.total_cases >= 50
             else f"{r.total_cases}-case v1 subset")
    lines = [
        f"EverLink Evals ({suite}, spec section 8)",
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
