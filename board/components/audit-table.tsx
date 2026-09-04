import type { AuditRow } from "@/lib/types";
import { formatDateTime } from "@/lib/utils";
import { AuditPayload } from "./audit-payload";

/** Append-only audit trail (spec §5 `audit_log`) — who did what, when. */
export function AuditTable({ rows }: { rows: AuditRow[] }) {
  if (!rows.length) return null;
  return (
    <div className="overflow-x-auto rounded-xl border border-zinc-200 dark:border-zinc-800">
      <table className="min-w-full divide-y divide-zinc-200 text-sm dark:divide-zinc-800">
        <thead className="bg-zinc-50 text-left text-xs uppercase tracking-wide text-zinc-500 dark:bg-zinc-900 dark:text-zinc-400">
          <tr>
            <th className="px-3 py-2 font-medium">Time</th>
            <th className="px-3 py-2 font-medium">Agent</th>
            <th className="px-3 py-2 font-medium">Event</th>
            <th className="px-3 py-2 font-medium">Payload</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-zinc-100 bg-white dark:divide-zinc-800/60 dark:bg-zinc-950">
          {rows.map((r) => (
            <tr key={r.id} className="align-top">
              <td className="whitespace-nowrap px-3 py-2 text-xs text-zinc-500 dark:text-zinc-400">
                {formatDateTime(r.ts)}
              </td>
              <td className="whitespace-nowrap px-3 py-2 text-xs font-medium text-zinc-700 dark:text-zinc-300">
                {r.agent}
              </td>
              <td className="whitespace-nowrap px-3 py-2">
                <code className="rounded bg-zinc-100 px-1.5 py-0.5 text-[11px] text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300">
                  {r.event}
                </code>
              </td>
              <td className="px-3 py-2">
                <AuditPayload payload={r.payload} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
