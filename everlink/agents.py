"""Scanner + Judge agents (Strands) and the deterministic scan pipeline (spec §4.1/§6).

Topology honesty (spec §4.2): this is an **Agent-as-Tool sequential pipeline**, not
a Swarm — the stages have a strict data dependency (discover -> detect -> judge),
so there is nothing for peer agents to negotiate.

Two consumption modes share the same tools:
  * ``run_scan(...)`` — deterministic orchestration (plain Python calls the tools'
    underlying functions). Detection needs no LLM, so a real dead-link report runs
    offline; the Judge is invoked per-problem only when a model is supplied.
  * ``build_scanner`` / ``build_judge`` — real Strands ``Agent``s wrapping the same
    ``@tool`` functions, so an LLM can drive ad-hoc investigation and (for the
    Judge) emit a ``Proposal`` via ``structured_output_model`` (spec §6).

The Judge never fabricates: if the model does not return a structured Proposal we
ESCALATE_HUMAN rather than guess.
"""
from __future__ import annotations

from typing import Optional
from urllib.parse import quote, urlparse

from pydantic import BaseModel, Field
from strands import Agent, tool

from . import adapters, detect, steering
from .l2 import probe_l2
from .llm import StubModel
from .model import CheckResult, LinkSlot, Proposal
from .probes import probe_url

# --------------------------------------------------------------------------- #
# @tool wrappers (thin; the real logic lives in adapters / detect / probes / l2)
# --------------------------------------------------------------------------- #
_MERCHANT_SEARCH = {
    "amazon": ("https://www.amazon.com/s?k={q}", "Amazon"),
    "aliexpress": ("https://www.aliexpress.com/wholesale?SearchText={q}", "AliExpress"),
    "ebay": ("https://www.ebay.com/sch/i.html?_nkw={q}", "eBay"),
    "etsy": ("https://www.etsy.com/search?q={q}", "Etsy"),
    "walmart": ("https://www.walmart.com/search?q={q}", "Walmart"),
    "target": ("https://www.target.com/s?searchTerm={q}", "Target"),
    "bestbuy": ("https://www.bestbuy.com/site/searchpage.jsp?st={q}", "Best Buy"),
}


@tool
def extract_slots(site: str, limit: int = 20) -> dict:
    """Discover a site's outbound link slots (READ-ONLY; never writes back).

    A first-party site name (aethelgem/sandcart/hotdeals) reads its CSV snapshot;
    any other value (a page URL, sitemap URL, or list) uses the generic adapter.
    Returns a count plus up to `limit` example slots.
    """
    slots = adapters.extract_slots(site)
    sample = slots[: max(0, limit)]
    return {
        "site": site,
        "total_discovered": len(slots),
        "returned": len(sample),
        "slots": [{"id": s.id, "url": s.url, "slot_type": s.slot_type,
                   "anchor_text": s.anchor_text, "article_id": s.article_id}
                  for s in sample],
    }


@tool
def http_probe(url: str) -> dict:
    """L1 probe of ONE url (read-only): HTTP status + affiliate redirect-chain
    analysis. Returns the verdict and the redirect chain as evidence."""
    r = probe_url(url, timeout=15.0)
    return {
        "url": url, "l1_status": r.l1_status, "final_verdict": r.final_verdict,
        "redirect_chain": [{"url": h.url, "status": h.status} for h in r.redirect_chain],
        "evidence": r.l2_evidence, "error": r.error,
    }


@tool
def page_parse(url: str) -> dict:
    """L2 parse of ONE url (read-only): fetch the page and classify whether the
    OFFER is still live (ok / dead / unavailable / blocked / price_anomaly)."""
    r = probe_l2(url, timeout=20.0)
    return {"url": url, "verdict": r.verdict, "evidence": r.evidence,
            "title": r.title, "extracted_price": r.extracted_price}


@tool
def find_alternatives(url: str, anchor_text: str = "", article_title: str = "") -> dict:
    """Propose replacement candidates for a dead/changed outbound link.

    Heuristic and honest: returns SEARCH entrypoints (the merchant's own search for
    the product, plus a web search), NOT fabricated deep links. Any new_url the
    Judge picks must be verified (L1+L2) by verify_fix before it is written.
    """
    host = (urlparse(url).hostname or "").lower()
    query = (anchor_text or article_title or "").strip()
    candidates: list[dict] = []
    if query:
        for key, (tmpl, name) in _MERCHANT_SEARCH.items():
            if key in host:
                candidates.append({"url": tmpl.format(q=quote(query)),
                                   "why": f"{name} search for the same product"})
                break
        candidates.append({"url": f"https://www.google.com/search?q={quote(query)}",
                           "why": "web search for a live equivalent"})
    return {
        "original_url": url, "query": query, "candidates": candidates,
        "note": ("Candidates are SEARCH entrypoints, not verified deep links. "
                 "Never fabricate a specific product URL you cannot verify; if no "
                 "verifiable replacement exists, ESCALATE_HUMAN."),
    }


