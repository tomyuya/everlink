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

export default async function AuditPage() {
  let rows: AuditRow[] = [];
  let dbError: string | null = null;
  try {
    rows = await listAudit(300);
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
          hint="Run a scan (python -m everlink.cli scan) and events will appear here."
          icon={<ScrollText className="h-8 w-8" />}
        />
      ) : (
        <AuditTable rows={rows} />
      )}
    </div>
  );
}
