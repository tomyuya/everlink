import type { Metadata } from "next";
import {
  Activity,
  Database,
  Settings as SettingsIcon,
  Table2,
  Timer,
} from "lucide-react";

import { SettingsPanel } from "@/components/settings-panel";
import { isConfigured } from "@/lib/db";
import { cronOverview, getSettings, rotationCoverage } from "@/lib/queries";
import type { BoardSettings, CronOverview, NightlyRunRow, RotationRow } from "@/lib/types";
import { formatDateTime, safeJsonParse } from "@/lib/utils";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "Settings · EverLink Board",
};

/** The control-plane tables the agent's ensure_schema creates on first connect. */
function isSchemaMissing(message: string): boolean {
  return /does not exist|undefined_table|relation/i.test(message);
}

export default async function SettingsPage() {
  const dbOk = isConfigured();
  let settings: BoardSettings | null = null;
  let overview: CronOverview | null = null;
  let rotation: RotationRow[] = [];
  let dbError: string | null = null;
  let schemaPending = false;

  if (!dbOk) {
    dbError = "EVERLINK_DATABASE_URL is not configured for this board.";
  } else {
    try {
      settings = await getSettings();
    } catch (e) {
      const message = e instanceof Error ? e.message : "Failed to read settings";
      if (isSchemaMissing(message)) schemaPending = true;
      else dbError = message;
    }
    if (settings) {
      try {
        overview = await cronOverview();
      } catch {
        schemaPending = true;
      }
      try {
        rotation = await rotationCoverage(settings.rotation_cycle_days);
      } catch {
        schemaPending = true;   // link_slots.last_checked_at not migrated yet
      }
    }
  }

  const pre = {
    db: dbOk && !dbError,
    schema: settings !== null && !schemaPending,
    heartbeatAlive: overview?.heartbeat_alive ?? false,
    lastFireAt: overview?.last_fire_at ?? null,
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="flex items-center gap-2 text-xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-100">
          <SettingsIcon className="h-5 w-5" />
          Settings
        </h1>
        <p className="mt-1 text-sm text-zinc-500 dark:text-zinc-400">
          The autonomous loop&apos;s control plane: rotation coverage, cron schedule and
          the run ledger. The agent reads this row on every cron fire.
        </p>
      </div>

      {dbError ? (
        <div className="rounded-lg border border-rose-200 bg-rose-50 p-4 text-sm text-rose-800 dark:border-rose-900 dark:bg-rose-950/40 dark:text-rose-200">
          Database unavailable: {dbError}
        </div>
      ) : (
        <>
          {/* ------------------------------------------- preconditions ------- */}
          <section className="rounded-lg border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900">
            <h2 className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">
              Cron preconditions
            </h2>
            <ul className="mt-2 space-y-1.5 text-sm text-zinc-600 dark:text-zinc-400">
              <PreconditionRow
                ok={pre.db}
                icon={<Database className="h-4 w-4" />}
                label="Operational DB reachable"
                detail={pre.db ? "EVERLINK_DATABASE_URL configured" : "not configured"}
              />
              <PreconditionRow
                ok={pre.schema}
                icon={<Table2 className="h-4 w-4" />}
                label="Control-plane schema present"
                detail={
                  pre.schema
                    ? "settings + nightly_runs + rotation column live"
                    : "missing — applied on the next agent run (schema.sql)"
                }
              />
              <PreconditionRow
                ok={pre.heartbeatAlive}
                icon={<Timer className="h-4 w-4" />}
                label="Cron heartbeat alive (fire within 75 min)"
                detail={
                  overview?.last_fire_at
                    ? `last fire ${formatDateTime(overview.last_fire_at)}`
                    : "no fire recorded yet"
                }
              />
            </ul>
            {!pre.heartbeatAlive && (
              <div className="mt-3 rounded-md bg-amber-50 p-3 text-xs text-amber-900 dark:bg-amber-900/30 dark:text-amber-200">
                <p className="font-semibold">One-time Railway wiring (Dashboard → service → Settings):</p>
                <ul className="mt-1 list-inside list-disc space-y-0.5">
                  <li>Cron Schedule = Custom = <code className="font-mono">0 * * * *</code> (hourly heartbeat)</li>
                  <li>Restart Policy = <code className="font-mono">Never</code></li>
                  <li>Custom Start Command = <code className="font-mono">python scripts/nightly.py</code></li>
                </ul>
                <p className="mt-1.5">
                  Until then the legacy daily 03:00 UTC fire still runs the chain once a
                  day (the gate honours it), but <em>Run now</em> stays locked — nothing
                  would consume the request. Push-deploy fires are harmless heartbeats.
                </p>
              </div>
            )}
          </section>

          {settings && (
            <SettingsPanel settings={settings} pre={pre} rotation={rotation} />
          )}

          {/* ------------------------------------------------ run ledger ----- */}
          <section className="rounded-lg border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900">
            <h2 className="flex items-center gap-1.5 text-sm font-semibold text-zinc-900 dark:text-zinc-100">
              <Activity className="h-4 w-4" />
              Cron ledger (last {overview?.runs.length ?? 0} entries)
            </h2>
            <p className="mt-1 text-xs text-zinc-500 dark:text-zinc-400">
              {overview?.last_run ? (
                <>
                  Last full run{" "}
                  <span className="font-mono">{formatDateTime(overview.last_run.started_at)}</span>{" "}
                  <span
                    className={
                      overview.last_run.status === "ok"
                        ? "text-emerald-600 dark:text-emerald-400"
                        : "text-amber-600 dark:text-amber-400"
                    }
                  >
                    {overview.last_run.status}
                  </span>
                  {runDuration(overview.last_run)} · trigger{" "}
                  {overview.last_run.reason ?? "—"}
                  {runBudgets(overview.last_run.summary) && (
                    <> · budget {runBudgets(overview.last_run.summary)}</>
                  )}
                </>
              ) : (
                "No full run recorded yet — the next fire at the configured run hour starts one."
              )}
            </p>
            <p className="mt-0.5 text-[11px] text-zinc-400 dark:text-zinc-500">
              Heartbeat skips are pruned after 14 days; every full run is kept.
            </p>
            <table className="mt-2 w-full text-left text-xs text-zinc-600 dark:text-zinc-400">
              <thead>
                <tr className="border-b border-zinc-200 dark:border-zinc-800">
                  <th className="py-1 pr-3 font-medium">started (UTC)</th>
                  <th className="py-1 pr-3 font-medium">kind</th>
                  <th className="py-1 pr-3 font-medium">status</th>
                  <th className="py-1 pr-3 font-medium">duration</th>
                  <th className="py-1 font-medium">reason / trigger</th>
                </tr>
              </thead>
              <tbody>
                {(overview?.runs ?? []).map((r) => (
                  <tr key={r.id} className="border-b border-zinc-100 dark:border-zinc-800/60">
                    <td className="py-1 pr-3 font-mono">{formatDateTime(r.started_at)}</td>
                    <td className="py-1 pr-3">{r.kind}</td>
                    <td className="py-1 pr-3">
                      <span
                        className={
                          r.status === "ok"
                            ? "text-emerald-600 dark:text-emerald-400"
                            : r.status === "skipped"
                              ? "text-zinc-400"
                              : "text-amber-600 dark:text-amber-400"
                        }
                      >
                        {r.status}
                      </span>
                    </td>
                    <td className="py-1 pr-3">
                      {r.finished_at
                        ? `${Math.max(0, Math.round((new Date(r.finished_at).getTime() - new Date(r.started_at).getTime()) / 1000))}s`
                        : "…"}
                    </td>
                    <td className="py-1">{r.reason ?? ""}</td>
                  </tr>
                ))}
                {(overview?.runs.length ?? 0) === 0 && (
                  <tr>
                    <td colSpan={5} className="py-2 text-zinc-400">
                      No cron fire recorded yet — the ledger fills on the first fire
                      after this schema lands.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </section>
        </>
      )}
    </div>
  );
}

function runDuration(row: NightlyRunRow): string {
  if (!row.finished_at) return " · still running";
  const secs = Math.max(
    0,
    Math.round(
      (new Date(row.finished_at).getTime() - new Date(row.started_at).getTime()) / 1000,
    ),
  );
  return ` · ${secs}s`;
}

/** The per-site probe budget a run actually used, from its JSON summary. */
function runBudgets(summary: string | null): string | null {
  const parsed = safeJsonParse<{ budgets?: Record<string, number> | null }>(summary, {});
  const budgets = parsed?.budgets;
  if (!budgets || typeof budgets !== "object") return null;
  const parts = Object.entries(budgets)
    .filter(([, n]) => Number.isFinite(Number(n)))
    .map(([site, n]) => `${site} ${Number(n).toLocaleString()}`);
  return parts.length > 0 ? parts.join(", ") : null;
}

function PreconditionRow({
  ok,
  icon,
  label,
  detail,
}: {
  ok: boolean;
  icon: React.ReactNode;
  label: string;
  detail: string;
}) {
  return (
    <li className="flex items-start gap-2">
      <span
        className={
          ok
            ? "mt-0.5 text-emerald-600 dark:text-emerald-400"
            : "mt-0.5 text-amber-600 dark:text-amber-400"
        }
      >
        {icon}
      </span>
      <span>
        <span className={ok ? "text-zinc-800 dark:text-zinc-200" : "text-amber-800 dark:text-amber-300"}>
          {label}
        </span>
        <span className="text-zinc-400 dark:text-zinc-500"> — {detail}</span>
      </span>
    </li>
  );
}
