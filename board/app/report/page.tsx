import type { Metadata } from "next";
import type { ReactNode } from "react";
import { BarChart3, HeartPulse, Layers, ListChecks, Gavel } from "lucide-react";

import { EmptyState } from "@/components/empty-state";
import { weeklyStats } from "@/lib/queries";
import type { WeeklyStats } from "@/lib/types";
import { ACTION_LABEL, STATUS_META, formatDateTime } from "@/lib/utils";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "Report · EverLink Board",
};

export default async function ReportPage({
  searchParams,
}: {
  searchParams: Promise<{ days?: string }>;
}) {
  const sp = await searchParams;
  const days = clampDays(Number(sp.days ?? 7));

  let stats: WeeklyStats | null = null;
  let dbError: string | null = null;
  try {
    stats = await weeklyStats(days);
  } catch (e) {
    dbError = e instanceof Error ? e.message : "Failed to compute report";
  }

  const empty =
    stats &&
    stats.decisions_created === 0 &&
    stats.links_healed === 0 &&
    Object.keys(stats.audit_events).length === 0;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <h1 className="text-xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-100">
            Weekly report
          </h1>
          <p className="mt-1 text-sm text-zinc-500 dark:text-zinc-400">
            Live aggregate over the last {days} day{days === 1 ? "" : "s"} — the same
            numbers the agent’s scheduled digest reports.
          </p>
        </div>
        <div className="flex items-center gap-1">
          {[7, 14, 30].map((d) => (
            <a
              key={d}
              href={`/report?days=${d}`}
              className={
                d === days
                  ? "rounded-full bg-zinc-900 px-3 py-1 text-xs font-medium text-white dark:bg-zinc-100 dark:text-zinc-900"
                  : "rounded-full px-3 py-1 text-xs font-medium text-zinc-500 ring-1 ring-inset ring-zinc-200 hover:bg-zinc-50 dark:text-zinc-400 dark:ring-zinc-800 dark:hover:bg-zinc-900"
              }
            >
              {d}d
            </a>
          ))}
        </div>
      </div>

      {dbError ? (
        <EmptyState
          title="Database unavailable"
          hint={dbError}
          icon={<BarChart3 className="h-8 w-8" />}
        />
      ) : !stats || empty ? (
        <EmptyState
          title="Nothing to report yet"
          hint="Once EverLink runs scans and the queue sees decisions, this page fills in automatically."
          icon={<BarChart3 className="h-8 w-8" />}
        />
      ) : (
        <ReportBody stats={stats} />
      )}
    </div>
  );
}

function ReportBody({ stats }: { stats: WeeklyStats }) {
  return (
    <div className="space-y-6">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Stat
          icon={<HeartPulse className="h-4 w-4" />}
          label="Links healed"
          value={stats.links_healed}
          accent="text-emerald-600 dark:text-emerald-400"
        />
        <Stat
          icon={<Layers className="h-4 w-4" />}
          label="Slots fixed"
          value={stats.slots_affected_by_applied}
          accent="text-sky-600 dark:text-sky-400"
        />
        <Stat
          icon={<ListChecks className="h-4 w-4" />}
          label="Decisions created"
          value={stats.decisions_created}
          accent="text-zinc-700 dark:text-zinc-300"
        />
        <Stat
          icon={<Gavel className="h-4 w-4" />}
          label="Decisions decided"
          value={stats.decisions_decided}
          accent="text-zinc-700 dark:text-zinc-300"
        />
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <Panel title="Decisions by status">
          <Breakdown
            rows={Object.entries(stats.by_status)}
            total={Object.values(stats.by_status).reduce((a, b) => a + b, 0)}
            labelFor={(k) => STATUS_META[k as keyof typeof STATUS_META]?.label ?? k}
          />
        </Panel>
        <Panel title="Decisions by action">
          <Breakdown
            rows={Object.entries(stats.by_action)}
            total={Object.values(stats.by_action).reduce((a, b) => a + b, 0)}
            labelFor={(k) => ACTION_LABEL[k as keyof typeof ACTION_LABEL] ?? k}
          />
        </Panel>
      </div>

      <Panel title="Audit events">
        <Breakdown
          rows={Object.entries(stats.audit_events)}
          total={Object.values(stats.audit_events).reduce((a, b) => a + b, 0)}
          labelFor={(k) => k}
        />
      </Panel>

      <p className="text-xs text-zinc-400 dark:text-zinc-500">
        Generated {formatDateTime(stats.generated_at)} · window {stats.window_days}d
      </p>
    </div>
  );
}

function Stat({
  icon,
  label,
  value,
  accent,
}: {
  icon: ReactNode;
  label: string;
  value: number;
  accent: string;
}) {
  return (
    <div className="rounded-xl border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900">
      <div className={`flex items-center gap-1.5 text-xs ${accent}`}>
        {icon}
        <span className="font-medium">{label}</span>
      </div>
      <p className="mt-2 text-2xl font-semibold tabular-nums text-zinc-900 dark:text-zinc-100">
        {value}
      </p>
    </div>
  );
}

function Panel({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="rounded-xl border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900">
      <h2 className="text-sm font-semibold text-zinc-700 dark:text-zinc-300">{title}</h2>
      <div className="mt-3">{children}</div>
    </section>
  );
}

function Breakdown({
  rows,
  total,
  labelFor,
}: {
  rows: [string, number][];
  total: number;
  labelFor: (key: string) => string;
}) {
  if (!rows.length) {
    return <p className="text-xs text-zinc-400 dark:text-zinc-500">No data in window.</p>;
  }
  const sorted = [...rows].sort((a, b) => b[1] - a[1]);
  return (
    <ul className="space-y-2">
      {sorted.map(([key, n]) => {
        const pct = total > 0 ? Math.round((n / total) * 100) : 0;
        return (
          <li key={key} className="text-xs">
            <div className="flex items-center justify-between text-zinc-600 dark:text-zinc-400">
              <span className="font-medium">{labelFor(key)}</span>
              <span className="tabular-nums">
                {n} · {pct}%
              </span>
            </div>
            <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-zinc-100 dark:bg-zinc-800">
              <div
                className="h-full rounded-full bg-sky-500/80"
                style={{ width: `${pct}%` }}
              />
            </div>
          </li>
        );
      })}
    </ul>
  );
}

function clampDays(n: number): number {
  if (Number.isNaN(n)) return 7;
  return Math.min(90, Math.max(1, Math.round(n)));
}
