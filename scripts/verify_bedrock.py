"""One-shot REAL Bedrock connectivity check — run AFTER configuring AWS creds.

This is the single operator step that EverLink cannot do offline. It verifies,
in order: credentials resolve -> model constructs -> a real Claude call succeeds
(i.e. Bedrock model access is granted). Prints actionable diagnostics on failure.

Usage:
    python scripts/verify_bedrock.py
Exit codes: 0 ok · 2 no creds / model init fail · 3 real call failed (access?)
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from everlink import llm  # noqa: E402


def main() -> int:
    print("=" * 64)
    print("EverLink Bedrock connectivity check")
    print("=" * 64)

    if not llm.aws_credentials_available():
        print("\n[abort] No AWS credentials resolved.")
        print("  - IAM Identity Center: install AWS CLI, then `aws configure sso`")
        print("  - or set AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY / AWS_REGION")
        print("  - Hackathon: claim Builder ID + $200 credits (see README)")
        return 2
    print("credentials           : resolved")

    try:
        model = llm.get_model()
        mid = model.get_config().get("model_id")
        print("model_id              :", mid)
    except llm.BedrockNotConfigured as e:
        print("\n[abort]", e)
        return 2
    except Exception as e:  # noqa: BLE001
        print("\n[abort] model init failed:", type(e).__name__, str(e)[:300])
        return 2

    try:
        from strands import Agent
    except ImportError as e:
        print("\n[abort] strands not installed:", e)
        return 2

    agent = Agent(
        model=model,
        system_prompt="You are a connectivity probe. Reply with exactly: BEDROCK_OK",
    )
    print("calling Bedrock (real) ...")
    t0 = time.time()
    try:
        resp = agent("Ping. Reply with exactly BEDROCK_OK and nothing else.")
        text = str(resp).strip()
        dt = time.time() - t0
        print(f"real Bedrock call OK  : {dt:.1f}s")
        print("response              :", text[:200])
        print("\nRESULT: PASS — Judge/Evals can now run against real Claude.")
        return 0
    except Exception as e:  # noqa: BLE001
        dt = time.time() - t0
        print(f"\n[fail] real Bedrock call failed after {dt:.1f}s:")
        print("       ", type(e).__name__, str(e)[:300])
        print("  -> In the Bedrock console, request Model access for the model_id above")
        print("     (Anthropic Claude). Access approval can take a few minutes.")
        return 3


if __name__ == "__main__":
    sys.exit(main())
