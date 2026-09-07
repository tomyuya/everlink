"use client";

/**
 * The operator control plane island of /settings: rotation cycle, cron schedule
 * knobs and the run-now request. Every mutation goes through /api/settings*
 * (audited as settings_change / run_requested) and then router.refresh() so the
 * server-rendered ledger + coverage re-read the DB.
 *
 * PRECONDITION GATE: the knobs stay disabled until the DB + control-plane
 * schema are reachable; "Run now" additionally needs a cron that fires OFTEN
 * ENOUGH to pick the request up within the hour (runNowAvailable). A healthy
 * daily cron is alive but cannot honour "now" — the request would sit until the
 * next 03:00 fire — so the button stays locked and the tooltip says why; the UI
 * never pretends a run will start.
 */
import { Play, Save } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

import type { BoardSettings, RotationRow } from "@/lib/types";
import { siteLabel, siteUrl } from "@/lib/utils";

export interface SettingsPreconditions {
  db: boolean;
  schema: boolean;
  heartbeatAlive: boolean;
  runNowAvailable: boolean;
  /** Inferred cron period in minutes (null = cadence not yet learnable). */
  periodMin: number | null;
  lastFireAt: string | null;
}

/** Mirror of nightly.site_budget: ceil(active / cycle), floor 25. */
function siteBudget(active: number, cycle: number): number {
  return Math.max(25, Math.ceil(active / Math.max(1, cycle)));
}

function fmtUtc(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "—" : d.toISOString().replace("T", " ").slice(0, 16) + " UTC";
}

/** "≈hourly" / "≈daily" from the inferred period, for honest schedule wording. */
function cadenceLabel(periodMin: number | null): string | null {
  if (periodMin === null) return null;
  if (periodMin <= 90) return "≈hourly";
  if (periodMin <= 2880) return "≈daily";
  return `≈every ${Math.round(periodMin / 1440)} days`;
}

