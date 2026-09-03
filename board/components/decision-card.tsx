import Link from "next/link";
import { ArrowUpRight, Layers } from "lucide-react";

import type { Decision } from "@/lib/types";
import { ACTION_LABEL, cn, relativeTime } from "@/lib/utils";
import { RiskBadge } from "./risk-badge";
import { StatusPill } from "./status-pill";

/**
 * Presentational summary of one decision card. Server-safe (no hooks/handlers) so
 * it can be rendered directly by a Server Component or embedded in a client list.
 */
export function DecisionCard({
  decision,
  className,
}: {
  decision: Decision;
  className?: string;
}) {
  const { proposal } = decision;
  const slots = decision.affected_slot_ids.length;
  return (
    <div
      className={cn(
        "rounded-xl border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900",
        className,
      )}
    >
      <div className="flex flex-wrap items-center gap-2">
        <StatusPill status={decision.status} />
        <RiskBadge risk={proposal.risk_level} />
        <span className="text-sm font-medium text-zinc-900 dark:text-zinc-100">
          {ACTION_LABEL[proposal.action] ?? proposal.action}
        </span>
        <span className="ml-auto text-xs text-zinc-400 dark:text-zinc-500">
          {relativeTime(decision.created_at)}
        </span>
      </div>

      {proposal.rationale ? (
        <p className="mt-2 line-clamp-3 text-sm text-zinc-600 dark:text-zinc-400">
          {proposal.rationale}
        </p>
      ) : null}

      {proposal.new_url ? (
        <p className="mt-2 truncate font-mono text-xs text-sky-700 dark:text-sky-400">
          → {proposal.new_url}
        </p>
      ) : null}

      <div className="mt-3 flex items-center gap-3 text-xs text-zinc-500 dark:text-zinc-400">
        <span className="inline-flex items-center gap-1">
          <Layers className="h-3.5 w-3.5" />
          {slots} slot{slots === 1 ? "" : "s"}
        </span>
        <Link
          href={`/decision/${decision.id}`}
          className="ml-auto inline-flex items-center gap-1 font-medium text-sky-600 hover:underline dark:text-sky-400"
        >
          Evidence
          <ArrowUpRight className="h-3.5 w-3.5" />
        </Link>
      </div>
    </div>
  );
}