# --------------------------------------------------------------------------- #
# agents
# --------------------------------------------------------------------------- #
SCANNER_SYSTEM_PROMPT = (
    "You are EverLink's Scanner agent. You perform READ-ONLY discovery and detection "
    "of link rot in a site's outbound links. Tools: extract_slots (discover outbound "
    "link slots), http_probe (L1: HTTP status + affiliate redirect-chain analysis), "
    "page_parse (L2: fetch a page and classify whether the OFFER is still live).\n"
    "Detection discipline (spec §4.1): an affiliate hop that drops its tracking tag or "
    "bounces to the network's homepage means program_ended; an HTTP 200 page can still "
    "be a soft-404 ('Currently unavailable'), so escalate to L2; when blocked, "
    "rate-limited, or timed out, report needs_human_recheck — NEVER fabricate a healthy "
    "verdict you cannot prove. You never modify any site."
)

JUDGE_SYSTEM_PROMPT = (
    "You are EverLink's Judge agent. For ONE detected problem link you propose exactly "
    "ONE fix as a structured Proposal {action, new_url, new_anchor, new_sentence, "
    "rationale, risk_level}. Actions: REPLACE_URL, REWRITE_ANCHOR, REWRITE_SENTENCE, "
    "DROP_BLOCK, ESCALATE_HUMAN.\n"
    "Hard rules (spec §4.3 steering — also enforced by hooks; always obey them):\n"
    "1. Disclosure: a protected slot (affiliate/commission/partner/sponsored/disclosure "
    "context) must NEVER be modified or dropped — return ESCALATE_HUMAN.\n"
    "2. Scope: slot_type=reference must NOT get REPLACE_URL to a commercial target; "
    "prefer REWRITE_SENTENCE or ESCALATE_HUMAN. DROP_BLOCK only for incidental links.\n"
    "3. Editorial: REWRITE_SENTENCE must preserve the sentence's factual claims or "
    "explicitly downgrade them — no stale price/year/superlative may survive a re-link.\n"
    "4. Honesty: NEVER fabricate a URL. Use find_alternatives for SEARCH entrypoints; a "
    "specific replacement deep link is acceptable only if it can be verified. If you "
    "cannot verify a fix, ESCALATE_HUMAN — that is a correct outcome, not a failure.\n"
    "risk_level: low (anchor/cosmetic), medium (re-link to a verified equivalent), "
    "high (sentence rewrite, drop, or anything touching disclosure/commercial intent)."
)


def build_scanner(model, hooks: Optional[list] = None, callback_handler=None,
                  audit_sink=None, enforce: bool = False) -> Agent:
    """Scanner agent (spec §6): discovery + L1/L2 detection tools, read-only.

    ``callback_handler=None`` keeps the agent SILENT: Strands' default prints
    every tool call ("Tool #1: ...") to stdout, but EverLink agents are backend
    components — the CLI/report owns user-facing output.

    ``enforce=True`` assembles the spec §6 scanner hooks (``[audit]``) unless an
    explicit ``hooks`` list is given. ``audit_sink`` chooses where audit records
    go (default: an in-memory collector; production passes ``steering.db_audit_sink``).
    """
    if hooks is None:
        hooks = steering.scanner_hooks(audit_sink) if enforce else []
    return Agent(model=model, system_prompt=SCANNER_SYSTEM_PROMPT,
                 tools=[extract_slots, http_probe, page_parse], hooks=list(hooks),
                 callback_handler=callback_handler)


def build_judge(model, hooks: Optional[list] = None, callback_handler=None,
                audit_sink=None, enforce: bool = False) -> Agent:
    """Judge agent (spec §6): forced ``structured_output_model=Proposal``.

    Silent by default (see build_scanner); pass a callback_handler to stream.

    ``enforce=True`` assembles the spec §6 judge hooks (``[scope_policy,
    editorial_policy, audit]``) unless an explicit ``hooks`` list is given.
    Enforcement is OPT-IN: the Evals harness builds a raw judge (no hooks) so the
    policy oracle scores the Judge's actual proposals — enforcement (hooks) and
    scoring (oracle) are deliberately separate consumers of the same policy module.
    """
    if hooks is None:
        hooks = steering.judge_hooks(audit_sink) if enforce else []
    return Agent(model=model, system_prompt=JUDGE_SYSTEM_PROMPT,
                 tools=[find_alternatives], structured_output_model=Proposal,
                 hooks=list(hooks), callback_handler=callback_handler)


