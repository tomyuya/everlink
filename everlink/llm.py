"""Model-provider layer for EverLink's Strands agents (spec §6).

Two paths, one interface:

  * ``get_model()`` -> a real ``BedrockModel`` (Claude via Amazon Bedrock).
    This is the submission path; it needs AWS credentials. When they are absent
    it raises ``BedrockNotConfigured`` with actionable guidance instead of
    failing deep inside the SDK.

  * ``StubModel`` -> an offline, deterministic ``strands.models.Model`` that
    yields scripted text via ``stream()`` and a fixed instance via
    ``structured_output()``. It lets the whole agent orchestration (hooks,
    steering, schema wiring, decision queue) be exercised and unit-tested
    WITHOUT AWS credentials or network.

StubModel is NOT a substitute for real LLM judgment: detection accuracy and
proposal quality are verified by ``scripts/verify_bedrock.py`` + Strands Evals
once credentials are present (spec §8). It exists so development and CI are not
blocked on a cloud dependency.
"""
from __future__ import annotations

import os
from collections.abc import AsyncGenerator, Callable
from typing import Any, TypeVar

from pydantic import BaseModel
from strands.models.model import Model
from strands.types.streaming import StreamEvent
from strands.types.tools import ToolChoice, ToolSpec

T = TypeVar("T", bound=BaseModel)

# spec §6 locks the submission build to Bedrock Claude. Overridable via env so
# the README can demonstrate Strands' "any model" provider-swap selling point.
DEFAULT_MODEL_ID = "us.anthropic.claude-sonnet-4-5"
DEFAULT_REGION = "us-east-1"


class BedrockNotConfigured(RuntimeError):
    """Raised when a real Bedrock model is requested but AWS creds are missing."""


def aws_credentials_available() -> bool:
    """True if boto3 can resolve any credentials (env / shared file / SSO / role).

    Offline check only: does not call any AWS API, so it cannot hang on SSO.
    """
    try:
        import boto3

        return boto3.session.Session().get_credentials() is not None
    except Exception:
        return False


def get_model(model_id: str | None = None, region_name: str | None = None) -> Model:
    """Return a real ``BedrockModel`` (the submission path).

    Raises:
        BedrockNotConfigured: if no AWS credentials can be resolved. The message
            tells the operator exactly how to fix it (and points at StubModel for
            offline work).
    """
    if not aws_credentials_available():
        raise BedrockNotConfigured(
            "No AWS credentials resolved, so BedrockModel cannot authenticate.\n"
            "  - IAM Identity Center: install the AWS CLI, then `aws configure sso`\n"
            "  - or export AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY (+ AWS_REGION)\n"
            "  - Hackathon: claim your Builder ID + $200 credits (see README), and\n"
            "    grant Bedrock model access for the model_id in the console.\n"
            "Then run: python scripts/verify_bedrock.py\n"
            "For offline dev/tests, use everlink.llm.StubModel instead."
        )
    from strands.models import BedrockModel

    mid = model_id or os.environ.get("BEDROCK_MODEL_ID") or DEFAULT_MODEL_ID
    region = region_name or os.environ.get("AWS_REGION") or DEFAULT_REGION
    return BedrockModel(model_id=mid, region_name=region)


class StubModel(Model):
    """Offline deterministic Model for tests / --dry-run without AWS credentials.

    Args:
        text: text returned by ``stream()`` (a fixed assistant message).
        structured: a dict, or a callable ``(prompt) -> dict``, validated into the
            requested ``output_model`` by ``structured_output()``.
        **config: stored in the model config (e.g. model_id override).
    """

    def __init__(
        self,
        *,
        text: str = "stub-ok",
        structured: dict[str, Any] | Callable[[Any], dict[str, Any]] | None = None,
        **config: Any,
    ) -> None:
        self.config: dict[str, Any] = {"model_id": "everlink-stub", **config}
        self._text = text
        self._structured = structured if structured is not None else {}
        self.calls = 0

    # -- config -------------------------------------------------------------
    def update_config(self, **model_config: Any) -> None:
        self.config.update(model_config)

    def get_config(self) -> Any:
        return self.config

    # -- streaming ----------------------------------------------------------
    async def stream(
        self,
        messages: Any,
        tool_specs: list[ToolSpec] | None = None,
        system_prompt: str | None = None,
        *,
        tool_choice: ToolChoice | None = None,
        **kwargs: Any,
    ) -> AsyncGenerator[StreamEvent, None]:
        self.calls += 1
        yield {"messageStart": {"role": "assistant"}}
        yield {"contentBlockStart": {"start": {}}}
        yield {"contentBlockDelta": {"delta": {"text": self._text}}}
        yield {"contentBlockStop": {}}
        yield {"messageStop": {"stopReason": "end_turn"}}
        yield {
            "metadata": {
                "usage": {"inputTokens": 0, "outputTokens": 0, "totalTokens": 0},
                "metrics": {"latencyMs": 0},
            }
        }

    # -- structured output --------------------------------------------------
    async def structured_output(
        self,
        output_model: type[T],
        prompt: Any,
        system_prompt: str | None = None,
        **kwargs: Any,
    ) -> AsyncGenerator[dict[str, T | Any], None]:
        data = self._structured(prompt) if callable(self._structured) else self._structured
        yield {"output": output_model.model_validate(data)}
