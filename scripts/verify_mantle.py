"""Mantle verification entry point — offline-safe smoke for the Judge pipeline.

Usage::

    python scripts/verify_mantle.py                  # offline: no I/O, exit 0
    python scripts/verify_mantle.py --identity-only  # STS caller-identity check
    python scripts/verify_mantle.py --live           # full judge pipeline (2 synthetic inputs)

Design contract (tested by tests/test_verify_mantle.py):
  * ``main(argv=None) -> int``; ``build_parser()`` is pure (no side effects).
  * ``--identity-only`` and ``--live`` are mutually exclusive.
  * ``--max-model-calls`` default 6, valid 1..6.
  * ``--timeout-seconds`` default 60, valid 0 < x <= 60, finite only.
  * Default mode is COMPLETELY offline: no model, no AWS, no DB, no network.
  * ``--live`` builds ONE real judge (enforce=True) and runs TWO synthetic inputs
    through it; the raw ``structured_output`` must be a ``Proposal`` instance.
  * Budget covers ALL internal model turns (not just top-level agent calls).
  * Timeout is a shared total deadline across both inputs.
  * Errors are redacted: only ``type(exc).__name__`` reaches stdout/stderr.
"""
from __future__ import annotations

import argparse
import asyncio
import math
import sys
from typing import Optional


# --------------------------------------------------------------------------- #
# Internal exceptions (never leak text to output)
# --------------------------------------------------------------------------- #
class _BudgetExceeded(Exception):
    """Model call budget exhausted."""


class _NotProposal(Exception):
    """structured_output is not a Proposal instance."""


# --------------------------------------------------------------------------- #
# Parser (pure — no imports, no I/O, no side effects)
# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    """Build the CLI parser. Pure function; safe to call in any context."""
    p = argparse.ArgumentParser(
        prog="verify_mantle",
        description="Offline-safe Mantle/Judge pipeline verification.",
    )
    mode = p.add_mutually_exclusive_group()
    mode.add_argument(
        "--identity-only", action="store_true",
        help="Only check AWS STS caller identity; no model or judge.",
    )
    mode.add_argument(
        "--live", action="store_true",
        help="Run the full judge pipeline on two synthetic inputs.",
    )
    p.add_argument(
        "--max-model-calls", type=int, default=6,
        help="Maximum底层 model stream calls (1..6, default 6).",
    )
    p.add_argument(
        "--timeout-seconds", type=float, default=60.0,
        help="Total deadline for --live in seconds (0<x<=60, default 60).",
    )
    return p


def _validate(args: argparse.Namespace) -> Optional[str]:
    """Return an error string if args are unsafe, else None."""
    if not isinstance(args.max_model_calls, int) or not (1 <= args.max_model_calls <= 6):
        return "--max-model-calls must be an integer in 1..6"
    t = args.timeout_seconds
    if not math.isfinite(t) or not (0 < t <= 60):
        return "--timeout-seconds must be finite and in (0, 60]"
    return None


# --------------------------------------------------------------------------- #
# --identity-only
# --------------------------------------------------------------------------- #
def _run_identity() -> int:
    """Check AWS STS caller identity. Redacts all error details."""
    try:
        import boto3
        sts = boto3.client("sts")
        identity = sts.get_caller_identity()
        print(f"[verify_mantle] identity OK: Account={identity.get('Account')} "
              f"Arn={identity.get('Arn')}")
        return 0
    except Exception as exc:
        print(f"[verify_mantle] identity check failed ({type(exc).__name__})",
              file=sys.stderr)
        return 1