def build_stub_judge(hooks: Optional[list] = None, callback_handler=None,
                     audit_sink=None, enforce: bool = False) -> Agent:
    """Judge on an offline ``StubModel`` — for CI / ``--judge stub`` demos.

    HONEST by construction: a stub cannot really judge a fix, so it always
    returns ESCALATE_HUMAN (a correct, non-fabricating outcome). Its value is
    proving the orchestration + Proposal schema wiring runs end-to-end with zero
    AWS credentials; real fix quality is verified on Bedrock (scripts/verify_bedrock.py
    + Strands Evals, spec §8). Steering hooks still run and are still tested.
    """
    model = StubModel(structured={
        "action": "ESCALATE_HUMAN",
        "rationale": ("[offline stub judge] detection-only run; a stub cannot verify "
                      "a replacement, so it escalates rather than fabricate a fix. "
                      "Use --judge bedrock for real proposals."),
        "risk_level": "high",
    })
    return build_judge(model, hooks=hooks, callback_handler=callback_handler,
                       audit_sink=audit_sink, enforce=enforce)


def _judge_prompt(slot: LinkSlot, check: CheckResult) -> str:
    chain = " -> ".join(f"{h.url} ({h.status})" for h in check.redirect_chain) or "(no redirects)"
    return (
        f"A problem link was detected on site '{slot.site}'. Propose ONE fix.\n"
        f"- slot_id: {slot.id}\n"
        f"- slot_type: {slot.slot_type}   protected: {slot.protected}\n"
        f"- article: {slot.article_title!r}  (article_id={slot.article_id})\n"
        f"- anchor_text: {slot.anchor_text!r}\n"
        f"- url: {slot.url}\n"
        f"- surrounding_sentence: {slot.surrounding_sentence!r}\n"
        f"- final_verdict: {check.final_verdict}\n"
        f"- L1 HTTP {check.l1_status}; redirect chain: {chain}\n"
        f"- L2: {check.l2_verdict}; evidence: {check.l2_evidence}\n"
    )


def judge_slot(judge: Agent, slot: LinkSlot, check: CheckResult) -> Proposal:
    """Run the Judge on one problem slot; never fabricate if output is missing.

    The slot (and the price the article claimed, for the editorial hook) is threaded
    via ``invocation_state`` so the spec §6 steering hooks can enforce against the
    real context. This is harmless when the judge has no hooks (Evals scoring path).
    """
    claimed_price = detect.claimed_price_from_text(slot.surrounding_sentence or "")
    result = judge(
        _judge_prompt(slot, check),
        invocation_state={"slot": slot.model_dump(), "claimed_price": claimed_price},
    )
    so = getattr(result, "structured_output", None)
    if isinstance(so, Proposal):
        return so
    return Proposal(
        action="ESCALATE_HUMAN",
        rationale="Judge returned no structured Proposal; escalating rather than guessing.",
        risk_level="high",
    )


# --------------------------------------------------------------------------- #
# deterministic scan pipeline (no LLM required for detection)
# --------------------------------------------------------------------------- #
class SlotProposal(BaseModel):
    slot: LinkSlot
    check: CheckResult
    proposal: Proposal


class ScanReport(BaseModel):
    source: str
    scanned: int = 0
    checks: list[CheckResult] = Field(default_factory=list)
    proposals: list[SlotProposal] = Field(default_factory=list)
    judge_backend: str = "none"          # none | stub | bedrock

    def problems(self) -> list[CheckResult]:
        return [c for c in self.checks if c.final_verdict != "healthy"]

    def verdict_counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for c in self.checks:
            out[c.final_verdict] = out.get(c.final_verdict, 0) + 1
        return out


def run_scan(source, *, limit: Optional[int] = 25, rate_delay: float = 1.0,
             timeout: float = 15.0, use_l2: bool = True, judge: Optional[Agent] = None,
             judge_backend: str = "none", **adapter_kwargs) -> ScanReport:
    """Discover -> detect (deterministic) -> optionally judge each problem.

    ``source`` is a first-party site name OR any URL/sitemap/list (generic adapter).
    Detection is pure HTTP (no LLM); the Judge runs only if ``judge`` is supplied.
    """
    slots = adapters.extract_slots(source, **adapter_kwargs)
    if limit is not None:
        slots = slots[:limit]
    checks = detect.check_slots(slots, rate_delay=rate_delay, timeout=timeout, use_l2=use_l2)

    proposals: list[SlotProposal] = []
    if judge is not None:
        by_id = {s.id: s for s in slots}
        for c in checks:
            if c.final_verdict == "healthy":
                continue
            slot = by_id.get(c.slot_id)
            if slot is not None:
                proposals.append(SlotProposal(slot=slot, check=c,
                                              proposal=judge_slot(judge, slot, c)))

    return ScanReport(source=str(source), scanned=len(slots), checks=checks,
                      proposals=proposals, judge_backend=judge_backend)
