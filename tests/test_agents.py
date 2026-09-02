"""Agent-layer tests (everlink.agents): @tool wrappers, the Judge's structured
output on StubModel, Scanner construction, and an end-to-end ``run_scan`` against
the local fixture server.

Everything runs OFFLINE (StubModel + fixture server): no AWS credentials, no
external network. The Judge tests prove the MODERN structured-output path
(``agent(prompt, structured_output_model=Proposal)``) resolves on the stub, so the
same Judge code runs unchanged on Bedrock. ``run_scan`` asserts the full detection
pyramid fires on every rot class and that each problem gets exactly one Proposal.
"""
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from everlink import agents  # noqa: E402
from everlink.fixtures import make_server  # noqa: E402
from everlink.llm import StubModel  # noqa: E402
from everlink.model import CheckResult, LinkSlot, Proposal, RedirectHop  # noqa: E402

_server = None
_thread = None
_base = None


def setup_module(module):  # noqa: ARG001
    global _server, _thread, _base
    _server = make_server(port=0)
    host, port = _server.server_address
    _base = f"http://{host}:{port}"
    _thread = threading.Thread(target=_server.serve_forever, daemon=True)
    _thread.start()


def teardown_module(module):  # noqa: ARG001
    if _server is not None:
        _server.shutdown()
        _server.server_close()
    if _thread is not None:
        _thread.join(timeout=5)


def _slot(url, **kw):
    base = dict(id="s1", site="test", article_id="a1", article_title="T",
                block_id="b1", block_type="paragraph", slot_type="commercial", url=url)
    base.update(kw)
    return LinkSlot(**base)


# --- @tool wrappers are directly callable (test-friendly) -------------------
def test_find_alternatives_returns_search_entrypoints_not_fabricated_deeplinks():
    r = agents.find_alternatives("https://www.amazon.com/dp/B0XYZ",
                                 anchor_text="Sony WH-1000XM5")
    urls = [c["url"] for c in r["candidates"]]
    assert any("amazon.com/s?k=" in u for u in urls)      # the merchant's own search
    assert any("google.com/search" in u for u in urls)    # a web search fallback
    assert not any("/dp/" in u for u in urls)             # never a fabricated deep link
    assert "Never fabricate" in r["note"]


def test_find_alternatives_without_query_is_honestly_empty():
    r = agents.find_alternatives("https://shop.example.com/thing")
    assert r["candidates"] == []                          # nothing verifiable to propose


def test_http_probe_tool_reports_l1_dead():
    r = agents.http_probe(f"{_base}/dead")
    assert r["l1_status"] == 404 and r["final_verdict"] == "dead"


def test_page_parse_tool_reports_l2_unavailable():
    r = agents.page_parse(f"{_base}/unavailable")
    assert r["verdict"] == "unavailable"


# --- Judge: structured output resolves on the stub --------------------------
def test_judge_returns_structured_proposal_on_stub():
    model = StubModel(structured={"action": "REWRITE_ANCHOR",
                                  "rationale": "tighten the anchor", "risk_level": "low"})
    judge = agents.build_judge(model)
    slot = _slot(f"{_base}/dead", anchor_text="click here")
    check = CheckResult(slot_id=slot.id, l1_status=404, final_verdict="dead",
                        redirect_chain=[RedirectHop(url=slot.url, status=404)])
    prop = agents.judge_slot(judge, slot, check)
    assert isinstance(prop, Proposal)
    assert prop.action == "REWRITE_ANCHOR" and prop.risk_level == "low"


def test_stub_judge_escalates_rather_than_fabricate():
    judge = agents.build_stub_judge()
    slot = _slot(f"{_base}/dead")
    check = CheckResult(slot_id=slot.id, l1_status=404, final_verdict="dead")
    prop = agents.judge_slot(judge, slot, check)
    assert prop.action == "ESCALATE_HUMAN"                # honest: no invented fix


# --- Scanner construction ---------------------------------------------------
def test_scanner_agent_builds_and_runs_on_stub():
    scanner = agents.build_scanner(StubModel(text="scan-ok"))
    res = scanner("discover outbound slots")
    assert res is not None and "scan-ok" in str(res)


# --- end-to-end run_scan against the fixture server -------------------------
def test_run_scan_detects_every_rot_class_and_judges_each_problem():
    report = agents.run_scan(f"{_base}/link-farm", limit=None, rate_delay=0.0,
                             use_l2=True, judge=agents.build_stub_judge(),
                             judge_backend="stub", include_internal=True)
    counts = report.verdict_counts()
    assert counts.get("dead", 0) >= 1                     # /dead
    assert counts.get("offer_changed", 0) >= 1            # /unavailable (soft-404)
    assert counts.get("program_ended", 0) >= 1            # /affiliate/deal dropped its tag
    assert counts.get("healthy", 0) >= 1                  # /ok
    # exactly the problem slots got a proposal; healthy links did not
    problem_ids = {c.slot_id for c in report.problems()}
    proposal_ids = {sp.check.slot_id for sp in report.proposals}
    assert proposal_ids == problem_ids
    assert all(sp.proposal.action == "ESCALATE_HUMAN" for sp in report.proposals)


def test_run_scan_detection_only_needs_no_judge():
    report = agents.run_scan(f"{_base}/link-farm", limit=None, rate_delay=0.0,
                             use_l2=True, judge=None, include_internal=True)
    assert report.judge_backend == "none"
    assert report.proposals == []                         # no judge -> no proposals
    assert len(report.problems()) >= 3                    # detection still works offline


ALL = [v for k, v in sorted(globals().items()) if k.startswith("test_")]


if __name__ == "__main__":
    setup_module(None)
    failed = 0
    try:
        for fn in ALL:
            try:
                fn()
                print(f"PASS {fn.__name__}")
            except Exception as e:  # noqa: BLE001
                failed += 1
                print(f"FAIL {fn.__name__}: {type(e).__name__}: {e}")
    finally:
        teardown_module(None)
    print(f"\n{len(ALL)-failed}/{len(ALL)} passed")
    sys.exit(1 if failed else 0)
