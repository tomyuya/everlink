"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Check, Inbox as InboxIcon, X } from "lucide-react";

import type { Decision, DecisionStatus, StatusCounts } from "@/lib/types";
import { cn } from "@/lib/utils";
import { DecisionCard } from "./decision-card";
import { EmptyState } from "./empty-state";

const FILTERS: { key: DecisionStatus | "all"; label: string }[] = [
  { key: "pending", label: "Pending" },
  { key: "approved", label: "Approved" },
  { key: "applied", label: "Applied" },
  { key: "rejected", label: "Rejected" },
  { key: "all", label: "All" },
];

/**
 * The inbox: a filterable list of decision cards with multi-select + batch
 * approve/reject. Reads are server-rendered (props); the only mutation is a POST
 * to /api/decisions, after which we `router.refresh()` to re-pull server state.
 */
export function InboxClient({
  decisions,
  counts,
  status,
  readonly = false,
}: {
  decisions: Decision[];
  counts: StatusCounts;
  status: DecisionStatus | "all";
  readonly?: boolean;
}) {
  const router = useRouter();
  const [selected, setSelected] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const selectedSet = useMemo(() => new Set(selected), [selected]);
  const allSelected = decisions.length > 0 && selected.length === decisions.length;

  function toggle(id: string) {
    setSelected((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id],
    );
  }

  function toggleAll() {
    setSelected(allSelected ? [] : decisions.map((d) => d.id));
  }

  async function decide(action: "approve" | "reject") {
    if (!selected.length || busy) return;
    const reason =
      action === "reject" ? (window.prompt("Reject reason (optional):") ?? "") : "";
    setBusy(true);
    setError(null);
    try {
      const res = await fetch("/api/decisions", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ ids: selected, action, reason }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data?.error || `Request failed (${res.status})`);
      setSelected([]);
      router.refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Something went wrong");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-4">
      {/* filter tabs */}
      <div className="flex flex-wrap items-center gap-1">
        {FILTERS.map(({ key, label }) => {
          const active = key === status;
          const n = key === "all" ? sum(counts) : (counts[key] ?? 0);
          const href = key === "pending" ? "/" : `/?status=${key}`;
          return (
            <Link
              key={key}
              href={href}
              className={cn(
                "inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-medium ring-1 ring-inset transition-colors",
                active
                  ? "bg-zinc-900 text-white ring-zinc-900 dark:bg-zinc-100 dark:text-zinc-900 dark:ring-zinc-100"
                  : "bg-white text-zinc-600 ring-zinc-200 hover:bg-zinc-50 dark:bg-zinc-900 dark:text-zinc-400 dark:ring-zinc-800 dark:hover:bg-zinc-800",
              )}
            >
              {label}
              <span className={cn("tabular-nums", active ? "opacity-70" : "opacity-60")}>
                {n}
              </span>
            </Link>
          );
        })}
      </div>

      {/* batch bar */}
      {!readonly && decisions.length > 0 ? (
        <div className="flex flex-wrap items-center gap-2 rounded-lg border border-zinc-200 bg-white px-3 py-2 dark:border-zinc-800 dark:bg-zinc-900">
          <label className="inline-flex cursor-pointer items-center gap-2 text-xs text-zinc-600 dark:text-zinc-400">
            <input
              type="checkbox"
              checked={allSelected}
              onChange={toggleAll}
              className="h-3.5 w-3.5 rounded border-zinc-300 accent-sky-600 dark:border-zinc-700"
            />
            Select all
          </label>
          <span className="text-xs text-zinc-400">
            {selected.length} selected
          </span>
          <div className="ml-auto flex items-center gap-2">
            <button
              type="button"
              onClick={() => decide("approve")}
              disabled={busy || !selected.length}
              className="inline-flex items-center gap-1 rounded-md bg-emerald-600 px-3 py-1.5 text-xs font-medium text-white transition-colors hover:bg-emerald-500 disabled:cursor-not-allowed disabled:opacity-40"
            >
              <Check className="h-3.5 w-3.5" />
              Approve
            </button>
            <button
              type="button"
              onClick={() => decide("reject")}
              disabled={busy || !selected.length}
              className="inline-flex items-center gap-1 rounded-md bg-rose-600 px-3 py-1.5 text-xs font-medium text-white transition-colors hover:bg-rose-500 disabled:cursor-not-allowed disabled:opacity-40"
            >
              <X className="h-3.5 w-3.5" />
              Reject
            </button>
          </div>
        </div>
      ) : null}

      {readonly ? (
        <p className="rounded-lg border border-zinc-200 bg-zinc-50 px-3 py-2 text-xs text-zinc-500 dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-400">
          Read-only view — decisions are disabled on this deployment.
        </p>
      ) : null}

      {error ? (
        <p className="rounded-lg border border-rose-300 bg-rose-50 px-3 py-2 text-xs text-rose-700 dark:border-rose-800 dark:bg-rose-950/40 dark:text-rose-300">
          {error}
        </p>
      ) : null}

      {/* list */}
      {decisions.length === 0 ? (
        <EmptyState
          title={`No ${status === "all" ? "" : status} decisions`}
          hint="EverLink only surfaces a card when a fix genuinely needs a human. An empty inbox is the goal."
          icon={<InboxIcon className="h-8 w-8" />}
        />
      ) : (
        <ul className="space-y-3">
          {decisions.map((d) => (
            <li key={d.id} className="flex items-start gap-3">
              {!readonly ? (
                <input
                  type="checkbox"
                  aria-label={`Select decision ${d.id}`}
                  checked={selectedSet.has(d.id)}
                  onChange={() => toggle(d.id)}
                  className="mt-5 h-4 w-4 shrink-0 rounded border-zinc-300 accent-sky-600 dark:border-zinc-700"
                />
              ) : null}
              <DecisionCard decision={d} className="flex-1" />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function sum(counts: StatusCounts): number {
  return Object.values(counts).reduce((a, b) => a + Number(b || 0), 0);
}
