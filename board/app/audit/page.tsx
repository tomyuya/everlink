import type { Metadata } from "next";
import { ScrollText } from "lucide-react";

import { AuditTable } from "@/components/audit-table";
import { EmptyState } from "@/components/empty-state";
import { listAudit } from "@/lib/queries";
import type { AuditRow } from "@/lib/types";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "Audit · EverLink Board",
};

export default async function AuditPage({
  searchParams,
}: {
  searchParams: Promise<{ event?: string }>;
}) {
  const { event } = await searchParams;
  const filter = event && /^[a-z_]{3,40}$/.test(event) ? event : undefined;
  let rows: AuditRow[] = [];
  let dbError: string | null = null;
  try {
    rows = await listAudit(300, filter);
  } catch (e) {
    dbError = e instanceof Error ? e.message : "Failed to load audit log";
  }

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-100">
          Audit trail
        </h1>
        <p className="mt-1 text-sm text-zinc-500 dark:text-zinc-400">
          Append-only record of every detection, interruption, decision, and apply —
          written by the agent, the board, and the worker. Nothing is ever rewritten.
        </p>
        {filter ? (
          <p className="mt-2 text-xs text-zinc-500 dark:text-zinc-400">
            Filtering event = <code className="font-mono">{filter}</code> ·{" "}
            {rows.length} row(s) ·{" "}
            <a href="/audit" className="underline decoration-zinc-300 underline-offset-2 hover:text-zinc-700 dark:decoration-zinc-700 dark:hover:text-zinc-300">
              clear filter
            </a>
          </p>
        ) : null}
      </div>

      {dbError ? (
        <EmptyState
          title="Database unavailable"
          hint={dbError}
          icon={<ScrollText className="h-8 w-8" />}
        />
      ) : rows.length === 0 ? (
        <EmptyState
          title="No audit events yet"
          hint="Events appear as soon as the nightly loop runs. See the Automation panel on the home page for the exact entrypoint and what each run records."
          icon={<ScrollText className="h-8 w-8" />}
        />
      ) : (
        <AuditTable rows={rows} />
      )}
    </div>
  );
}
