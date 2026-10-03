"""Mantle 验证入口的离线契约测试；入口缺失只导致单项失败，不阻塞收集。

后续实现接口：main(argv=None) -> int、纯 build_parser()；互斥 --identity-only/--live。
默认完全离线；--max-model-calls 默认 6、--timeout-seconds 默认 60，仅允许降低。
两条合成输入共用同一 Judge；预算覆盖其内部模型循环，超时覆盖整个 live 操作。
本文件即使传 --live 也只使用内存替身，绝不构成真实模型或生产验收。
"""
import asyncio
import importlib.util
import math
import os
import socket
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
SCRIPT = ROOT / "scripts" / "verify_mantle.py"


@pytest.fixture
def smoke_io(monkeypatch, tmp_path):
    import boto3
    import botocore.session
    import dotenv
    import httpx
    import psycopg
    import aws_bedrock_token_generator as tokens

    # 在延迟加载被测入口前切断所有凭据、.env 和副作用入口。
    for name in tuple(os.environ):
        if name.startswith(("AWS_", "BEDROCK_", "EVERLINK_", "OTEL_", "RESEND_", "TELEGRAM_")) or name in (
            "AETHELGEM_DATABASE_URL", "SANDCART_DATABASE_URL", "HOTDEALS_DATABASE_URL", "OPENAI_API_KEY",
        ):
            monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("PYTHON_DOTENV_DISABLED", "1")
    monkeypatch.setenv("AWS_EC2_METADATA_DISABLED", "true")
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", str(tmp_path / "absent-credentials"))
    monkeypatch.setenv("AWS_CONFIG_FILE", str(tmp_path / "absent-config"))
    monkeypatch.setattr(dotenv, "load_dotenv", lambda *a, **k: False)

    def forbidden(*args, **kwargs):
        pytest.fail("Mantle 验证回归禁止真实网络、AWS chain、DB、Writer 或通知")

    monkeypatch.setattr(boto3.session.Session, "get_credentials", forbidden)
    monkeypatch.setattr(botocore.session.Session, "get_credentials", forbidden)
    identity = Mock()
    identity.get_caller_identity.return_value = {
        "Account": "000000000000", "Arn": "arn:aws:iam::000000000000:user/synthetic", "UserId": "synthetic",
    }
    aws_client = Mock(side_effect=forbidden)
    monkeypatch.setattr(boto3, "client", aws_client)
    monkeypatch.setattr(boto3.session.Session, "client", aws_client)
    provider = Mock(side_effect=forbidden)
    monkeypatch.setattr(tokens, "provide_token", provider)
    monkeypatch.setattr(httpx.Client, "send", forbidden)
    monkeypatch.setattr(httpx.AsyncClient, "send", forbidden)
    monkeypatch.setattr(psycopg, "connect", forbidden)
    monkeypatch.setattr(botocore.session.Session, "create_client", forbidden)

    # 保留 Windows asyncio 内部 socketpair；外部连接及所有 HTTP 请求均禁止。
    def local_only(original):
        def guarded(sock, address):
            if not isinstance(address, tuple) or address[0] not in {"127.0.0.1", "::1"}:
                forbidden()
            return original(sock, address)
        return guarded

    monkeypatch.setattr(socket.socket, "connect", local_only(socket.socket.connect))
    monkeypatch.setattr(socket.socket, "connect_ex", local_only(socket.socket.connect_ex))
    monkeypatch.setattr(socket, "create_connection", forbidden)

    from everlink import agents, db, llm, notify, steering, writer
    from strands.hooks import AfterInvocationEvent, BeforeInvocationEvent

    for name in ("connect", "ensure_schema", "insert_audit", "everlink_dsn"):
        monkeypatch.setattr(db, name, forbidden)
    for name in ("build_writer", "judge_slot", "run_scan"):
        monkeypatch.setattr(agents, name, forbidden)
    for name in ("apply_fix", "verify_fix", "rollback", "make_writer_handler"):
        monkeypatch.setattr(writer, name, forbidden)
    monkeypatch.setattr(notify, "Notifier", forbidden)
    monkeypatch.setattr(steering, "db_audit_sink", forbidden)

    state = SimpleNamespace(
        model_calls=0, prompts=[], delays=[], repeat_tools=False, invocations=[], results=[],
        models=[], judges=[], audits=[], identity=identity, aws_client=aws_client, provider=provider,
        agents=agents, llm=llm, steering=steering,
    )
    real_factory, real_builder = llm.get_mantle_model, agents.build_judge
    stub = llm.StubModel(structured={
        "action": "ESCALATE_HUMAN", "rationale": "synthetic offline proposal", "risk_level": "high",
    })

    async def stream(messages, *args, **kwargs):
        state.model_calls += 1
        if state.model_calls > 8:
            pytest.fail("模型调用预算未生效；测试侧停止无界循环")
        user_messages = [m for m in messages if m["role"] == "user"]
        if user_messages:
            state.prompts.append(str(user_messages[-1]["content"]))
        if state.delays:
            await asyncio.sleep(state.delays.pop(0))
        if state.repeat_tools:
            # 强制内部多轮循环，证明限制的是底层模型调用而非只数两次 Agent 调用。
            yield {"messageStart": {"role": "assistant"}}
            yield {"contentBlockStart": {"start": {"toolUse": {
                "toolUseId": f"synthetic-{state.model_calls}", "name": "find_alternatives"}}, "index": 0}}
            yield {"contentBlockDelta": {"delta": {"toolUse": {
                "input": '{"url":"https://example.invalid/item"}'}}, "index": 0}}
            yield {"contentBlockStop": {"index": 0}}
            yield {"messageStop": {"stopReason": "tool_use"}}
            return
        async for event in stub.stream(messages, *args, **kwargs):
            yield event

    def factory(*args, **kwargs):
        # 保留真实 get_mantle_model 构造与模型类型，仅替换传输，不替换 Strands Agent。
        model = real_factory(*args, **kwargs)
        monkeypatch.setattr(model, "stream", stream)
        state.models.append(model)
        return model

    def builder(model, *args, **kwargs):
        judge = real_builder(model, *args, **kwargs)
        judge.hooks.add_callback(BeforeInvocationEvent,
                                 lambda event: state.invocations.append((event.agent, dict(event.invocation_state))))
        judge.hooks.add_callback(AfterInvocationEvent,
                                 lambda event: state.results.append(event.result))
        state.judges.append(judge)
        state.audits.append(kwargs.get("audit_sink"))
        return judge

    state.factory = Mock(side_effect=factory)
    state.builder = Mock(side_effect=builder)
    monkeypatch.setattr(llm, "get_mantle_model", state.factory)
    monkeypatch.setattr(agents, "build_judge", state.builder)
    return state