export function SettingsPanel({
  settings,
  pre,
  rotation,
}: {
  settings: BoardSettings;
  pre: SettingsPreconditions;
  rotation: RotationRow[];
}) {
  const router = useRouter();
  const [cycle, setCycle] = useState(settings.rotation_cycle_days);
  const [hour, setHour] = useState(settings.run_hour_utc);
  const [enabled, setEnabled] = useState(settings.enabled);
  const [busy, setBusy] = useState<"save" | "run" | null>(null);
  const [msg, setMsg] = useState<{ kind: "ok" | "err"; text: string } | null>(null);

  const controlsOn = pre.db && pre.schema;
  const dirty =
    cycle !== settings.rotation_cycle_days ||
    hour !== settings.run_hour_utc ||
    enabled !== settings.enabled;

  async function save() {
    setBusy("save");
    setMsg(null);
    try {
      const res = await fetch("/api/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ rotation_cycle_days: cycle, run_hour_utc: hour, enabled }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.error || res.statusText);
      setMsg({ kind: "ok", text: "Saved — the next cron fire reads the new settings." });
      router.refresh();
    } catch (e) {
      setMsg({ kind: "err", text: e instanceof Error ? e.message : "save failed" });
    } finally {
      setBusy(null);
    }
  }

  async function runNow() {
    setBusy("run");
    setMsg(null);
    try {
      const res = await fetch("/api/settings/run-now", { method: "POST" });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.error || res.statusText);
      setMsg({
        kind: "ok",
        text: "Run requested — the next cron fire (≤60 min) picks it up and clears the request.",
      });
      router.refresh();
    } catch (e) {
      setMsg({ kind: "err", text: e instanceof Error ? e.message : "run-now failed" });
    } finally {
      setBusy(null);
    }
  }

  const inputCls =
    "rounded-md border border-zinc-300 bg-white px-2 py-1.5 text-sm text-zinc-900 " +
    "dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100 disabled:opacity-50";

  return (
    <div className="space-y-6">
      <div className="grid gap-4 md:grid-cols-2">
        {/* ------------------------------------------------ rotation cycle --- */}
        <section className="rounded-lg border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900">
          <h2 className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">
            Rotation cycle
          </h2>
          <p className="mt-1 text-xs text-zinc-500 dark:text-zinc-400">
            Every active slot is probed once per cycle: each nightly run takes the
            least-recently-checked slots, budget = ceil(active ÷ cycle), floor 25/site.
          </p>
          <label className="mt-3 flex items-center gap-2 text-sm text-zinc-700 dark:text-zinc-300">
            Full-pass cycle
            <input
              type="number"
              min={7}
              max={120}
              value={cycle}
              disabled={!controlsOn}
              onChange={(e) => setCycle(Number(e.target.value))}
              className={inputCls + " w-24"}
            />
            days
          </label>
          {/* Same guard as the cron ledger: scroll sideways rather than stretch the
              page if this table ever grows a column or the viewport gets narrow. */}
          <div className="mt-3 overflow-x-auto">
            <table className="w-full text-left text-xs text-zinc-600 dark:text-zinc-400">
              <thead>
                <tr className="border-b border-zinc-200 dark:border-zinc-800">
                  <th className="py-1 pr-2 font-medium">site</th>
                  <th className="py-1 pr-2 font-medium">active</th>
                  <th className="py-1 pr-2 font-medium">daily budget</th>
                  <th className="py-1 pr-2 font-medium">covered in cycle</th>
                  <th className="py-1 font-medium">oldest probe</th>
                </tr>
              </thead>
              <tbody>
                {rotation.map((r) => {
                  const pct = r.active > 0 ? Math.round((r.covered / r.active) * 100) : 0;
                  const url = siteUrl(r.site);
                  return (
                    <tr key={r.site} className="border-b border-zinc-100 dark:border-zinc-800/60">
                      {/* Brand name, not the internal key (sandcart -> FlashDeals),
                          linked to the live store so a reader can click through
                          and verify it is a real site. Unmapped keys stay plain. */}
                      <td className="py-1 pr-2">
                        {url ? (
                          <a
                            href={url}
                            target="_blank"
                            rel="noopener noreferrer"
                            title={`Open ${siteLabel(r.site)} in a new tab`}
                            className="font-medium text-sky-600 hover:underline dark:text-sky-400"
                          >
                            {siteLabel(r.site)}
                          </a>
                        ) : (
                          <span className="font-mono">{siteLabel(r.site)}</span>
                        )}
                      </td>
                      <td className="py-1 pr-2">{r.active.toLocaleString()}</td>
                      <td className="py-1 pr-2">{siteBudget(r.active, cycle).toLocaleString()}</td>
                      <td className="py-1 pr-2">
                        <span className="inline-flex items-center gap-1.5">
                          <span className="inline-block h-1.5 w-16 overflow-hidden rounded-full bg-zinc-200 dark:bg-zinc-800">
                            <span
                              className="block h-full rounded-full bg-emerald-500"
                              style={{ width: `${pct}%` }}
                            />
                          </span>
                          {pct}%
                        </span>
                      </td>
                      <td className="py-1">{fmtUtc(r.oldest)}</td>
                    </tr>
                  );
                })}
                {rotation.length === 0 && (
                  <tr>
                    <td colSpan={5} className="py-2 text-zinc-400">
                      No slots in the mirror yet.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </section>

        {/* --------------------------------------------- schedule & cron ----- */}
        <section className="rounded-lg border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900">
          <h2 className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">
            Schedule &amp; cron
          </h2>
          <p className="mt-1 text-xs text-zinc-500 dark:text-zinc-400">
            The cron fires as a heartbeat and the gate decides: the fire matching this
            hour (UTC) runs the full chain, every other fire logs an honest heartbeat
            skip. An hourly schedule picks up a <em>Run now</em> within the hour; a daily
            one only at its next fire.
          </p>
          <div className="mt-3 space-y-3 text-sm text-zinc-700 dark:text-zinc-300">
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={enabled}
                disabled={!controlsOn}
                onChange={(e) => setEnabled(e.target.checked)}
                className="h-4 w-4 accent-zinc-900 dark:accent-zinc-100"
              />
              cron enabled (kill-switch)
            </label>
            <label className="flex items-center gap-2">
              Run hour
              <select
                value={hour}
                disabled={!controlsOn}
                onChange={(e) => setHour(Number(e.target.value))}
                className={inputCls}
              >
                {Array.from({ length: 24 }, (_, h) => (
                  <option key={h} value={h}>
                    {String(h).padStart(2, "0")}:00 UTC
                  </option>
                ))}
              </select>
            </label>
            <div className="flex flex-wrap items-center gap-2">
              <button
                type="button"
                onClick={save}
                disabled={!controlsOn || !dirty || busy !== null}
                className="inline-flex items-center gap-1.5 rounded-md bg-zinc-900 px-3 py-1.5 text-xs font-medium text-white disabled:opacity-40 dark:bg-zinc-100 dark:text-zinc-900"
              >
                <Save className="h-3.5 w-3.5" />
                {busy === "save" ? "Saving…" : "Save settings"}
              </button>
              <button
                type="button"
                onClick={runNow}
                disabled={!controlsOn || !pre.runNowAvailable || !enabled || busy !== null}
                title={
                  pre.runNowAvailable
                    ? "Ask the next cron fire to run the chain now (picked up within the hour)"
                    : !pre.heartbeatAlive
                      ? "Needs a live cron heartbeat (a Railway-tagged fire within its expected window — a run started on a laptop does not count)"
                      : pre.periodMin === null
                        ? "Cron is wired and has fired once, but not often enough yet to confirm it can run 'now' within the hour. It clarifies after the next fire — or switch the Railway cron to 0 * * * * (hourly) to enable on-demand runs now."
                        : "Your cron fires about once a day, so it cannot run 'now' — the request would wait until the next daily fire. Switch the Railway cron to 0 * * * * (hourly) to enable on-demand runs."
                }
                className="inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium ring-1 ring-inset ring-zinc-300 hover:bg-zinc-100 disabled:opacity-40 dark:ring-zinc-700 dark:hover:bg-zinc-800"
              >
                <Play className="h-3.5 w-3.5" />
                {busy === "run" ? "Requesting…" : "Run now"}
              </button>
              {settings.run_requested_at && (
                <span className="rounded-full bg-amber-100 px-2 py-0.5 text-[11px] font-medium text-amber-800 dark:bg-amber-900/40 dark:text-amber-200">
                  run requested {fmtUtc(settings.run_requested_at)}
                </span>
              )}
            </div>
            <p className="text-[11px] text-zinc-400 dark:text-zinc-500">
              last change: {fmtUtc(settings.updated_at)}
              {settings.updated_by ? ` by ${settings.updated_by}` : ""} · heartbeat:{" "}
              {pre.heartbeatAlive ? (
                <>
                  alive{cadenceLabel(pre.periodMin) ? ` (${cadenceLabel(pre.periodMin)})` : ""} ·{" "}
                  {fmtUtc(pre.lastFireAt)}
                </>
              ) : (
                "NOT alive"
              )}
            </p>
          </div>
        </section>
      </div>

      {msg && (
        <p
          className={
            msg.kind === "ok"
              ? "rounded-md bg-emerald-50 px-3 py-2 text-xs text-emerald-800 dark:bg-emerald-900/30 dark:text-emerald-200"
              : "rounded-md bg-rose-50 px-3 py-2 text-xs text-rose-800 dark:bg-rose-900/30 dark:text-rose-200"
          }
        >
          {msg.text}
        </p>
      )}
    </div>
  );
}
