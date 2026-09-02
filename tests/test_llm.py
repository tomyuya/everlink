"""Offline tests for the model-provider layer (everlink.llm).

Verifies StubModel yields a valid Strands stream, produces a Proposal via
structured_output, and that a real Strands Agent runs end-to-end on StubModel
(no AWS credentials, no network).
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from everlink.llm import StubModel, aws_credentials_available  # noqa: E402
from everlink.model import Proposal  # noqa: E402

USER_MSG = [{"role": "user", "content": [{"text": "hi"}]}]


def _stream_events(model, messages):
    async def run():
        return [e async for e in model.stream(messages)]

    return asyncio.run(run())


def test_stub_stream_yields_valid_sequence():
    events = _stream_events(StubModel(text="hello"), USER_MSG)
    kinds = [next(iter(e)) for e in events]
    assert kinds[0] == "messageStart"
    assert "contentBlockDelta" in kinds
    assert "messageStop" in kinds
    assert kinds[-1] == "metadata"
    text = "".join(
        e["contentBlockDelta"]["delta"]["text"] for e in events if "contentBlockDelta" in e
    )
    assert text == "hello"


def test_stub_stop_reason_is_end_turn():
    events = _stream_events(StubModel(text="x"), USER_MSG)
    stops = [e["messageStop"] for e in events if "messageStop" in e]
    assert stops and stops[0]["stopReason"] == "end_turn"


def test_stub_structured_output_is_proposal():
    model = StubModel(structured={
        "action": "ESCALATE_HUMAN", "rationale": "stub says escalate", "risk_level": "low",
    })

    async def run():
        out = [e async for e in model.structured_output(Proposal, USER_MSG)]
        return out[-1]["output"]

    p = asyncio.run(run())
    assert isinstance(p, Proposal)
    assert p.action == "ESCALATE_HUMAN"
    assert p.risk_level == "low"


def test_stub_structured_output_callable_per_prompt():
    model = StubModel(structured=lambda prompt: {
        "action": "REPLACE_URL", "new_url": "https://example.com/x",
        "rationale": "dynamic", "risk_level": "medium",
    })

    async def run():
        out = [e async for e in model.structured_output(Proposal, USER_MSG)]
        return out[-1]["output"]

    p = asyncio.run(run())
    assert p.action == "REPLACE_URL" and p.new_url == "https://example.com/x"


def test_credentials_probe_returns_bool():
    assert isinstance(aws_credentials_available(), bool)


def test_strands_agent_runs_on_stub_model():
    """The real orchestration entrypoint must work offline on StubModel."""
    from strands import Agent

    agent = Agent(model=StubModel(text="OK"), system_prompt="probe")
    result = agent("ping")
    assert result is not None
    assert "OK" in str(result)


ALL = [v for k, v in sorted(globals().items()) if k.startswith("test_")]


if __name__ == "__main__":
    failed = 0
    for fn in ALL:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"FAIL {fn.__name__}: {type(e).__name__}: {e}")
    print(f"\n{len(ALL)-failed}/{len(ALL)} passed")
    sys.exit(1 if failed else 0)
