"""Demo seed dataset — a clearly-labelled REPLAY of one nightly EverLink run.

spec §7 line 244 ("部署环境注入 seed 数据集：当夜 41 问题槽回放 + 已批/已驳样例 +
审计日志，杜绝评委打开空 inbox 的空态风险") and the §11 demo beats. The live/public
board must never show a judge an empty inbox, so this module BUILDS (pure, offline,
deterministic) and WRITES (guarded, atomic, idempotent, resettable) a realistic
snapshot of "last night's autonomous run" into EverLink's OWN Neon store:

  * **41 problem slots** across all three sites (the morning-report headline).
  * **41 scan decision cards** the human triaged: **approved 38, rejected 3**
    (spec §11 "批 38 驳 3"). The 3 rejections carry real reasons (驳回记忆) and each
    is a steering safety curtain: a protected affiliate-disclosure block, a
    ``reference`` citation, and a point-in-time price claim.
  * The worker then applied the 38 approved cards: **37 re-probed healthy**
    ("37 dead→0", the closed-loop green shot) and **1 was CAUGHT by ``verify_fix``**
    (its replacement had also gone dead) → auto-rolled-back → pe2 dead-lettered the
    card to ``rejected`` and spawned a **pending rollback-recommendation card** (the
    "回滚演示" beat). Final state: applied 37 · rejected 4 (3 human + 1 machine
    dead-letter) · pending 1 (the recommendation).
  * ``write_snapshots`` (before/after) for every applied aethelgem slot, one stamped
    ``rolled_back_at``.
  * A full ``audit_log`` trail mirroring EXACTLY what the real hooks emit: scan/judge
    ``tool_result``, the three steering curtains as ``steering_cancel``, the high-risk
    ``interrupt``, the morning-brief + card ``notify``, and the writer's
    ``write``/``verify``/``rollback`` + the worker's ``dead_letter``.
  * Relative timestamps so the whole run sits inside the weekly-report window and
    reads as "last night".

HONESTY (spec §2.1 "fixture 回放为辅（明确标注）"): this is a REPLAY — NOT live scan
output and NOT real Bedrock decisions. Every rationale/reject_reason is human-authored
demo copy, every URL is a synthetic merchant/fixture link, and every row is tagged with
``SEED_MARK`` so it can be found and removed (``--reset``). It DOES exercise the real
code paths (``cards.build_decision_cards``, ``writer.compute_after``,
``writer.rollback_recommendation``, ``db``/``queue`` serialization) so the seeded rows
are byte-for-byte what those functions produce — but it never claims a real LLM judged
these fixes or a real merchant link was probed. The demo narrator reads the TRUE counts
from ``--json``; nothing here fabricates a delivery or a live decision.

SAFETY: writes go ONLY to EverLink's own store through ``db._assert_writable`` (the same
guard that forbids any source-site / Blue Neon production host). No source site is
touched and no production content is baked in. The whole seed is ONE transaction: on any
error it rolls back, leaving no half-written dataset (spec §5 "不产生半写状态").
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

from . import cards as cards_mod
from . import db, detect, queue, writer
from .agents import SlotProposal
from .model import CheckResult, Decision, LinkSlot, Proposal, RedirectHop

# Stable marker stamped into every seeded row's id/payload so --reset targets EXACTLY
# the demo dataset and nothing else (never a real scanned slot or a live decision).
SEED_MARK = "demo-seed"

# Only aethelgem has a (non-production) write-back path — mirrors writer.WRITEBACK_SITES.
_WRITEBACK_SITE = "aethelgem"

# --- the demo narrative, as realistic first-party content ----------------------- #
_AEG_ARTICLES = [
    ("Best Lab-Grown Diamond Engagement Rings (2026 Review)", "product_grid"),
    ("Moissanite vs Diamond: Which Should You Actually Buy?", "product_card"),
    ("7 Affordable Sapphire Rings That Look Far More Expensive", "product_card"),
    ("The Honest Guide to Buying Emerald Jewelry Online", "comparison_table"),
    ("Best Places to Buy Lab Diamonds: Our Top 5 Picks", "product_grid"),
    ("Pear-Cut Diamond Rings: 2026 Buyer's Guide", "product_card"),
    ("Everyday Stackable Rings Under $300", "inline_product"),
    ("How to Spot a Treated vs Natural Gemstone", "product_card"),
]
_AEG_PRODUCTS = [
    ("Aurora Lab-Grown Diamond Solitaire", "aurora lab-grown diamond solitaire"),
    ("Moissanite Halo Ring 2ct", "moissanite halo ring"),
    ("Ceylon Blue Sapphire Pendant", "ceylon sapphire pendant"),
    ("Colombian Emerald Trilogy Ring", "emerald trilogy ring"),
    ("Pear-Cut Diamond Eternity Band", "pear-cut eternity band"),
    ("Rose-Cut Diamond Studs", "rose-cut diamond studs"),
    ("Stackable Sapphire Band Set", "stackable sapphire bands"),
    ("Oval Moissanite Engagement Ring", "oval moissanite ring"),
]
_TAG = "aethelgem-20"

# scenario-verdict label -> (l1_verdict, l1_status, l2_verdict, l2_evidence, chain_kind).
# The FINAL verdict is NEVER hardcoded here: it is folded from (l1_verdict, l2_verdict) by
# the REAL production oracle ``detect.combine_verdict``, so a seeded CheckResult carries
# exactly the verdict the live L1+L2 pyramid would — no drift between the replay and the
# detector the Evals score. ``l2_verdict`` is None when L1 is conclusive and detect SKIPS L2
# (detect._L2_ESCALATE): a 404 dead link or a dropped-tag affiliate redirect. A soft-404
# ("Currently unavailable") is L1-healthy, so L2 runs and combine_verdict folds
# 'unavailable' -> 'offer_changed' (the page lives, the offer died) — NOT 'dead'.
_VERDICTS = {
    "dead": ("dead", 404, None,
             "L1: HTTP 404; the redirect chain ends at a 'Page Not Found' body.", None),
    "dead_soft404": ("healthy", 200, "unavailable",
                     "L2 parse: #availability = 'Currently unavailable'; soft-404 (HTTP 200 "
                     "but no buy box) — the page lives, the offer died.", None),
    "program_ended": ("program_ended", 302, None,
                      "L1 redirect-chain: affiliate hop 302 dropped ?tag= and landed the "
                      "store homepage — the tracking partnership is gone.", "affiliate"),
    "offer_changed": ("healthy", 200, "price_anomaly",
                      "L2 parse: price block jumped $199.00 -> $349.00 vs the claimed "
                      "'under $200' in the surrounding sentence.", None),
    "healthy": ("healthy", 200, "ok",
                "L2 parse: #dp-container present, in stock, price matches the claim.", None),
    "needs_human_recheck": ("healthy", 200, "blocked",
                            "L2 parse: bot-wall / captcha; inconclusive — flagged for human "
                            "recheck, never auto-fixed.", None),
}


def _final_of(label: str) -> str:
    """The final_verdict for a scenario label, folded by the REAL ``detect`` oracle.

    Single source of truth: this is literally ``detect.combine_verdict`` over the label's
    (l1_verdict, l2_verdict), so the replay can never disagree with production detection.
    """
    l1_verdict, _status, l2_verdict, _ev, _chain = _VERDICTS.get(label, _VERDICTS["dead"])
    return detect.combine_verdict(l1_verdict, l2_verdict)


def _dt(hours: float, now: datetime) -> datetime:
    return now - timedelta(hours=hours)


# --------------------------------------------------------------------------- #
# scenario table — the 41 problem slots of "last night"
# --------------------------------------------------------------------------- #
@dataclass
class _Scen:
    site: str
    article_id: str
    article_title: str
    block_id: str
    block_type: str
    slot_type: str
    role: Optional[str]
    anchor_text: str
    url: str
    target_url: Optional[str]
    surrounding_sentence: str
    regions: Optional[str]
    protected: int
    verdict: str
    action: str
    risk: str
    new_url: Optional[str] = None
    new_anchor: Optional[str] = None
    new_sentence: Optional[str] = None
    rationale: str = ""
    human: str = "approve"                 # approve | reject
    reject_reason: Optional[str] = None
    verify: str = ""                       # healthy | dead | '' (editorial: not probed)
    is_rollback_demo: bool = False
    steering_curtain: Optional[str] = None  # disclosure_policy | scope_policy | editorial_policy


def _aeg_scenarios() -> list[_Scen]:
    """The 38 aethelgem dead/rotted product slots the human APPROVED (批 38): 37 heal
    green + 1 (the last) caught by verify_fix and rolled back. Plus 1 protected
    affiliate-disclosure dead link the human REJECTED (safety curtain 1)."""
    out: list[_Scen] = []
    for i in range(38):
        title, block_type = _AEG_ARTICLES[i % len(_AEG_ARTICLES)]
        name, anchor = _AEG_PRODUCTS[i % len(_AEG_PRODUCTS)]
        asin = f"B0AEG{i:04d}"
        url = f"https://www.amazon.com/dp/{asin}?tag={_TAG}"
        if i < 30:
            verdict = "dead"
        elif i < 35:
            verdict = "program_ended"
        elif i < 37:
            verdict = "dead_soft404"
        else:
            verdict = "dead"                        # the rollback demo (verify will fail)
        is_rb = (i == 37)
        fix_asin = f"B0GONE{i:04d}" if is_rb else f"B0FIX{i:04d}"
        new_url = f"https://www.amazon.com/dp/{fix_asin}?tag={_TAG}"
        _l1v, l1, l2, l2e, _chain = _VERDICTS[verdict]
        out.append(_Scen(
            site=_WRITEBACK_SITE, article_id=f"demo-{i:03d}", article_title=title,
            block_id=f"b{i}", block_type=block_type, slot_type="component",
            role="core_recommendation", anchor_text=f"{name} on Amazon", url=url,
            target_url=url,
            surrounding_sentence=(f"Our top pick, the {name}, is still the best value "
                                  f"we've tested this year."),
            regions='["us","ca","uk"]' if i % 3 == 0 else '["us"]', protected=0,
            verdict=verdict, action="REPLACE_URL", risk="high", new_url=new_url,
            rationale=(f"The {verdict.replace('_', ' ')} merchant link for the {name} no "
                       f"longer resolves to a live offer; replace it with a verified in-stock "
                       f"replacement for the same product so the recommendation keeps working "
                       f"(L1 {l1}{', ' + l2 if l2 else ''})."),
            human="approve", verify=("dead" if is_rb else "healthy"),
            is_rollback_demo=is_rb,
        ))
    # the protected affiliate-disclosure dead link (safety curtain 1: zero delete)
    out.append(_Scen(
        site=_WRITEBACK_SITE, article_id="demo-disclosure",
        article_title="How We Test Lab Diamonds (Our Affiliate Disclosure)",
        block_id="b-disc", block_type="cta_box", slot_type="commercial",
        role="incidental", anchor_text="our lab-diamond testing partners",
        url="https://www.amazon.com/dp/B0AEGDISC?tag=" + _TAG,
        target_url="https://www.amazon.com/dp/B0AEGDISC?tag=" + _TAG,
        surrounding_sentence=("As an Amazon Associate we earn from qualifying purchases — "
                              "this affiliate disclosure block is part of our testing "
                              "transparency commitment."),
        regions='["us"]', protected=1, verdict="dead", action="ESCALATE_HUMAN", risk="high",
        rationale=("A merchant link inside an affiliate-DISCLOSURE block is dead. Disclosure "
                   "text is structurally protected (DisclosurePolicy): it may never be edited "
                   "or dropped by an agent, so this is escalated, not auto-fixed."),
        human="reject",
        reject_reason=("Acknowledged — the disclosure block is structurally protected, so NO "
                       "write is allowed. The dead merchant link is tracked separately; the "
                       "disclosure text itself never changes."),
        steering_curtain="disclosure_policy",
    ))
    return out


def _hotdeals_scenario() -> _Scen:
    """A dead ``reference`` citation on hotdeals (safety curtain 2: ScopePolicy forbids
    REPLACE_URL on a reference link) — the human rejected the escalation."""
    url = "https://www.soundguys.example/sony-wh-1000xm5-review"
    return _Scen(
        site="hotdeals", article_id="demo-hd-001",
        article_title="Top Headphone Deals This Week", block_id="b-ref",
        block_type="paragraph", slot_type="reference", role="incidental",
        anchor_text="the original Sony WH-1000XM5 review", url=url, target_url=url,
        surrounding_sentence=("For the full spec breakdown see the original Sony WH-1000XM5 "
                              "review we cited when this deal first ran."),
        regions='["us"]', protected=0, verdict="dead", action="ESCALATE_HUMAN", risk="medium",
        rationale=("A cited reference page 404s. ScopePolicy forbids REPLACE_URL on a "
                   "reference slot (citations are not re-pointed at merchants), so this is "
                   "escalated for a human to find the archived source."),
        human="reject",
        reject_reason=("Historical citation — leave the anchor as-is. It documents the source "
                       "we used even though the page moved; do not re-point a reference link."),
        steering_curtain="scope_policy",
    )


def _sandcart_scenario() -> _Scen:
    """A price-drift (offer_changed) product slot on sandcart (safety curtain 3:
    EditorialPolicy must downgrade the stale price claim) — the human rejected it."""
    asin = "B0SCDESK01"
    url = f"https://www.amazon.com/dp/{asin}?tag=sandcart-20"
    return _Scen(
        site="sandcart", article_id="demo-sc-001",
        article_title="Home Office Setup: Our Favorite Standing Desks", block_id="b-price",
        block_type="product_card", slot_type="component", role="core_recommendation",
        anchor_text="FlexiSpot E7 standing desk", url=url, target_url=url,
        surrounding_sentence="The FlexiSpot E7 is a rock-solid standing desk under $200.",
        regions='["us","ca"]', protected=0, verdict="offer_changed",
        action="REWRITE_SENTENCE", risk="medium",
        new_sentence=("The FlexiSpot E7 is a rock-solid standing desk — check the current "
                      "price, which has risen since we last tested it."),
        rationale=("The price jumped $199 -> $349, so the 'under $200' claim is now stale. "
                   "EditorialPolicy requires the rewrite to DROP the flagged price rather "
                   "than carry it over; the fact (a good desk) is preserved, the number is "
                   "downgraded."),
        human="reject",
        reject_reason=("The sentence already reads as a point-in-time figure and the page "
                       "shows the live price; no edit needed — leave the copy unchanged."),
        steering_curtain="editorial_policy",
    )


def build_scenarios() -> list[_Scen]:
    """The 41 problem slots of the demo night (39 aethelgem + 1 hotdeals + 1 sandcart)."""
    return _aeg_scenarios() + [_hotdeals_scenario(), _sandcart_scenario()]


# --------------------------------------------------------------------------- #
# scenario -> domain objects (pure)
# --------------------------------------------------------------------------- #
def _slot_of(s: _Scen, idx: int) -> LinkSlot:
    return LinkSlot(
        id=f"{s.site}:{s.article_id}:{s.block_id}:{idx}", site=s.site,
        article_id=s.article_id, article_title=s.article_title, block_id=s.block_id,
        block_type=s.block_type, slot_type=s.slot_type, role=s.role,
        anchor_text=s.anchor_text, url=s.url, target_url=s.target_url,
        surrounding_sentence=s.surrounding_sentence, regions=s.regions,
        protected=s.protected, status="active",
    )


def _check_of(s: _Scen, slot_id: str, *, verdict: Optional[str] = None) -> CheckResult:
    v = verdict or s.verdict
    _l1v, l1, l2, l2e, chain_kind = _VERDICTS.get(v, _VERDICTS["dead"])
    chain: list[RedirectHop] = []
    if chain_kind == "affiliate":
        chain = [RedirectHop(url=s.url, status=302),
                 RedirectHop(url="https://www.amazon.example/", status=200)]
    return CheckResult(slot_id=slot_id, l1_status=l1, redirect_chain=chain,
                       l2_verdict=l2, l2_evidence=l2e, final_verdict=_final_of(v))


def _proposal_of(s: _Scen) -> Proposal:
    return Proposal(action=s.action, new_url=s.new_url, new_anchor=s.new_anchor,
                    new_sentence=s.new_sentence, rationale=s.rationale, risk_level=s.risk)


# --------------------------------------------------------------------------- #
# the seed plan (everything the writer persists), built offline + deterministically
# --------------------------------------------------------------------------- #
@dataclass
class SeedPlan:
    now: datetime
    slots: list[LinkSlot] = field(default_factory=list)          # persisted (post-fix) state
    scan_checks: list[tuple[str, CheckResult]] = field(default_factory=list)   # (checked_at, check)
    verify_checks: list[tuple[str, CheckResult]] = field(default_factory=list)
    cards: list[Decision] = field(default_factory=list)          # 41 scan cards
    reco_card: Optional[Decision] = None                         # pe2 rollback recommendation
    snapshots: list[dict] = field(default_factory=list)          # write_snapshots rows
    audit: list[dict] = field(default_factory=list)              # audit_log rows (ts/agent/event/payload)
    scenarios: list[_Scen] = field(default_factory=list)
    card_ts: dict = field(default_factory=dict)                 # card_id -> (created_at, decided_at) ISO

    # -- convenience views -- #
    @property
    def all_cards(self) -> list[Decision]:
        return self.cards + ([self.reco_card] if self.reco_card else [])

    @property
    def slot_ids(self) -> list[str]:
        return [s.id for s in self.slots]

    @property
    def card_ids(self) -> list[str]:
        return [c.id for c in self.all_cards]

    def status_counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for c in self.all_cards:
            out[c.status] = out.get(c.status, 0) + 1
        return out

    def summary(self) -> dict:
        """The TRUE counts the demo narrator reads (``seed_demo.py --json``)."""
        by_site: dict[str, int] = {}
        by_verdict: dict[str, int] = {}
        protected = 0
        for sc in self.scenarios:                 # order-independent (slots/scenarios differ)
            by_site[sc.site] = by_site.get(sc.site, 0) + 1
            fv = _final_of(sc.verdict)
            by_verdict[fv] = by_verdict.get(fv, 0) + 1
            protected += int(sc.protected)
        approved_by_human = sum(1 for sc in self.scenarios if sc.human == "approve")
        rejected_by_human = sum(1 for sc in self.scenarios if sc.human == "reject")
        healed = sum(1 for sc in self.scenarios if sc.verify == "healthy")
        rolled = sum(1 for sc in self.scenarios if sc.is_rollback_demo)
        ev: dict[str, int] = {}
        for r in self.audit:
            ev[r["event"]] = ev.get(r["event"], 0) + 1
        return {
            "seed_mark": SEED_MARK,
            "kind": "replay (NOT live scan output, NOT real Bedrock decisions)",
            "generated_at": self.now.isoformat(),
            "slots": len(self.slots),
            "by_site": by_site,
            "by_verdict": by_verdict,
            "protected_slots": protected,
            "scan_cards": len(self.cards),
            "decision_rows": len(self.all_cards),
            "human_approved": approved_by_human,
            "human_rejected": rejected_by_human,
            "final_status": self.status_counts(),
            "links_healed": healed,
            "rolled_back": rolled,
            "write_snapshots": len(self.snapshots),
            "verify_checks": len(self.verify_checks),
            "audit_rows": len(self.audit),
            "audit_events": ev,
        }


def build_seed(now: Optional[datetime] = None) -> SeedPlan:
    """Build the whole demo night as pure data (offline, deterministic given ``now``).

    Reuses the REAL assembly code so the seeded rows are exactly what production
    produces: ``cards.build_decision_cards`` for the merge/id logic, ``writer.compute_after``
    for each snapshot's after-state, and ``writer.rollback_recommendation`` for the pe2
    recommendation card.
    """
    now = now or datetime.now(timezone.utc)
    plan = SeedPlan(now=now)
    t_scan = _dt(14, now)
    t_cards = _dt(13, now)
    t_decide = _dt(12, now)
    t_apply = _dt(11, now)

    scenarios = build_scenarios()
    plan.scenarios = scenarios

    # 1) slots + initial scan checks + proposals, then the REAL card assembly
    slot_proposals: list[SlotProposal] = []
    scen_by_slot: dict[str, _Scen] = {}
    for idx, sc in enumerate(scenarios):
        slot = _slot_of(sc, idx)
        scen_by_slot[slot.id] = sc
        check = _check_of(sc, slot.id)
        proposal = _proposal_of(sc)
        plan.scan_checks.append((t_scan.isoformat(), check))
        slot_proposals.append(SlotProposal(slot=slot, check=check, proposal=proposal))
        # audit: the scanner/judge tool_result trail (a representative slice, not 41×)
        if idx < 6 or sc.steering_curtain:
            plan.audit.append(_audit(t_scan, "scanner", "tool_result",
                                     {"tool": "http_probe", "slot_id": slot.id,
                                      "final_verdict": check.final_verdict,
                                      "l1_status": check.l1_status, "seed": SEED_MARK}))
        if sc.steering_curtain:
            plan.audit.append(_audit(_dt(13.5, now), "judge", "steering_cancel", {
                "tool": "Proposal", "policy": sc.steering_curtain, "slot_id": slot.id,
                "cancel_message": _GUIDE_MSG[sc.steering_curtain], "seed": SEED_MARK}))

    built = cards_mod.build_decision_cards(slot_proposals)   # 41 distinct urls -> 41 cards

    # 2) assign each card its human decision + worker outcome, and build write artifacts
    for card in built:
        slot_id = card.affected_slot_ids[0]
        sc = scen_by_slot[slot_id]
        slot = next(s for s in (sp.slot for sp in slot_proposals) if s.id == slot_id)
        card_created = t_cards.isoformat()
        if sc.human == "reject":
            card.status = "rejected"
            card.reject_reason = sc.reject_reason
            plan.cards.append(card)
            plan.card_ts[card.id] = (card_created, t_decide.isoformat())
            plan.audit.append(_audit(t_decide, "judge", "interrupt", {
                "interrupt": "everlink_high_risk_fix", "decision_id": card.id,
                "response": "rejected", "seed": SEED_MARK}))
            continue

        # approved by the human
        plan.audit.append(_audit(t_decide, "judge", "interrupt", {
            "interrupt": "everlink_high_risk_fix", "decision_id": card.id,
            "response": "approved", "seed": SEED_MARK}))
        before = {"url": slot.url, "target_url": slot.target_url,
                  "anchor_text": slot.anchor_text,
                  "surrounding_sentence": slot.surrounding_sentence, "status": slot.status}
        after = writer.compute_after(before, card.proposal)
        verify_verdict = sc.verify or "healthy"
        vcheck = _check_of(sc, slot_id, verdict=verify_verdict)
        plan.verify_checks.append((t_apply.isoformat(), vcheck))
        plan.audit.append(_audit(t_apply, "writer", "write", {
            "decision_id": card.id, "slot_id": slot_id, "site": slot.site,
            "action": card.proposal.action, "snapshot_id": 0,
            "final_status": ("rolled_back" if sc.is_rollback_demo else "applied"),
            "after": after, "seed": SEED_MARK}))
        ok, reason = writer.interpret_verify(vcheck)
        plan.audit.append(_audit(t_apply, "writer", "verify", {
            "decision_id": card.id, "slot_id": slot_id, "probed": True, "verified": ok,
            "verdict": verify_verdict, "reason": reason, "seed": SEED_MARK}))
        rolled_back = sc.is_rollback_demo
        plan.snapshots.append({
            "slot_id": slot_id, "decision_id": card.id, "before": before, "after": after,
            "applied_at": t_apply.isoformat(),
            "rolled_back_at": (t_apply.isoformat() if rolled_back else None),
        })
        if rolled_back:
            # persist the slot content as RESTORED (before), and spawn pe2's recommendation
            persisted = slot.model_copy(update={"url": before["url"],
                                                "target_url": before["target_url"],
                                                "status": before["status"]})
            plan.slots.append(persisted)
            outcome = writer.FixOutcome(
                decision_id=card.id,
                writes=[writer.SlotWrite(slot_id=slot_id, site=slot.site,
                                         action=card.proposal.action, status="rolled_back")],
                verifies=[writer.VerifyResult(slot_id=slot_id, verified=False, probed=True,
                                              verdict=verify_verdict, reason=reason)],
                rolled_back=[slot_id],
                dead_letter=f"slot '{slot_id}' {reason} (rolled back)")
            reco = writer.rollback_recommendation(card, outcome)
            plan.reco_card = reco
            # the failed card dead-letters to rejected (worker flips approved -> rejected)
            card.status = "rejected"
            card.reject_reason = outcome.dead_letter
            plan.cards.append(card)
            plan.card_ts[card.id] = (card_created, t_apply.isoformat())
            plan.audit.append(_audit(t_apply, "writer", "rollback", {
                "decision_id": card.id, "slot_id": slot_id,
                "recommendation_card": (reco.id if reco else None), "seed": SEED_MARK}))
            plan.audit.append(_audit(t_apply, "worker", "dead_letter", {
                "decision_id": card.id, "reason": outcome.dead_letter, "seed": SEED_MARK}))
        else:
            # healed: persist the slot content as the fixed (after) state
            persisted = slot.model_copy(update={"url": after["url"],
                                                "target_url": after["target_url"],
                                                "status": after["status"]})
            plan.slots.append(persisted)
            card.status = "applied"
            plan.cards.append(card)
            plan.card_ts[card.id] = (card_created, t_apply.isoformat())

    # rejected/never-written slots persist in their ORIGINAL state
    written = {sp["slot_id"] for sp in plan.snapshots}
    for sp in slot_proposals:
        if sp.slot.id not in written and sp.slot.id not in plan.slot_ids:
            plan.slots.append(sp.slot)

    # 3) the recommendation card is pending (worker never claims it) — surfaced to the human
    if plan.reco_card is not None:
        plan.card_ts[plan.reco_card.id] = (t_apply.isoformat(), None)

    # 4) the push-layer notify audit (morning brief + decision cards)
    plan.audit.append(_audit(_dt(13.75, now), "notifier", "notify", {
        "kind": "morning_brief", "channels": ["email", "telegram"], "sent": 2,
        "skipped": 0, "problem_slots": len(scenarios), "seed": SEED_MARK}))
    plan.audit.append(_audit(t_decide, "notifier", "notify", {
        "kind": "decision_cards", "channels": ["email"], "sent": 1, "skipped": 0,
        "cards": len(built), "seed": SEED_MARK}))

    plan.audit.sort(key=lambda r: r["ts"])
    return plan


# the guide messages steering would have emitted (mirrors steering._GUIDE + policy copy)
_GUIDE_MSG = {
    "disclosure_policy": ("Tool call cancelled by EverLink steering [disclosure_policy]. "
                          "slot is protected (affiliate-disclosure keywords). Re-decide with "
                          "action=ESCALATE_HUMAN; disclosure-bearing blocks are never edited "
                          "or dropped by an agent."),
    "scope_policy": ("Tool call cancelled by EverLink steering [scope_policy]. slot_type="
                     "reference may not be REPLACE_URL. Re-decide with REWRITE_SENTENCE "
                     "(downgrade the claim) or ESCALATE_HUMAN; never REPLACE_URL a reference "
                     "link."),
    "editorial_policy": ("Tool call cancelled by EverLink steering [editorial_policy]. the "
                         "rewrite preserves the flagged stale price '199'; a re-link must "
                         "downgrade or remove it, not carry it over."),
}


def _audit(ts: datetime, agent: str, event: str, payload: dict) -> dict:
    return {"ts": ts.isoformat(), "agent": agent, "event": event,
            "payload": json.dumps(payload, default=str)}


# --------------------------------------------------------------------------- #
# guarded writer — EverLink's OWN store only, ONE atomic transaction (spec §5
# "不产生半写状态"). Reuses db.SLOT_COLUMNS + queue.decision_to_row so the seeded
# rows are serialized EXACTLY like production writes; every statement is scoped to
# the deterministic seed ids / SEED_MARK so it never touches real scanned data.
# --------------------------------------------------------------------------- #
def _parse_ts(v):
    """ISO string (as stored on the plan) -> tz-aware datetime for psycopg, or None."""
    if v is None:
        return None
    return datetime.fromisoformat(v) if isinstance(v, str) else v


def _upsert_slots(cur, slots: list[LinkSlot]) -> None:
    cols = db.SLOT_COLUMNS
    placeholders = ", ".join(["%s"] * len(cols))
    updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in cols if c != "id")
    sql = (f"INSERT INTO link_slots ({', '.join(cols)}) VALUES ({placeholders}) "
           f"ON CONFLICT (id) DO UPDATE SET {updates}, updated_at = now()")
    cur.executemany(sql, [
        (s.id, s.site, str(s.article_id), s.article_title, str(s.block_id), s.block_type,
         s.slot_type, s.role, s.anchor_text, s.url, s.target_url, s.surrounding_sentence,
         s.regions, int(s.protected), s.status) for s in slots])


def _insert_checks(cur, checks: list[tuple[str, CheckResult]]) -> None:
    sql = ("INSERT INTO slot_checks (slot_id, checked_at, l1_status, l1_redirect_chain, "
           "l2_verdict, l2_evidence, final_verdict) VALUES (%s,%s,%s,%s,%s,%s,%s) "
           "ON CONFLICT (slot_id, checked_at) DO NOTHING")
    cur.executemany(sql, [
        (c.slot_id, _parse_ts(ts), c.l1_status,
         json.dumps([h.model_dump() for h in c.redirect_chain]),
         c.l2_verdict, c.l2_evidence, c.final_verdict) for ts, c in checks])


def _upsert_decisions(cur, plan: "SeedPlan") -> None:
    # reuse queue.decision_to_row for the JSON columns, then add the demo timeline
    sql = ("INSERT INTO decisions (id, affected_slot_ids, proposal, status, created_at, "
           "decided_at, reject_reason) VALUES (%s,%s,%s,%s,%s,%s,%s) "
           "ON CONFLICT (id) DO UPDATE SET affected_slot_ids = EXCLUDED.affected_slot_ids, "
           "proposal = EXCLUDED.proposal, status = EXCLUDED.status, "
           "created_at = EXCLUDED.created_at, decided_at = EXCLUDED.decided_at, "
           "reject_reason = EXCLUDED.reject_reason")
    rows = []
    for c in plan.all_cards:
        _id, slots_json, proposal_json, status, reject_reason = queue.decision_to_row(c)
        created, decided = plan.card_ts.get(c.id, (None, None))
        rows.append((_id, slots_json, proposal_json, status,
                     _parse_ts(created), _parse_ts(decided), reject_reason))
    cur.executemany(sql, rows)


def _insert_snapshots(cur, snapshots: list[dict]) -> None:
    sql = ("INSERT INTO write_snapshots (slot_id, decision_id, before_json, after_json, "
           "applied_at, rolled_back_at) VALUES (%s,%s,%s,%s,%s,%s)")
    cur.executemany(sql, [
        (s["slot_id"], s["decision_id"], json.dumps(s["before"], default=str),
         json.dumps(s["after"], default=str), _parse_ts(s["applied_at"]),
         _parse_ts(s["rolled_back_at"])) for s in snapshots])


def _insert_audit(cur, audit: list[dict]) -> None:
    sql = "INSERT INTO audit_log (ts, agent, event, payload) VALUES (%s,%s,%s,%s)"
    cur.executemany(sql, [(_parse_ts(r["ts"]), r["agent"], r["event"], r["payload"])
                          for r in audit])


def write_seed(conn, plan: Optional["SeedPlan"] = None, *, ensure: bool = True) -> dict:
    """Persist the demo seed into EverLink's OWN store as ONE guarded transaction.

    Idempotent: re-running overwrites exactly the seed-owned rows (deterministic
    namespaced ids + ``SEED_MARK``-tagged audit) and never touches real scanned data.
    Refuses a forbidden source/production host via ``db._assert_writable`` (Blue Neon
    guard). On any error the transaction rolls back — no half-written dataset. Returns
    ``plan.summary()`` (the true counts) so the caller can print/verify them.
    """
    plan = plan or build_seed()
    db._assert_writable(conn.info.dsn or "")
    if ensure:
        db.ensure_schema(conn)                    # idempotent; guarded; commits its own txn
    slot_ids, card_ids = plan.slot_ids, plan.card_ids
    with conn.transaction():                      # atomic: all-or-nothing seed
        cur = conn.cursor()
        _upsert_slots(cur, plan.slots)
        # delete-then-insert keeps the BIGSERIAL/no-natural-key tables idempotent
        cur.execute("DELETE FROM slot_checks WHERE slot_id = ANY(%s)", (slot_ids,))
        _insert_checks(cur, list(plan.scan_checks) + list(plan.verify_checks))
        _upsert_decisions(cur, plan)
        cur.execute("DELETE FROM write_snapshots WHERE slot_id = ANY(%s)", (slot_ids,))
        _insert_snapshots(cur, plan.snapshots)
        cur.execute("DELETE FROM audit_log WHERE payload LIKE %s", (f"%{SEED_MARK}%",))
        _insert_audit(cur, plan.audit)
    return plan.summary()


def reset_seed(conn, *, plan: Optional["SeedPlan"] = None) -> dict:
    """Remove EXACTLY the demo seed, leaving any real scanned data untouched.

    Recomputes the deterministic ids (they do not depend on ``now``) + the
    ``SEED_MARK`` audit tag, then deletes in FK-safe order: snapshots/checks (also
    cascade from link_slots) -> decisions -> link_slots -> audit. Returns per-table
    deleted counts.
    """
    plan = plan or build_seed()
    db._assert_writable(conn.info.dsn or "")
    slot_ids, card_ids = plan.slot_ids, plan.card_ids
    with conn.transaction():
        cur = conn.cursor()
        cur.execute("DELETE FROM write_snapshots WHERE slot_id = ANY(%s) OR decision_id = ANY(%s)",
                    (slot_ids, card_ids))
        n_snap = cur.rowcount
        cur.execute("DELETE FROM slot_checks WHERE slot_id = ANY(%s)", (slot_ids,))
        n_check = cur.rowcount
        cur.execute("DELETE FROM decisions WHERE id = ANY(%s)", (card_ids,))
        n_dec = cur.rowcount
        cur.execute("DELETE FROM link_slots WHERE id = ANY(%s)", (slot_ids,))
        n_slot = cur.rowcount
        cur.execute("DELETE FROM audit_log WHERE payload LIKE %s", (f"%{SEED_MARK}%",))
        n_audit = cur.rowcount
    return {"write_snapshots": n_snap, "slot_checks": n_check, "decisions": n_dec,
            "link_slots": n_slot, "audit_log": n_audit}


def seed_stats(conn) -> dict:
    """Count the seed-owned rows currently in the DB (verification / ``--json``).

    Read-only. Uses the same deterministic ids + SEED_MARK so it reports exactly the
    demo dataset's footprint, whatever else lives in the store.
    """
    plan = build_seed()
    slot_ids, card_ids = plan.slot_ids, plan.card_ids
    like = f"%{SEED_MARK}%"
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM link_slots WHERE id = ANY(%s)", (slot_ids,))
        slots = cur.fetchone()[0]
        cur.execute("SELECT status, count(*) FROM decisions WHERE id = ANY(%s) GROUP BY status",
                    (card_ids,))
        by_status = {r[0]: int(r[1]) for r in cur.fetchall()}
        cur.execute("SELECT count(*) FROM slot_checks WHERE slot_id = ANY(%s)", (slot_ids,))
        checks = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM write_snapshots WHERE slot_id = ANY(%s)", (slot_ids,))
        snaps = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM write_snapshots WHERE slot_id = ANY(%s) "
                    "AND rolled_back_at IS NOT NULL", (slot_ids,))
        rolled = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM audit_log WHERE payload LIKE %s", (like,))
        audit = cur.fetchone()[0]
    conn.rollback()                               # close the read txn (idle-in-transaction guard)
    return {"slots": slots, "decisions": sum(by_status.values()), "by_status": by_status,
            "slot_checks": checks, "write_snapshots": snaps, "rolled_back_snapshots": rolled,
            "audit_rows": audit}
