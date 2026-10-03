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
  * ``run_origin`` / ``tag_reason``, which attribute a ledger row to the platform or to a human.
    That attribution is the only thing stopping a laptop rehearsal from being read as proof the
    Railway cron is wired, so it is a pure predicate and it fails towards 'local'.

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


def test_run_steps_checkpoints_progress_after_every_step():
    seen = []

    def fake(argv):
        return 0

    def progress(results):
        seen.append([r.label for r in results])

    plan = nightly.plan_steps(_ns("--sites", "aethelgem"), today=WED)
    nightly.run_steps(plan, runner=fake, progress=progress)
    # one checkpoint per step, each carrying every result so far — this is what
    # lets the ledger show how far the chain got if the process dies pre-finalize
    assert seen == [["scan:aethelgem"],
                    ["scan:aethelgem", "notify"],
                    ["scan:aethelgem", "notify", "worker"]]


def test_print_summary_ok_ignores_skips_and_flags_failures():
    assert nightly._print_summary(
        [nightly.StepResult("scan:a", 0), nightly.StepResult("worker", None, "skipped")]) is True
    assert nightly._print_summary(
        [nightly.StepResult("scan:a", 0), nightly.StepResult("notify", 1)]) is False
    assert nightly._print_summary(
        [nightly.StepResult("scan:a", 2)]) is False        # a degraded scan is not "ok"


# --------------------------------------------------------------------------- #
# rotation budget + schedule gate — the pure control-plane predicates
# --------------------------------------------------------------------------- #
def test_site_budget_covers_every_slot_inside_the_cycle():
    assert nightly.site_budget(15834, 30) == 528       # ceil(15834/30)
    assert nightly.site_budget(7606, 30) == 254        # ceil(7606/30)
    assert nightly.site_budget(77, 30) == 25           # floor: a tiny site still probed
    assert nightly.site_budget(0, 30) == 25
    assert nightly.site_budget(100, 7) == 25           # ceil(100/7)=15 < floor 25
    assert nightly.site_budget(1000, 7) == 143         # ceil(1000/7) above the floor
    assert nightly.site_budget(500, 0) == 500          # cycle clamped to >= 1 day


def test_gate_decision_priority_order():
    g = nightly.gate_decision
    assert g(enabled=False, run_requested_at="x", ran_today=False, run_in_flight=False,
             hour_utc=3, now_hour_utc=3) == (False, "disabled in board settings")
    assert g(enabled=True, run_requested_at=None, ran_today=False, run_in_flight=True,
             hour_utc=3, now_hour_utc=3)[0] is False       # one run at a time
    assert g(enabled=True, run_requested_at="2026-09-06T12:00:00Z", ran_today=True,
             run_in_flight=False, hour_utc=3, now_hour_utc=3)[0] is True   # request wins
    assert g(enabled=True, run_requested_at=None, ran_today=True, run_in_flight=False,
             hour_utc=3, now_hour_utc=3)[0] is False       # once per day
    assert g(enabled=True, run_requested_at=None, ran_today=False, run_in_flight=False,
             hour_utc=3, now_hour_utc=3)[0] is True        # the scheduled hour
    run, reason = g(enabled=True, run_requested_at=None, ran_today=False,
                    run_in_flight=False, hour_utc=3, now_hour_utc=14)
    assert run is False and "heartbeat" in reason          # any other hourly fire


def test_plan_steps_rotation_budgets_drive_due_selection():
    plan = nightly.plan_steps(_ns("--sites", "aethelgem"), today=WED,
                              budgets={"aethelgem": 528})
    assert _argv(plan, "scan:aethelgem") == [
        "scan", "--site", "aethelgem", "--select", "due", "--judge", "mantle",
        "--limit", "528"]


def test_plan_steps_explicit_due_without_budgets_keeps_default_limit():
    plan = nightly.plan_steps(_ns("--sites", "sandcart", "--select", "due"), today=WED)
    assert _argv(plan, "scan:sandcart") == [
        "scan", "--site", "sandcart", "--select", "due", "--judge", "mantle",
        "--limit", "25"]


