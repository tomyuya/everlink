import { HeartPulse, Inbox as InboxIcon, ListChecks, Timer } from "lucide-react";

/**
 * The four-tile operational pulse: what awaits the human, what the agent
 * healed/decided in the last 30 days, and when it last acted. Lives at the very
 * top of the inbox body (above the Decision inbox module) as the dashboard KPI
 * row for the working queue — deliberately NOT on the home page, which stays a
 * public showcase.
 */
export function PulseStrip({
  pending,
  healed,
  decided,
  lastActivity,
}: {
  pending: number;
  healed: number;
  decided: number;
  lastActivity: string;
}) {
  const tiles = [
    { icon: <InboxIcon className="h-4 w-4" />, label: "Awaiting you", value: String(pending), accent: "text-amber-600 dark:text-amber-400" },
    { icon: <HeartPulse className="h-4 w-4" />, label: "Links healed · 30d", value: String(healed), accent: "text-emerald-600 dark:text-emerald-400" },
    { icon: <ListChecks className="h-4 w-4" />, label: "Decisions decided · 30d", value: String(decided), accent: "text-sky-600 dark:text-sky-400" },
    { icon: <Timer className="h-4 w-4" />, label: "Last activity", value: lastActivity || "—", accent: "text-zinc-600 dark:text-zinc-300" },
  ];
  return (
    <section aria-label="Pipeline health" className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
      {tiles.map(({ icon, label, value, accent }) => (
        <div
          key={label}
          className="rounded-xl border border-zinc-200 bg-white p-3 dark:border-zinc-800 dark:bg-zinc-900"
        >
          <div className={`flex items-center gap-1.5 text-xs ${accent}`}>
            {icon}
            <span className="font-medium">{label}</span>
          </div>
          <p className="mt-1.5 text-xl font-semibold tabular-nums text-zinc-900 dark:text-zinc-100">
            {value}
          </p>
        </div>
      ))}
    </section>
  );
}