def _load(monkeypatch):
    assert SCRIPT.is_file(), "待实现 scripts/verify_mantle.py；此失败不应成为 collection error"
    spec = importlib.util.spec_from_file_location("everlink_verify_mantle_contract", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    assert callable(getattr(module, "main", None)), "入口须提供 main(argv=None) -> int"
    return module


def _code(module, argv):
    try:
        result = module.main(argv)
    except SystemExit as exc:
        result = exc.code
    assert isinstance(result, int) and not isinstance(result, bool)
    return result


def test_default_is_offline_without_model_identity_or_bearer(smoke_io, monkeypatch):
    module = _load(monkeypatch)
    assert _code(module, []) == 0
    smoke_io.factory.assert_not_called()
    smoke_io.builder.assert_not_called()
    smoke_io.aws_client.assert_not_called()
    smoke_io.provider.assert_not_called()


def test_identity_only_uses_only_mocked_sts(smoke_io, monkeypatch):
    def client(service_name, *args, **kwargs):
        assert service_name == "sts"
        return smoke_io.identity

    smoke_io.aws_client.side_effect = client
    module = _load(monkeypatch)
    assert _code(module, ["--identity-only"]) == 0
    smoke_io.identity.get_caller_identity.assert_called_once_with()
    smoke_io.factory.assert_not_called()
    smoke_io.builder.assert_not_called()
    smoke_io.provider.assert_not_called()


def test_identity_failure_is_nonzero_and_redacted(smoke_io, monkeypatch, capsys):
    smoke_io.aws_client.side_effect = None
    smoke_io.aws_client.return_value = smoke_io.identity
    smoke_io.identity.get_caller_identity.side_effect = RuntimeError("synthetic-identity-secret")
    module = _load(monkeypatch)
    assert _code(module, ["--identity-only"]) != 0
    captured = capsys.readouterr()
    assert "synthetic-identity-secret" not in captured.out + captured.err
    smoke_io.factory.assert_not_called()


def test_live_uses_real_factory_and_one_enforced_agent_for_two_inputs(smoke_io, monkeypatch):
    module = _load(monkeypatch)
    assert _code(module, ["--live"]) == 0
    smoke_io.factory.assert_called_once()
    smoke_io.builder.assert_called_once()
    call = smoke_io.builder.call_args
    assert (call.args[0] if call.args else call.kwargs["model"]) is smoke_io.models[0]
    assert call.kwargs["enforce"] is True
    assert call.kwargs.get("hooks") is None
    assert smoke_io.judges[0].system_prompt == smoke_io.agents.JUDGE_SYSTEM_PROMPT
    assert len(smoke_io.judges) == 1 and smoke_io.model_calls == 2
    assert len(set(smoke_io.prompts)) == 2
    assert len(smoke_io.invocations) == 2
    assert all(agent is smoke_io.judges[0] for agent, _ in smoke_io.invocations)
    from everlink.model import LinkSlot, Proposal
    from urllib.parse import urlparse

    slots = [LinkSlot.model_validate(context["slot"]) for _, context in smoke_io.invocations]
    assert slots[0].id != slots[1].id
    assert all((urlparse(slot.url).hostname or "").endswith(".invalid") or
               urlparse(slot.url).hostname in {"example.com", "example.org", "example.net"} for slot in slots)
    assert all(context.get("verdict") for _, context in smoke_io.invocations)
    assert len(smoke_io.results) == 2
    assert all(isinstance(result.structured_output, Proposal) for result in smoke_io.results)
    assert all(isinstance(audit, smoke_io.steering.AuditCollector) for audit in smoke_io.audits)
    smoke_io.aws_client.assert_not_called()
    smoke_io.provider.assert_not_called()


@pytest.mark.parametrize("raw", [None, "plain text", {
    "action": "ESCALATE_HUMAN", "rationale": "synthetic", "risk_level": "high",
}])
def test_live_rejects_missing_or_non_proposal_raw_structured_output(smoke_io, monkeypatch, raw):
    # 不接受 judge_slot 的兜底，也不把一个可解析 dict 或普通文本当作原始 Proposal。
    result = SimpleNamespace(structured_output=raw)
    fake_judge = Mock(return_value=result)
    fake_judge.invoke_async = AsyncMock(return_value=result)
    smoke_io.builder.side_effect = None
    smoke_io.builder.return_value = fake_judge
    module = _load(monkeypatch)
    assert _code(module, ["--live"]) != 0
    assert fake_judge.call_count + fake_judge.invoke_async.await_count == 1


def test_live_model_failure_is_nonzero_without_secret_output(smoke_io, monkeypatch, capsys):
    smoke_io.factory.side_effect = RuntimeError("synthetic-model-secret")
    module = _load(monkeypatch)
    assert _code(module, ["--live"]) != 0
    captured = capsys.readouterr()
    assert "synthetic-model-secret" not in captured.out + captured.err
    smoke_io.builder.assert_not_called()


def test_call_budget_includes_internal_agent_model_turns(smoke_io, monkeypatch):
    smoke_io.repeat_tools = True
    module = _load(monkeypatch)
    assert _code(module, ["--live", "--max-model-calls", "3"]) != 0
    assert smoke_io.model_calls == 3


def test_one_call_budget_cannot_pass_two_structured_inputs(smoke_io, monkeypatch):
    module = _load(monkeypatch)
    assert _code(module, ["--live", "--max-model-calls", "1"]) != 0
    assert smoke_io.model_calls == 1


def test_total_timeout_cancels_a_slow_model_request(smoke_io, monkeypatch):
    smoke_io.delays = [1.0]
    module = _load(monkeypatch)
    start = time.monotonic()
    assert _code(module, ["--live", "--timeout-seconds", "0.05"]) != 0
    assert time.monotonic() - start < 0.75
    assert smoke_io.model_calls == 1


def test_total_deadline_is_shared_across_both_inputs(smoke_io, monkeypatch):
    smoke_io.delays = [0.5, 0.5]
    module = _load(monkeypatch)
    assert _code(module, ["--live", "--timeout-seconds", "0.85"]) != 0
    assert smoke_io.model_calls == 2


def test_parser_defaults_are_bounded_and_have_no_side_effects(smoke_io, monkeypatch):
    module = _load(monkeypatch)
    args = module.build_parser().parse_args([])
    assert args.max_model_calls == 6
    assert args.timeout_seconds == 60 and math.isfinite(args.timeout_seconds)
    assert not args.live and not args.identity_only
    smoke_io.factory.assert_not_called()
    smoke_io.builder.assert_not_called()
    smoke_io.aws_client.assert_not_called()
    smoke_io.provider.assert_not_called()


def test_default_model_budget_cannot_expand_past_six(smoke_io, monkeypatch):
    smoke_io.repeat_tools = True
    module = _load(monkeypatch)
    assert _code(module, ["--live"]) != 0
    assert smoke_io.model_calls == 6


@pytest.mark.parametrize("argv", [
    ["--identity-only", "--live"],
    ["--live", "--max-model-calls", "0"],
    ["--live", "--max-model-calls", "7"],
    ["--live", "--timeout-seconds", "0"],
    ["--live", "--timeout-seconds", "-1"],
    ["--live", "--timeout-seconds", "61"],
    ["--live", "--timeout-seconds", "nan"],
    ["--live", "--timeout-seconds", "inf"],
])
def test_unsafe_or_conflicting_arguments_fail_before_model_use(smoke_io, monkeypatch, argv):
    module = _load(monkeypatch)
    assert _code(module, argv) != 0
    smoke_io.factory.assert_not_called()
    smoke_io.builder.assert_not_called()
    smoke_io.aws_client.assert_not_called()
    smoke_io.provider.assert_not_called()
