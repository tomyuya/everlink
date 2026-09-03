"""Full-chain nightly cron entrypoint (spec §3 core loop / §9 Phase F / §12-5).

This is the ONE command a scheduler runs to reproduce EverLink's autonomous loop
with no hidden logic — it drives the SAME ``python -m everlink`` subcommands a human
would, in order:

  1. scan   (per site)  Scanner -> detect -> Judge -> enqueue decision cards [pending]
  2. notify             push the freshly-surfaced cards to the operator (Resend/Telegram)
  3. worker --once      drain any cards the human already APPROVED (snapshot->apply->verify)
  4. report             on --weekly-day (default Monday) the SAME cron folds in the weekly
                        digest — the board /report numbers — so ONE service drives the loop

The orchestration is deliberately thin: ``plan_steps`` is a PURE function that turns
arguments into the ordered argv list (unit-tested offline in tests/test_nightly.py),
and ``run_steps`` just feeds each argv to an injectable runner (default: everlink.cli.main).
Nothing here re-implements detection, judging, writing, or notifying — so a cron run is
byte-for-byte the same code path as the CLI, and the audit trail is identical.

HONEST DEGRADATION (nothing is faked):
  * ``--judge bedrock`` (the default) needs AWS/Bedrock creds; if they are missing the
    scan step exits 2 and this script reports the degradation and CONTINUES (detection
    still ran). ``--judge none`` needs no creds and produces a real dead-link scan with
    zero proposals; ``--judge stub`` is the offline fixture judge.
  * ``--dry-run`` is the safe manual trigger (§12-5): scan writes nothing, notify sends
    nothing, and the worker step is SKIPPED (it writes; its own safe no-op is
    ``everlink worker --handler null``). Use it to prove the chain is wired offline.
  * Every write still goes only to EverLink's OWN guarded store (db._assert_writable);
    a source-site or forbidden host is refused exactly as in the CLI.

Usage:
    python scripts/nightly.py                          # real nightly (bedrock judge)
    python scripts/nightly.py --dry-run --judge none   # offline smoke, no writes/sends
    python scripts/nightly.py --sites aethelgem --weekly --days 7
"""
from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from everlink import cli  # noqa: E402

DEFAULT_SITES = ("aethelgem", "sandcart", "hotdeals")   # scan all three read-only (spec §4.1)
DEFAULT_JUDGE = "bedrock"                                # the real nightly uses the LLM judge
DEFAULT_WEEKLY_DAY = "mon"                               # fold the weekly digest in on Mondays


@dataclass
class Step:
    """One planned cron step: a label + the argv to run (None => honestly skipped)."""
    label: str
    argv: list[str] | None
    note: str = ""


@dataclass
class StepResult:
    label: str
    code: int | None          # None => the step was skipped, not run
    note: str = ""


@dataclass
class Plan:
    steps: list[Step] = field(default_factory=list)

    @property
    def executed(self) -> list[Step]:
        return [s for s in self.steps if s.argv is not None]

    @property
    def skipped(self) -> list[Step]:
        return [s for s in self.steps if s.argv is None]


def _sites(args: argparse.Namespace) -> list[str]:
    """Resolve the scan targets: --sites wins, then env, then the three first-party sites."""
    raw = args.sites or os.environ.get("EVERLINK_NIGHTLY_SITES") or ",".join(DEFAULT_SITES)
    return [s.strip() for s in raw.split(",") if s.strip()]


def _judge(args: argparse.Namespace) -> str:
    """Resolve the Judge backend: --judge wins, then env, then the real Bedrock judge."""
    return args.judge or os.environ.get("EVERLINK_JUDGE") or DEFAULT_JUDGE


def plan_steps(args: argparse.Namespace, today: date | None = None) -> Plan:
    """PURE: turn arguments into the ordered cron steps (no I/O, no side effects).

    Kept free of side effects so tests/test_nightly.py can assert the exact argv the
    cron will run — including the honest skips (worker under --dry-run) and the
    day-gated weekly report — offline. ``today`` is injectable for deterministic tests.
    """
    plan = Plan()
    judge = _judge(args)
    today = today or date.today()

    # 1. scan every site (Scanner -> detect -> Judge -> enqueue cards). Read-only on the
    #    source sites; the only writes (unless --dry-run) go to EverLink's own store.
    for site in _sites(args):
        argv = ["scan", "--site", site, "--judge", judge, "--limit", str(args.limit)]
        if args.no_l2:
            argv.append("--no-l2")
        if args.dry_run:
            argv.append("--dry-run")          # scan --dry-run writes nothing to any DB
        plan.steps.append(Step(f"scan:{site}", argv))

    # 2. surface the queue to the operator (spec §7 push-to-surface).
    if args.skip_notify:
        plan.steps.append(Step("notify", None, "skipped: --skip-notify"))
    else:
        argv = ["notify"]
        if args.brief:
            argv.append("--brief")            # morning digest instead of raw cards
        if args.channel != "all":
            argv += ["--channel", args.channel]
        if args.dry_run:
            argv.append("--dry-run")          # compose + print; send NOTHING
        plan.steps.append(Step("notify", argv))

    # 3. drain whatever the human already approved (async-Interrupt execution track).
    if args.skip_worker:
        plan.steps.append(Step("worker", None, "skipped: --skip-worker"))
    elif args.dry_run:
        # The worker WRITES (snapshot->apply->verify); there is no worker --dry-run, so we
        # honestly skip it rather than mutate anything during a dry-run smoke test.
        plan.steps.append(Step("worker", None,
                               "skipped under --dry-run (it writes; safe no-op = "
                               "`everlink worker --handler null`)"))
    else:
        argv = ["worker", "--once", "--handler", args.handler]
        if args.no_l2:
            argv.append("--no-l2")
        plan.steps.append(Step("worker", argv))

    # 4. weekly digest — folded into the SAME nightly cron on the configured weekday, so a
    #    single Railway service + one cronSchedule drives the whole autonomous loop (spec §3)
    #    with no second service to keep in sync. Force any day with --weekly.
    weekly_day = (args.weekly_day or os.environ.get("EVERLINK_WEEKLY_DAY")
                  or DEFAULT_WEEKLY_DAY).strip().lower()[:3]
    if args.weekly or today.strftime("%a").lower() == weekly_day:
        argv = ["report", "--days", str(args.days)]
        if args.channel != "all":
            argv += ["--channel", args.channel]
        if args.dry_run:
            argv.append("--dry-run")
        plan.steps.append(Step("report", argv))

    return plan


