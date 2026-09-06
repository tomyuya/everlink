import Link from "next/link";
import { CalendarClock, Terminal } from "lucide-react";

import { CopyButton } from "./copy-button";

/** What the board's control plane can state as FACT on a public page.
 *
 * Deliberately absent: any "heartbeat alive" verdict. Liveness is inferred from
 * the ledger's newest fire, and a fire started by a human running
 * `python scripts/nightly.py` on a laptop is indistinguishable there from a
 * Railway cron fire (only `--force` rows are attributable). Showing that guess
 * here would mislead in BOTH directions — green after one local rehearsal, or
 * "quiet" while a perfectly healthy `0 3 * * *` cron runs every night. The
 * verdict belongs on /settings, where the precondition checklist and the
 * one-time wiring steps give it context. Everything below is read straight from
 * the `settings` row or quoted from a ledger row, so it cannot overclaim.
 */
export interface ScheduleState {
  runHourUtc: number;
  cycleDays: number;
  enabled: boolean;
  /** Newest full run, quoted from the ledger (null = empty/unreadable ledger).
   * `ok` drives the chip tone so a failed run can never render green. */
  lastRun: { label: string; ok: boolean } | null;
}

const COMMANDS: { cmd: string; note: string }[] = [
  {
    cmd: "python scripts/nightly.py",
    note: "The production entrypoint: schedule gate → rotation budget → scan every site → notify → drain approved fixes. On a cron fire it decides for itself whether to run or log a heartbeat.",
  },
  {
    cmd: "python scripts/nightly.py --dry-run --judge none",
    note: "Safe offline smoke — proves the chain is wired; writes nothing, sends nothing, skips the worker.",
  },
];

const FLAGS: { flag: string; desc: string }[] = [
  { flag: "--force", desc: "Bypass the schedule gate and run the chain now (manual triggers)." },
  { flag: "--select due|head", desc: "due = the least-recently-checked mirror slots (rotation; the default when a DB is configured). head = the snapshot's first N, the legacy behaviour." },
  { flag: "--judge none|stub|bedrock|mantle", desc: "Judge backend. mantle = the real LLM via Bedrock (production); none = detection only, no creds." },
  { flag: "--dry-run", desc: "Scan writes nothing and notify sends nothing; the worker step is skipped (it writes)." },
  { flag: "--sites a,b,c", desc: "Restrict the scan targets (default: the three first-party sites)." },
  { flag: "--weekly", desc: "Force the weekly digest step now (otherwise it folds in automatically on Monday)." },
];

/**
 * How the loop runs itself — the schedule gate, the rotation budget, the exact
 * entrypoint, and the honest limit of what a browser can trigger.
 *
 * HONESTY NOTE (deliberate): the board is a Next.js app on Vercel while the agent is a
 * Python service on Railway, so a button here cannot exec Python. What it CAN do is
 * stamp a run-now request into the `settings` row, which the next cron fire consumes —
 * a real trigger, mediated by the DB, and locked until a live heartbeat proves the cron
 * is wired (see /settings). Everything else on this panel is documentation + live state.
 */
export function AutomationPanel({
  lastActivity,
  schedule,
}: {
  lastActivity: string;
  schedule?: ScheduleState | null;
}) {
  const hour = schedule ? `${String(schedule.runHourUtc).padStart(2, "0")}:00 UTC` : "the configured hour";
  return (
    <section
      aria-label="Automation and nightly entrypoint"
      className="rounded-xl border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900"
    >
      <div className="flex flex-wrap items-center gap-2">
        <Terminal className="h-4 w-4 text-sky-600 dark:text-sky-400" />
        <h2 className="text-sm font-semibold text-zinc-800 dark:text-zinc-200">
          Automation · the nightly loop
        </h2>
        <Chip icon={<CalendarClock className="h-3 w-3" />}>
          chain runs {hour}
          {schedule ? ` · full pass every ${schedule.cycleDays}d` : ""}
        </Chip>
        {schedule?.lastRun ? (
          <Chip tone={schedule.lastRun.ok ? "ok" : "warn"}>
            last run {schedule.lastRun.label}
          </Chip>
        ) : null}
        {schedule && !schedule.enabled ? <Chip tone="warn">cron disabled</Chip> : null}
        <span className="ml-auto text-[11px] text-zinc-400 dark:text-zinc-500">
          last activity {lastActivity || "—"}
        </span>
      </div>

      <p className="mt-2 text-xs leading-relaxed text-zinc-500 dark:text-zinc-400">
        Nobody opens a terminal in production. The cron fires as a heartbeat and the gate
        decides: only the fire matching the run hour runs the whole chain, and every other
        fire logs an honest heartbeat skip. (An hourly cron gives run-now a
        within-the-hour pickup; a daily cron set to the run hour works too.) Each run
        rotates: per-site budget ={" "}
        <code className="font-mono text-[11px] text-zinc-600 dark:text-zinc-300">
          ceil(active ÷ cycle)
        </code>{" "}
        least-recently-checked slots, so one cycle covers the WHOLE mirror instead of
        re-probing the same head forever.
      </p>

      <p className="mt-2 text-xs">
        <Link
          href="/settings"
          className="font-medium text-sky-600 hover:underline dark:text-sky-400"
        >
          Steer it on /settings — rotation cycle, run hour, kill-switch, run-now,
          heartbeat liveness and the cron ledger →
        </Link>
      </p>

      <div className="mt-3 space-y-2">
        {COMMANDS.map(({ cmd, note }) => (
          <div key={cmd} className="rounded-lg bg-zinc-950 px-3 py-2 dark:bg-black/60">
            <div className="flex items-center gap-2">
              <code className="flex-1 overflow-x-auto whitespace-nowrap font-mono text-xs text-emerald-300">
                {cmd}
              </code>
              <CopyButton text={cmd} />
            </div>
            <p className="mt-1 text-[11px] leading-relaxed text-zinc-400">{note}</p>
          </div>
        ))}
      </div>

      <details className="mt-3 group">
        <summary className="cursor-pointer select-none text-xs font-medium text-zinc-600 hover:text-zinc-900 dark:text-zinc-300 dark:hover:text-zinc-100">
          Useful flags
        </summary>
        <dl className="mt-2 space-y-1.5 rounded-lg bg-zinc-50 p-3 dark:bg-zinc-950/60">
          {FLAGS.map(({ flag, desc }) => (
            <div key={flag} className="grid gap-0.5 sm:grid-cols-[220px_1fr] sm:gap-3">
              <dt className="font-mono text-[11px] text-sky-700 dark:text-sky-400">{flag}</dt>
              <dd className="text-[11px] text-zinc-500 dark:text-zinc-400">{desc}</dd>
            </div>
          ))}
        </dl>
      </details>
    </section>
  );
}

function Chip({
  children,
  icon,
  tone = "neutral",
}: {
  children: React.ReactNode;
  icon?: React.ReactNode;
  tone?: "neutral" | "ok" | "warn";
}) {
  const cls =
    tone === "ok"
      ? "bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300"
      : tone === "warn"
        ? "bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300"
        : "bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300";
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-medium ${cls}`}
    >
      {icon}
      {children}
    </span>
  );
}
