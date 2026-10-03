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
    # 不解析本机 profile、SSO 或实例元数据；只验证凭据探测的布尔契约。
    from unittest.mock import patch

    with patch("boto3.session.Session.get_credentials", return_value=None):
        assert aws_credentials_available() is False


def test_strands_agent_runs_on_stub_model():
    """The real orchestration entrypoint must work offline on StubModel."""
    from strands import Agent

    agent = Agent(model=StubModel(text="OK"), system_prompt="probe")
    result = agent("ping")
    assert result is not None
    assert "OK" in str(result)


# 以下回归由 pytest 收集；真实 SDK 路由保留，AWS chain 和传输完全替身化。
import socket
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest


@pytest.fixture
def mantle_io(monkeypatch, tmp_path):
    import boto3
    import botocore.session
    import aws_bedrock_token_generator as tokens
    import httpx
    import openai
    from everlink import llm

    for name in (
        "BEDROCK_MANTLE_API_KEY", "BEDROCK_MANTLE_MODEL_ID", "BEDROCK_MANTLE_REASONING",
        "AWS_REGION", "AWS_DEFAULT_REGION", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN", "AWS_PROFILE", "AWS_DEFAULT_PROFILE", "OPENAI_API_KEY",
        "AWS_CONTAINER_CREDENTIALS_RELATIVE_URI", "AWS_CONTAINER_CREDENTIALS_FULL_URI",
        "AWS_WEB_IDENTITY_TOKEN_FILE", "AWS_ROLE_ARN",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("AWS_EC2_METADATA_DISABLED", "true")
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", str(tmp_path / "absent-credentials"))
    monkeypatch.setenv("AWS_CONFIG_FILE", str(tmp_path / "absent-config"))

    def forbidden(*args, **kwargs):
        pytest.fail("离线认证回归禁止真实 AWS chain 或网络")

    monkeypatch.setattr(boto3.session.Session, "get_credentials", forbidden)
    monkeypatch.setattr(botocore.session.Session, "get_credentials", forbidden)
    monkeypatch.setattr(boto3, "client", forbidden)
    monkeypatch.setattr(boto3.session.Session, "client", forbidden)
    monkeypatch.setattr(httpx.Client, "send", forbidden)
    monkeypatch.setattr(httpx.AsyncClient, "send", forbidden)

    # Windows asyncio 的 socketpair 使用回环连接；只放行内部通信，HTTP 仍禁止。
    def local_only(original):
        def guarded(sock, address):
            if not isinstance(address, tuple) or address[0] not in {"127.0.0.1", "::1"}:
                forbidden()
            return original(sock, address)
        return guarded

    monkeypatch.setattr(socket.socket, "connect", local_only(socket.socket.connect))
    monkeypatch.setattr(socket.socket, "connect_ex", local_only(socket.socket.connect_ex))
    monkeypatch.setattr(socket, "create_connection", forbidden)
    provider = Mock(side_effect=["synthetic-bearer-1", "synthetic-bearer-2"])
    monkeypatch.setattr(tokens, "provide_token", provider)
    client = Mock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.chat.completions.create = AsyncMock(return_value=SimpleNamespace(choices=[]))
    factory = Mock(return_value=client)
    monkeypatch.setattr(openai, "AsyncOpenAI", factory)
    return SimpleNamespace(llm=llm, provider=provider, factory=factory, client=client)


class TestMantleAuthContract:
    def test_static_key_wins_without_iam_fallback(self, mantle_io, monkeypatch):
        monkeypatch.setenv("BEDROCK_MANTLE_API_KEY", "  synthetic-static-key  ")
        mantle_io.provider.side_effect = AssertionError("不得进入 IAM provider")
        model = mantle_io.llm.get_mantle_model()
        model.update_config(stream=False)
        for _ in range(2):
            _stream_events(model, USER_MSG)
        assert mantle_io.provider.call_count == 0
        assert mantle_io.factory.call_count == 2
        for call in mantle_io.factory.call_args_list:
            assert call.kwargs["api_key"] == "synthetic-static-key"
            assert call.kwargs["base_url"] == "https://bedrock-mantle.us-east-1.api.aws/v1"

    @pytest.mark.parametrize("value", [None, "", " \t\n "])
    def test_absent_or_blank_key_uses_iam_at_request_time(self, mantle_io, monkeypatch, value):
        if value is not None:
            monkeypatch.setenv("BEDROCK_MANTLE_API_KEY", value)
        model = mantle_io.llm.get_mantle_model()
        mantle_io.provider.assert_not_called()
        mantle_io.factory.assert_not_called()
        model.update_config(stream=False)
        _stream_events(model, USER_MSG)
        mantle_io.provider.assert_called_once_with(region="us-east-1")
        assert mantle_io.factory.call_args.kwargs["api_key"] == "synthetic-bearer-1"

    @pytest.mark.parametrize("static", [False, True])
    @pytest.mark.parametrize("level", ["default", "env", "argument"])
    def test_model_region_priority(self, mantle_io, monkeypatch, static, level):
        if static:
            monkeypatch.setenv("BEDROCK_MANTLE_API_KEY", "synthetic-static-key")
        kwargs = {}
        expected_model = "qwen.qwen3-next-80b-a3b-instruct"
        expected_region = "us-east-1"
        if level != "default":
            monkeypatch.setenv("BEDROCK_MANTLE_MODEL_ID", "env.synthetic-model")
            monkeypatch.setenv("AWS_REGION", "us-west-2")
            expected_model, expected_region = "env.synthetic-model", "us-west-2"
        if level == "argument":
            kwargs = {"model_id": "argument.synthetic-model", "region_name": "eu-west-1"}
            expected_model, expected_region = "argument.synthetic-model", "eu-west-1"
        model = mantle_io.llm.get_mantle_model(**kwargs)
        assert model.get_config()["model_id"] == expected_model
        model.update_config(stream=False)
        _stream_events(model, USER_MSG)
        assert mantle_io.factory.call_args.kwargs["base_url"] == (
            f"https://bedrock-mantle.{expected_region}.api.aws/v1")
        if not static:
            mantle_io.provider.assert_called_once_with(region=expected_region)

    @pytest.mark.parametrize("static", [False, True])
    def test_construction_never_mints_or_creates_http_client(self, mantle_io, monkeypatch, static):
        if static:
            monkeypatch.setenv("BEDROCK_MANTLE_API_KEY", "synthetic-static-key")
        mantle_io.llm.get_mantle_model()
        mantle_io.provider.assert_not_called()
        mantle_io.factory.assert_not_called()

    def test_consecutive_requests_mint_separately_without_cached_bearer(self, mantle_io):
        model = mantle_io.llm.get_mantle_model()
        model.update_config(stream=False)
        for _ in range(2):
            _stream_events(model, USER_MSG)
        assert mantle_io.provider.call_count == 2
        assert [c.kwargs["api_key"] for c in mantle_io.factory.call_args_list] == [
            "synthetic-bearer-1", "synthetic-bearer-2"]
        assert mantle_io.client.chat.completions.create.await_count == 2
        assert mantle_io.client.__aexit__.await_count == 2

    def test_provider_failure_does_not_reuse_previous_bearer(self, mantle_io):
        mantle_io.provider.side_effect = ["synthetic-bearer-1", RuntimeError("session expired")]
        model = mantle_io.llm.get_mantle_model()
        model.update_config(stream=False)
        _stream_events(model, USER_MSG)
        with pytest.raises(RuntimeError):
            _stream_events(model, USER_MSG)
        assert mantle_io.provider.call_count == 2
        assert mantle_io.factory.call_count == 1
        assert mantle_io.client.chat.completions.create.await_count == 1

    def test_static_http_failure_does_not_silently_switch_to_iam(self, mantle_io, monkeypatch):
        import httpx
        import openai

        monkeypatch.setenv("BEDROCK_MANTLE_API_KEY", "synthetic-static-key")
        response = httpx.Response(401, request=httpx.Request("POST", "https://example.invalid/v1"))
        mantle_io.client.chat.completions.create.side_effect = openai.AuthenticationError(
            "synthetic failure", response=response, body=None)
        model = mantle_io.llm.get_mantle_model()
        model.update_config(stream=False)
        with pytest.raises(openai.AuthenticationError):
            _stream_events(model, USER_MSG)
        mantle_io.provider.assert_not_called()
        assert mantle_io.client.chat.completions.create.await_count == 1


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
