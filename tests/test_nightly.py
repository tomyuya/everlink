"""Nightly cron orchestration tests (spec §3 core loop / §9 Phase F / §12-5).

Offline and side-effect-free. ``plan_steps`` is a PURE function, and ``run_steps`` is driven
by an INJECTED fake runner that records argv instead of calling the real CLI — so no database,
no AWS/Bedrock, and no network are touched. What is proven here:

  * the exact argv the cron feeds each ``everlink`` subcommand (scan per site -> notify ->
    worker), including the honest skips (the worker under --dry-run) and the day-gated weekly
    report fold-in
  * site / judge / weekly-day resolution from args AND from the environment
  * ``run_steps`` executes runnable steps via the runner, records skips WITHOUT calling it, and
    captures a raising / SystemExit-ing step as a code without aborting the rest of the chain

HONESTY: these tests prove the ORCHESTRATION wiring only. They never run a real scan, touch a
database, call Bedrock, or send a notification — the live full-chain run is a separate,
explicitly-labelled check (see DEPLOYMENT.md, spec §12-5).
"""
import os
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import nightly  # noqa: E402

WED = date(2026, 9, 2)     # a Wednesday — the weekly report is NOT folded in by default
MON = date(2026, 9, 7)     # a Monday    — the default EVERLINK_WEEKLY_DAY
FRI = date(2026, 9, 4)     # a Friday    — for the custom --weekly-day case


def _ns(*argv):
    """Build the args namespace exactly as nightly.main() would (exercises parser defaults)."""
    return nightly.build_parser().parse_args(list(argv))


def _labels(plan):
    return [s.label for s in plan.steps]


def _step(plan, label):
    for s in plan.steps:
        if s.label == label:
            return s
    raise AssertionError(f"no step labelled {label!r} in {_labels(plan)}")


def _argv(plan, label):
    return _step(plan, label).argv


class _env:
    """Set env vars for a block, restoring the previous state afterwards (no pytest fixture)."""

    def __init__(self, **kv):
        self.kv = kv
        self.old = {}

    def __enter__(self):
        for k, v in self.kv.items():
            self.old[k] = os.environ.get(k)
            os.environ[k] = v
        return self

    def __exit__(self, *exc):
        for k, v in self.old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        return False


# --------------------------------------------------------------------------- #
# plan_steps — the pure argv plan
# --------------------------------------------------------------------------- #
def test_plan_steps_default_nightly_chain():
    plan = nightly.plan_steps(_ns(), today=WED)
    assert _labels(plan) == ["scan:aethelgem", "scan:sandcart", "scan:hotdeals", "notify", "worker"]
    assert _argv(plan, "scan:aethelgem") == [
        "scan", "--site", "aethelgem", "--judge", "mantle", "--limit", "25"]
    assert _argv(plan, "notify") == ["notify"]
    assert _argv(plan, "worker") == ["worker", "--once", "--handler", "writer"]
    assert len(plan.executed) == 5 and not plan.skipped
    assert "report" not in _labels(plan)                 # Wednesday: no weekly fold-in


def test_plan_steps_dry_run_is_read_only_and_skips_worker():
    plan = nightly.plan_steps(_ns("--dry-run", "--judge", "none"), today=WED)
    assert _argv(plan, "scan:aethelgem")[-1] == "--dry-run"
    assert "--dry-run" in _argv(plan, "notify")
    worker = _step(plan, "worker")
    assert worker.argv is None and "dry-run" in worker.note      # honest skip, not a write
    assert len(plan.skipped) == 1


def test_plan_steps_sites_and_judge_from_args():
    plan = nightly.plan_steps(_ns("--sites", "aethelgem", "--judge", "stub", "--limit", "5"), today=WED)
    assert _labels(plan) == ["scan:aethelgem", "notify", "worker"]
    assert _argv(plan, "scan:aethelgem") == [
        "scan", "--site", "aethelgem", "--judge", "stub", "--limit", "5"]


def test_plan_steps_resolves_sites_judge_and_weeklyday_from_env():
    with _env(EVERLINK_NIGHTLY_SITES="hotdeals", EVERLINK_JUDGE="none", EVERLINK_WEEKLY_DAY="wed"):
        plan = nightly.plan_steps(_ns(), today=WED)      # empty args => env wins
    assert _labels(plan) == ["scan:hotdeals", "notify", "worker", "report"]   # wed matches today
    scan = _argv(plan, "scan:hotdeals")
    assert scan[scan.index("--judge") + 1] == "none"


def test_plan_steps_args_override_env():
    with _env(EVERLINK_NIGHTLY_SITES="hotdeals", EVERLINK_JUDGE="none"):
        plan = nightly.plan_steps(_ns("--sites", "sandcart", "--judge", "stub"), today=WED)
    assert _labels(plan) == ["scan:sandcart", "notify", "worker"]
    scan = _argv(plan, "scan:sandcart")
    assert scan[scan.index("--judge") + 1] == "stub"