# --------------------------------------------------------------------------- #
# --live: synthetic inputs
# --------------------------------------------------------------------------- #
def _synthetic_inputs():
    """Build two deterministic LinkSlot+CheckResult pairs for judge verification.

    URLs use .invalid (RFC 2606) or example.com/org/net (RFC 6761) so no real
    host is ever contacted even if detection were accidentally triggered.
    """
    from everlink.model import CheckResult, LinkSlot

    slots = [
        LinkSlot(
            id="verify-mantle-slot-alpha",
            site="aethelgem",
            article_id="art-verify-001",
            article_title="Verification Article Alpha",
            block_id="blk-alpha",
            block_type="body",
            slot_type="commercial",
            anchor_text="alpha test product",
            url="https://shop.example.invalid/product/alpha",
            surrounding_sentence="The alpha test product is available here.",
        ),
        LinkSlot(
            id="verify-mantle-slot-beta",
            site="aethelgem",
            article_id="art-verify-002",
            article_title="Verification Article Beta",
            block_id="blk-beta",
            block_type="body",
            slot_type="commercial",
            anchor_text="beta test item",
            url="https://store.example.invalid/item/beta",
            surrounding_sentence="A beta test item worth reviewing.",
        ),
    ]
    checks = [
        CheckResult(slot_id="verify-mantle-slot-alpha", l1_status=404,
                    final_verdict="dead"),
        CheckResult(slot_id="verify-mantle-slot-beta", l1_status=403,
                    final_verdict="dead"),
    ]
    return list(zip(slots, checks))


# --------------------------------------------------------------------------- #
# --live: main logic
# --------------------------------------------------------------------------- #
def _run_live(args: argparse.Namespace) -> int:
    """Execute the live judge verification with budget and timeout enforcement."""
    from everlink.agents import _judge_prompt, build_judge
    from everlink.llm import get_mantle_model
    from everlink.model import Proposal
    from everlink.steering import AuditCollector

    # --- 1. Model construction (redacted failure) ---
    try:
        model = get_mantle_model()
    except Exception as exc:
        print(f"[verify_mantle] model init failed ({type(exc).__name__})",
              file=sys.stderr)
        return 1

    # --- 2. Budget wrapper on model.stream ---
    budget: int = args.max_model_calls
    calls = [0]
    budget_hit = [False]
    original_stream = model.stream

    async def _budgeted_stream(*a, **kw):
        calls[0] += 1
        if calls[0] > budget:
            budget_hit[0] = True
            raise _BudgetExceeded("budget")
        async for event in original_stream(*a, **kw):
            yield event

    model.stream = _budgeted_stream

    # --- 3. Build ONE enforced judge ---
    audit = AuditCollector()
    judge = build_judge(model, enforce=True, hooks=None, audit_sink=audit)

    # --- 4. Two synthetic inputs ---
    inputs = _synthetic_inputs()

    # --- 5. Async execution with shared total deadline ---
    async def _execute():
        results = []
        for slot, check in inputs:
            prompt = _judge_prompt(slot, check)
            result = await judge.invoke_async(
                prompt,
                invocation_state={
                    "slot": slot.model_dump(),
                    "verdict": check.final_verdict,
                },
            )
            so = getattr(result, "structured_output", None)
            if not isinstance(so, Proposal):
                raise _NotProposal(
                    f"input {len(results) + 1}: structured_output is "
                    f"{type(so).__name__}, not Proposal"
                )
            results.append(result)
        return results

    async def _timed():
        async with asyncio.timeout(args.timeout_seconds):
            return await _execute()

    try:
        asyncio.run(_timed())
    except (asyncio.TimeoutError, TimeoutError):
        print("[verify_mantle] total timeout exceeded", file=sys.stderr)
        return 1
    except _BudgetExceeded:
        print(f"[verify_mantle] model call budget ({budget}) exceeded",
              file=sys.stderr)
        return 1
    except _NotProposal as exc:
        print(f"[verify_mantle] {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        if budget_hit[0]:
            print(f"[verify_mantle] model call budget ({budget}) exceeded",
                  file=sys.stderr)
            return 1
        print(f"[verify_mantle] live verification failed ({type(exc).__name__})",
              file=sys.stderr)
        return 1

    print(f"[verify_mantle] live verification passed: "
          f"{len(inputs)} Proposal(s) validated, {calls[0]} model call(s)")
    return 0


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #
def main(argv=None) -> int:
    """CLI entry point. Returns exit code (0=pass, non-zero=failure)."""
    parser = build_parser()
    args = parser.parse_args(argv)

    error = _validate(args)
    if error:
        print(f"[verify_mantle] argument error: {error}", file=sys.stderr)
        return 64

    if args.identity_only:
        return _run_identity()
    if args.live:
        return _run_live(args)

    # Default: completely offline, no side effects.
    print("[verify_mantle] offline mode: no model, identity, or bearer requested.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