# --------------------------------------------------------------------------- #
# ledger origin tagging — who actually started this fire
# --------------------------------------------------------------------------- #
def test_run_origin_reads_platform_markers_not_the_command_line():
    assert nightly.run_origin({}) == "local"                       # nothing injected => a human
    assert nightly.run_origin({"RAILWAY_SERVICE_ID": "svc"}) == "railway"
    assert nightly.run_origin({"RAILWAY_DEPLOYMENT_ID": "d"}) == "railway"
    assert nightly.run_origin({"RAILWAY_ENVIRONMENT": "prod"}) == "railway"
    assert nightly.run_origin({"RAILWAY_SERVICE_ID": ""}) == "local"    # empty is absent
    assert nightly.run_origin({"PATH": "/usr/bin"}) == "local"          # unrelated env


def test_run_origin_honours_the_explicit_override_both_ways():
    """One Dashboard variable restores attribution if Railway renames its own."""
    override = nightly.ORIGIN_OVERRIDE
    assert nightly.run_origin({override: "railway"}) == "railway"
    assert nightly.run_origin({override: "RAILWAY"}) == "railway"          # case-insensitive
    assert nightly.run_origin({override: " local "}) == "local"            # trimmed
    assert nightly.run_origin({override: "local",
                               "RAILWAY_SERVICE_ID": "svc"}) == "local"    # override wins
    assert nightly.run_origin({override: "nonsense",
                               "RAILWAY_SERVICE_ID": "svc"}) == "railway"   # nonsense ignored
    assert nightly.run_origin({override: "nonsense"}) == "local"           # and still conservative


def test_tag_reason_keeps_the_verdict_readable_and_machine_parsable():
    assert nightly.tag_reason("railway", "heartbeat (next run 3:00 UTC)") == \
        "[railway] heartbeat (next run 3:00 UTC)"
    assert nightly.tag_reason("local", "--force") == "[local] --force"
    assert nightly.tag_reason("local", "") == "[local] "                   # never drops the tag


# 通过 main + 原始 run_steps 驱动闭包生命周期；runner/DB 全部替身化。
from types import SimpleNamespace
from unittest.mock import Mock

import psycopg
import pytest


class _LedgerConn:
    def __init__(self, name):
        self.name = name
        self.closed = False
        self.close_calls = 0
        self.info = SimpleNamespace(dsn="postgresql://test@example.invalid/own")

    def close(self):
        self.close_calls += 1
        self.closed = True

    def cursor(self):
        pytest.fail("nightly 回归不允许未注入的 SQL")


@pytest.fixture
def ledger_io(monkeypatch):
    old, candidate, recovered = [_LedgerConn(name) for name in ("old", "candidate", "recovered")]
    state = SimpleNamespace(
        old=old, candidate=candidate, recovered=recovered,
        writes={"checkpoint": [], "finalize": []}, failures={"checkpoint": {}, "finalize": {}},
        observations=[], step_codes=[0, 0],
        plan=nightly.Plan([nightly.Step("scan:synthetic-a", ["scan", "a"]),
                           nightly.Step("scan:synthetic-b", ["scan", "b"])]))
    state.connect = Mock(side_effect=[old, candidate, recovered])
    monkeypatch.setenv("EVERLINK_DATABASE_URL", old.info.dsn)
    monkeypatch.setenv("EVERLINK_CRON_ORIGIN", "local")
    for name in nightly.db.SOURCE_DSN_VARS:
        monkeypatch.delenv(name, raising=False)

    def forbidden(*args, **kwargs):
        pytest.fail("nightly 回归禁止真实 CLI/网络/数据库连接")

    monkeypatch.setattr(psycopg, "connect", forbidden)
    monkeypatch.setattr(nightly.cli, "main", forbidden)
    monkeypatch.setattr(nightly.db, "connect", state.connect)
    monkeypatch.setattr(nightly.db, "ensure_schema", Mock())
    monkeypatch.setattr(nightly.db, "reap_stale_runs", Mock(return_value=[]))
    monkeypatch.setattr(nightly.db, "get_settings", Mock(return_value=nightly.db.default_settings()))
    monkeypatch.setattr(nightly.db, "set_settings", Mock())
    monkeypatch.setattr(nightly.db, "count_active_slots", Mock(return_value={}))
    monkeypatch.setattr(nightly.db, "prune_heartbeats", Mock(return_value=0))
    monkeypatch.setattr(nightly.db, "insert_run", Mock(return_value=41))
    monkeypatch.setattr(nightly, "_run_state", Mock(return_value=(False, False)))

    def record(phase, conn, run_id, payload, status=None):
        assert run_id == 41
        state.writes[phase].append((conn, payload, status))
        if conn.closed:
            raise psycopg.InterfaceError("synthetic closed connection")
        errors = state.failures[phase].get(conn, [])
        if errors:
            raise errors.pop(0)

    monkeypatch.setattr(nightly.db, "update_run_summary",
                        lambda c, rid, payload: record("checkpoint", c, rid, payload))
    monkeypatch.setattr(nightly.db, "finish_run",
                        lambda c, rid, status, summary=None: record("finalize", c, rid, summary, status))
    monkeypatch.setattr(nightly, "plan_steps", lambda *a, **k: state.plan)
    real_run_steps = nightly.run_steps

    def run(plan, runner=None, progress=None):
        codes = iter(state.step_codes)

        def checkpoint(results):
            if progress is not None:
                progress(results)
            state.observations.append((state.connect.call_count, old.closed, candidate.closed))

        return real_run_steps(plan, runner=lambda argv: next(codes), progress=checkpoint)

    monkeypatch.setattr(nightly, "run_steps", run)
    state.argv = ["--force", "--select", "head", "--limit", "1", "--sites", "synthetic"]
    return state


