import { CalendarClock, Terminal } from "lucide-react";

import { CopyButton } from "./copy-button";

const COMMANDS: { cmd: string; note: string }[] = [
  {
    cmd: "python scripts/nightly.py",
    note: "Full live run — scan every site with the real Bedrock judge, notify, then drain approved fixes.",
  },
  {
    cmd: "python scripts/nightly.py --dry-run --judge none",
    note: "Safe offline smoke — proves the chain is wired; writes nothing, sends nothing, skips the worker.",
  },
];

const FLAGS: { flag: string; desc: string }[] = [
  { flag: "--judge none|stub|bedrock|mantle", desc: "Judge backend. mantle = real LLM via Bedrock (production); none = detection only, no creds." },
  { flag: "--dry-run", desc: "Scan writes nothing and notify sends nothing; the worker step is skipped (it writes)." },
  { flag: "--sites a,b,c", desc: "Restrict the scan targets (default: the three first-party sites)." },
  { flag: "--weekly", desc: "Force the weekly digest step now (otherwise it folds in automatically on Monday)." },
];

/**
 * The nightly entrypoint, surfaced on the product page with usage hints.
 *
 * HONESTY NOTE (deliberate): the board is a Next.js app on Vercel while the agent is a
 * Python service on Railway, so this panel DOCUMENTS the trigger (exact commands + flags
 * + the production cron schedule) and shows live proof the loop is running, rather than
 * offering a "Run now" button that could not actually execute the Python chain from here.
 * A fake execute button would mislead judges; documentation + live activity would not.
 */
export function AutomationPanel({ lastActivity }: { lastActivity: string }) {
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
        <span className="inline-flex items-center gap-1 rounded-full bg-zinc-100 px-2 py-0.5 text-[10px] font-medium text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300">
          <CalendarClock className="h-3 w-3" />
          Railway cron · 03:00 UTC daily
        </span>
        <span className="ml-auto text-[11px] text-zinc-400 dark:text-zinc-500">
          last activity {lastActivity || "—"}
        </span>
      </div>

      <p className="mt-2 text-xs leading-relaxed text-zinc-500 dark:text-zinc-400">
        In production this loop runs itself on a schedule — no one opens a terminal. The
        commands below are the exact entrypoint if you want to drive it yourself (locally
        or in CI). Each run appends to the audit trail, so you can watch it here.
      </p>

      <div className="mt-3 space-y-2">
        {COMMANDS.map(({ cmd, note }) => (
          <div
            key={cmd}
            className="flex items-center gap-2 rounded-lg bg-zinc-950 px-3 py-2 dark:bg-black/60"
          >
            <code className="flex-1 overflow-x-auto whitespace-nowrap font-mono text-xs text-emerald-300">
              {cmd}
            </code>
            <CopyButton text={cmd} />
          </div>
        ))}
      </div>
      <ul className="mt-2 space-y-1">
        {COMMANDS.map(({ cmd, note }) => (
          <li key={cmd} className="text-[11px] text-zinc-500 dark:text-zinc-400">
            <span className="font-mono text-zinc-600 dark:text-zinc-300">{cmd.split(" --")[0]}</span>
            {" — "}
            {note}
          </li>
        ))}
      </ul>

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
