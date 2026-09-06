import type { Metadata } from "next";
import { Inbox as InboxIcon } from "lucide-react";

import { EmptyState } from "@/components/empty-state";
import { InboxClient } from "@/components/inbox-client";
import { PulseStrip } from "@/components/pulse-strip";
import { isReadonly } from "@/lib/db";
import { listAudit, listDecisions, statusCounts, weeklyStats } from "@/lib/queries";
import { relativeTime } from "@/lib/utils";
import type { Decision, DecisionStatus, StatusCounts } from "@/lib/types";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "Inbox · EverLink Board",
};

const VALID = new Set(["pending", "approved", "applied", "rejected", "expired", "all"]);

/**
 * The working queue: the one place EverLink stops for a human. Kept on its own
 * route (/inbox) so the home page (/) stays a clean product narrative while this
 * page is purely the approve/reject surface.
 */
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
  let healed = 0;
  let decided = 0;
  let lastActivity = "";
  let dbError: string | null = null;
  try {
    const [d, c, stats, audit] = await Promise.all([
      listDecisions(status, 200),
      statusCounts(),
      weeklyStats(30),
      listAudit(1),
    ]);
    decisions = d;
    counts = c;
    healed = stats.links_healed;
    decided = stats.decisions_decided;
    lastActivity = relativeTime(audit[0]?.ts);
  } catch (e) {
    dbError = e instanceof Error ? e.message : "Failed to load decisions";
  }

  return (
    <div className="space-y-5">
      {/* Operational KPI row first: what awaits you, what the agent already
          settled, and when it last acted — before diving into the queue. */}
      {!dbError ? (
        <PulseStrip
          pending={counts.pending ?? 0}
          healed={healed}
          decided={decided}
          lastActivity={lastActivity}
        />
      ) : null}

      <div>
        <h1 className="text-xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-100">
          Decision inbox
        </h1>
        <p className="mt-1 text-sm text-zinc-500 dark:text-zinc-400">
          The one place EverLink stops for a human. Approve, reject, or batch the
          low-risk fixes it surfaced.
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
