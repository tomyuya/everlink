import type { Metadata } from "next";
import { Inbox as InboxIcon } from "lucide-react";

import { EmptyState } from "@/components/empty-state";
import { InboxClient } from "@/components/inbox-client";
import { isReadonly } from "@/lib/db";
import { listDecisions, statusCounts } from "@/lib/queries";
import type { Decision, DecisionStatus, StatusCounts } from "@/lib/types";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "Inbox · EverLink Board",
};

const VALID = new Set(["pending", "approved", "applied", "rejected", "expired", "all"]);

export default async function InboxPage({
  searchParams,
}: {
  searchParams: Promise<{ status?: string }>;
}) {
  const sp = await searchParams;
  const raw = sp.status ?? "pending";
  const status = (VALID.has(raw) ? raw : "pending") as DecisionStatus | "all";

  let decisions: Decision[] = [];
  let counts: StatusCounts = {};
  let dbError: string | null = null;
  try {
    [decisions, counts] = await Promise.all([
      listDecisions(status, 200),
      statusCounts(),
    ]);
  } catch (e) {
    dbError = e instanceof Error ? e.message : "Failed to load decisions";
  }

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-100">
          Decision inbox
        </h1>
        <p className="mt-1 text-sm text-zinc-500 dark:text-zinc-400">
          EverLink detects and fixes link rot on its own. It only stops here when a fix
          is risky enough to need a human. Approve, reject, or batch the low-risk ones.
        </p>
      </div>

      {dbError ? (
        <EmptyState
          title="Database unavailable"
          hint={dbError}
          icon={<InboxIcon className="h-8 w-8" />}
        />
      ) : (
        <InboxClient
          decisions={decisions}
          counts={counts}
          status={status}
          readonly={isReadonly()}
        />
      )}
    </div>
  );
}