def run_steps(plan: Plan, runner=cli.main) -> list[StepResult]:
    """Execute each planned step via ``runner`` (default: the real CLI main).

    The runner is injectable so tests can record the argv without touching a DB, AWS,
    or the network. A step that raises is captured as code -1 (the cron keeps going and
    reports it) so one bad site never silently aborts the whole night.
    """
    results: list[StepResult] = []
    for step in plan.steps:
        if step.argv is None:
            results.append(StepResult(step.label, None, step.note))
            continue
        try:
            code = runner(step.argv)
        except SystemExit as e:              # argparse exits via SystemExit
            code = int(e.code or 0)
        except Exception as e:  # noqa: BLE001 - keep the chain going, report honestly
            code = -1
            step.note = f"{type(e).__name__}: {e}"
        results.append(StepResult(step.label, code, step.note))
    return results


def _print_plan(plan: Plan, args: argparse.Namespace) -> None:
    mode = "DRY-RUN (no DB writes, no sends)" if args.dry_run else "LIVE"
    print(f"[nightly] {mode}  judge={_judge(args)}  sites={','.join(_sites(args))}")
    for i, step in enumerate(plan.steps, 1):
        tail = f"  -> {step.note}" if step.argv is None else f"  $ everlink {' '.join(step.argv)}"
        print(f"  {i}. {step.label}{tail}")


def _print_summary(results: list[StepResult]) -> bool:
    """Print an honest per-step summary; return True iff every executed step returned 0."""
    print("\n[nightly] summary")
    ok = True
    for r in results:
        if r.code is None:
            print(f"  [skip] {r.label:16s} {r.note}")
        else:
            flag = "ok" if r.code == 0 else ("degraded" if r.code == 2 else "FAIL")
            if r.code != 0:
                ok = False
            extra = f"  ({r.note})" if r.note else ""
            print(f"  [{flag:8s}] {r.label:16s} exit={r.code}{extra}")
    return ok


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="nightly", description="EverLink full-chain nightly cron (scan -> notify -> worker).")
    ap.add_argument("--sites", default="",
                    help="comma-separated scan targets (default: env EVERLINK_NIGHTLY_SITES "
                         "or aethelgem,sandcart,hotdeals)")
    ap.add_argument("--judge", choices=["", "none", "stub", "bedrock"], default="",
                    help="Judge backend (default: env EVERLINK_JUDGE or bedrock). "
                         "none=detection only, no creds; stub=offline fixture; bedrock=real LLM")
    ap.add_argument("--limit", type=int, default=25, help="max slots per site (default 25)")
    ap.add_argument("--no-l2", action="store_true", help="L1 only (skip the selective L2 fetch)")
    ap.add_argument("--channel", choices=["all", "email", "telegram"], default="all",
                    help="restrict notify/report to one channel (default: every configured one)")
    ap.add_argument("--brief", action="store_true",
                    help="notify step sends the morning digest instead of the raw cards")
    ap.add_argument("--handler", choices=["writer", "null"], default="writer",
                    help="worker handler (default writer = real snapshot->apply->verify)")
    ap.add_argument("--weekly", action="store_true",
                    help="force the weekly report step now (it is otherwise folded in "
                         "automatically on --weekly-day)")
    ap.add_argument("--weekly-day", default="",
                    help="3-letter weekday the weekly report auto-runs on (default: env "
                         "EVERLINK_WEEKLY_DAY or 'mon')")
    ap.add_argument("--days", type=int, default=7, help="weekly report window (default 7)")
    ap.add_argument("--skip-notify", action="store_true", help="skip the notify step")
    ap.add_argument("--skip-worker", action="store_true", help="skip the worker step")
    ap.add_argument("--dry-run", action="store_true",
                    help="safe manual trigger (§12-5): scan writes nothing, notify sends "
                         "nothing, worker is skipped. Proves the chain is wired, mutates nothing.")
    return ap


def main(argv: list[str] | None = None) -> int:
    # The plan/summary and the CLI help use '§' + em-dash; force UTF-8 so a Windows
    # console (cp1252/cp932) prints them without UnicodeEncodeError (mirrors cli.main).
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001 - best-effort (redirected/older streams)
            pass
    args = build_parser().parse_args(argv)
    plan = plan_steps(args)
    _print_plan(plan, args)
    results = run_steps(plan)
    ok = _print_summary(results)
    print(f"\n[nightly] {'all executed steps ok' if ok else 'one or more steps did not exit 0'} "
          f"({len(plan.executed)} run, {len(plan.skipped)} skipped).")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