def test_plan_steps_weekly_report_is_day_gated():
    assert "report" not in _labels(nightly.plan_steps(_ns(), today=WED))
    assert "report" in _labels(nightly.plan_steps(_ns(), today=MON))            # default monday
    assert "report" in _labels(nightly.plan_steps(_ns("--weekly"), today=WED))  # forced any day
    assert "report" in _labels(nightly.plan_steps(_ns("--weekly-day", "fri"), today=FRI))
    assert "report" not in _labels(nightly.plan_steps(_ns("--weekly-day", "fri"), today=MON))


def test_plan_steps_weekly_report_argv():
    plan = nightly.plan_steps(_ns("--days", "14", "--channel", "telegram"), today=MON)
    assert _argv(plan, "report") == ["report", "--days", "14", "--channel", "telegram"]


def test_plan_steps_skip_notify_and_worker():
    plan = nightly.plan_steps(_ns("--skip-notify", "--skip-worker"), today=WED)
    assert _step(plan, "notify").argv is None and "skip-notify" in _step(plan, "notify").note
    assert _step(plan, "worker").argv is None and "skip-worker" in _step(plan, "worker").note
    assert len(plan.executed) == 3                        # only the three scans run


def test_plan_steps_channel_brief_and_no_l2_flow_through():
    plan = nightly.plan_steps(_ns("--channel", "email", "--brief", "--no-l2"), today=WED)
    assert _argv(plan, "notify") == ["notify", "--brief", "--channel", "email"]
    assert "--no-l2" in _argv(plan, "scan:aethelgem")


def test_plan_executed_and_skipped_partition_the_steps():
    plan = nightly.plan_steps(_ns("--dry-run"), today=WED)
    assert all(s.argv is not None for s in plan.executed)
    assert all(s.argv is None for s in plan.skipped)
    assert len(plan.executed) + len(plan.skipped) == len(plan.steps)


# --------------------------------------------------------------------------- #
# run_steps — execution via an injected runner (never the real CLI)
# --------------------------------------------------------------------------- #
def test_run_steps_executes_each_argv_via_the_runner():
    calls = []

    def fake(argv):
        calls.append(argv)
        return 0

    plan = nightly.plan_steps(_ns("--sites", "aethelgem"), today=WED)
    results = nightly.run_steps(plan, runner=fake)
    assert [r.code for r in results] == [0, 0, 0]         # scan, notify, worker
    assert calls == [_argv(plan, "scan:aethelgem"), ["notify"],
                     ["worker", "--once", "--handler", "writer"]]


def test_run_steps_records_skips_without_calling_the_runner():
    calls = []

    def fake(argv):
        calls.append(argv)
        return 0

    plan = nightly.plan_steps(_ns("--sites", "aethelgem", "--dry-run"), today=WED)
    results = nightly.run_steps(plan, runner=fake)
    worker_res = [r for r in results if r.label == "worker"][0]
    assert worker_res.code is None and worker_res.note     # skipped, with an honest note
    assert all("worker" not in c for c in calls)           # the runner never saw the worker


def test_run_steps_captures_an_exception_and_keeps_going():
    def boom(argv):
        if argv[0] == "notify":
            raise RuntimeError("transport down")
        return 0

    plan = nightly.plan_steps(_ns("--sites", "aethelgem"), today=WED)
    results = nightly.run_steps(plan, runner=boom)
    by_label = {r.label: r for r in results}
    assert by_label["notify"].code == -1
    assert "transport down" in by_label["notify"].note
    assert by_label["worker"].code == 0                    # the chain continued past the failure


def test_run_steps_captures_systemexit_as_its_code():
    def exit2(argv):
        if argv[0] == "scan":
            raise SystemExit(2)                            # e.g. Bedrock unavailable
        return 0

    plan = nightly.plan_steps(_ns("--sites", "aethelgem", "--skip-worker"), today=WED)
    results = nightly.run_steps(plan, runner=exit2)
    scan_res = [r for r in results if r.label.startswith("scan")][0]
    assert scan_res.code == 2                              # captured, not re-raised


def test_print_summary_ok_ignores_skips_and_flags_failures():
    assert nightly._print_summary(
        [nightly.StepResult("scan:a", 0), nightly.StepResult("worker", None, "skipped")]) is True
    assert nightly._print_summary(
        [nightly.StepResult("scan:a", 0), nightly.StepResult("notify", 1)]) is False
    assert nightly._print_summary(
        [nightly.StepResult("scan:a", 2)]) is False        # a degraded scan is not "ok"


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