class TestNightlyLedgerContract:
    @pytest.mark.parametrize("error_type", [psycopg.OperationalError, psycopg.InterfaceError,
                                            psycopg.errors.ConnectionFailure])
    def test_connection_checkpoint_retries_once_and_replaces_shared_connection(self, ledger_io, error_type):
        io = ledger_io
        io.failures["checkpoint"][io.old] = [error_type("synthetic disconnect")]
        assert nightly.main(io.argv) == 0
        assert io.connect.call_count == 2
        assert [row[0] for row in io.writes["checkpoint"]] == [io.old, io.candidate, io.candidate]
        assert [row[0] for row in io.writes["finalize"]] == [io.candidate]
        assert io.observations[0] == (2, True, False)
        assert io.old.closed and io.candidate.closed

    @pytest.mark.parametrize("error_type", [psycopg.errors.InsufficientPrivilege,
                                            psycopg.errors.SyntaxError])
    def test_checkpoint_permission_and_sql_failures_do_not_blindly_reconnect(self, ledger_io, error_type):
        io = ledger_io
        io.failures["checkpoint"][io.old] = [error_type("synthetic SQL failure")]
        nightly.main(io.argv)
        assert io.observations[0][0] == 1
        assert io.connect.call_count == 1
        assert io.old.closed

    @pytest.mark.parametrize("recovery_at", ["checkpoint", "finalize"])
    @pytest.mark.parametrize("failure_at", ["connect", "candidate_write"])
    def test_failed_candidate_is_invalidated_and_later_operation_can_reconnect(
            self, ledger_io, recovery_at, failure_at):
        io = ledger_io
        io.failures["checkpoint"][io.old] = [psycopg.OperationalError("synthetic idle disconnect")]
        if failure_at == "connect":
            io.connect.side_effect = [io.old, psycopg.OperationalError("synthetic connect failure"), io.recovered]
        else:
            io.failures["checkpoint"][io.candidate] = [psycopg.OperationalError("synthetic candidate failure")]
        if recovery_at == "finalize":
            io.plan.steps = io.plan.steps[:1]
        nightly.main(io.argv)
        # 同一 checkpoint 最多取得一次候选，重试失败后不能留下旧引用或坏候选。
        assert io.observations[0][0] == 2
        assert io.observations[0][1] is True
        if failure_at == "candidate_write":
            assert io.observations[0][2] is True
        expected = [io.old] + ([io.candidate] if failure_at == "candidate_write" else [])
        if recovery_at == "checkpoint":
            expected += [io.recovered]
        assert [row[0] for row in io.writes["checkpoint"]] == expected
        assert [row[0] for row in io.writes["finalize"]] == [io.recovered]
        assert io.connect.call_count == 3
        assert io.recovered.closed

    @pytest.mark.parametrize("failure_at", ["connect", "write"])
    def test_exhausted_finalize_retry_is_failure_and_closes_every_candidate(self, ledger_io, failure_at):
        io = ledger_io
        io.failures["finalize"][io.old] = [psycopg.OperationalError("synthetic finalize disconnect")]
        if failure_at == "connect":
            io.connect.side_effect = [io.old, psycopg.OperationalError("synthetic reconnect failure")]
        else:
            io.failures["finalize"][io.candidate] = [psycopg.OperationalError("synthetic finalize failure")]
        result = nightly.main(io.argv)
        assert io.old.closed
        if failure_at == "write":
            assert io.candidate.closed
        assert io.connect.call_count == 2
        assert result == 1

    def test_successful_fresh_finalize_closes_both_connections(self, ledger_io):
        io = ledger_io
        io.failures["finalize"][io.old] = [psycopg.OperationalError("synthetic disconnect")]
        assert nightly.main(io.argv) == 0
        assert [row[0] for row in io.writes["finalize"]] == [io.old, io.candidate]
        assert io.connect.call_count == 2
        assert io.old.closed and io.candidate.closed

    @pytest.mark.parametrize("error_type", [psycopg.errors.InsufficientPrivilege,
                                            psycopg.errors.SyntaxError])
    def test_finalize_permission_and_sql_failures_are_not_retried(self, ledger_io, error_type):
        io = ledger_io
        io.failures["finalize"][io.old] = [error_type("synthetic final SQL failure")]
        result = nightly.main(io.argv)
        assert io.connect.call_count == 1
        assert io.old.closed
        assert result == 1

    @pytest.mark.parametrize("code,status,exit_code", [(0, "ok", 0), (2, "degraded", 1), (1, "fail", 1)])
    def test_scan_exit_and_ledger_status_remain_honest(self, ledger_io, code, status, exit_code):
        io = ledger_io
        io.step_codes = [code, 0]
        assert nightly.main(io.argv) == exit_code
        conn, summary, saved_status = io.writes["finalize"][-1]
        assert saved_status == status
        assert summary["steps"][0]["code"] == code
        assert conn.closed

    @pytest.mark.parametrize("boundary", ["connect", "settings", "run_state"])
    def test_schedule_read_failure_is_nonzero_not_successful_skip(self, ledger_io, boundary):
        io = ledger_io
        error = psycopg.OperationalError("synthetic schedule failure")
        if boundary == "connect":
            io.connect.side_effect = error
        elif boundary == "settings":
            nightly.db.get_settings.side_effect = error
        else:
            nightly._run_state.side_effect = error
        assert nightly.main([]) == 1
        assert not io.writes["checkpoint"] and not io.writes["finalize"]
        if boundary != "connect":
            assert io.old.closed

    def test_already_ran_today_remains_a_successful_heartbeat_skip(self, ledger_io):
        io = ledger_io
        nightly._run_state.return_value = (True, False)
        assert nightly.main([]) == 0
        args = nightly.db.insert_run.call_args.args
        assert args[1:3] == ("heartbeat", "skipped")
        assert "already ran today" in args[3]
        assert not io.writes["checkpoint"] and not io.writes["finalize"]
        assert io.old.closed

    def test_prune_failure_does_not_rewrite_successful_finalize(self, ledger_io, capsys):
        io = ledger_io
        nightly.db.prune_heartbeats.side_effect = psycopg.OperationalError("synthetic prune failure")
        assert nightly.main(io.argv) == 0
        assert len(io.writes["finalize"]) == 1
        assert io.writes["finalize"][0][2] == "ok"
        captured = capsys.readouterr()
        assert "prune" in captured.err.lower()
        assert "finalize failed" not in captured.err.lower()
        assert io.connect.call_count == 1 and io.old.closed

    def test_prune_and_finalize_failures_are_reported_as_separate_operations(self, ledger_io, capsys):
        io = ledger_io
        io.failures["finalize"][io.old] = [psycopg.OperationalError("synthetic disconnect")]
        nightly.db.prune_heartbeats.side_effect = psycopg.OperationalError("synthetic prune failure")
        assert nightly.main(io.argv) == 0
        captured = capsys.readouterr()
        assert "finalize" in captured.err.lower() and "prune" in captured.err.lower()
        assert len(io.writes["finalize"]) == 2
        assert io.old.closed and io.candidate.closed


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
