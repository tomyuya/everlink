"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Check, X } from "lucide-react";

import type { DecisionStatus } from "@/lib/types";

/**
 * Single-card approve/reject on the detail page. Mirrors the inbox batch action but
 * PATCHes /api/decisions/[id]. Only a `pending` card can be decided; anything else
 * is already settled and we say so honestly instead of showing dead buttons.
 */
export function DecisionActions({
  id,
  status,
  readonly = false,
}: {
  id: string;
  status: DecisionStatus;
  readonly?: boolean;
}) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function decide(action: "approve" | "reject") {
    if (busy) return;
    const reason =
      action === "reject" ? (window.prompt("Reject reason (optional):") ?? "") : "";
    setBusy(true);
    setError(null);
    try {
      const res = await fetch(`/api/decisions/${id}`, {
        method: "PATCH",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ action, reason }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data?.error || `Request failed (${res.status})`);
      router.refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Something went wrong");
    } finally {
      setBusy(false);
    }
  }

  if (status !== "pending") {
    return (
      <p className="text-sm text-zinc-500 dark:text-zinc-400">
        This card is already{" "}
        <span className="font-medium text-zinc-700 dark:text-zinc-300">{status}</span>.
      </p>
    );
  }

  if (readonly) {
    return (
      <p className="text-sm text-zinc-500 dark:text-zinc-400">
        Read-only view — decisions are disabled on this deployment.
      </p>
    );
  }

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          onClick={() => decide("approve")}
          disabled={busy}
          className="inline-flex items-center gap-1.5 rounded-md bg-emerald-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-emerald-500 disabled:cursor-not-allowed disabled:opacity-40"
        >
          <Check className="h-4 w-4" />
          Approve
        </button>
        <button
          type="button"
          onClick={() => decide("reject")}
          disabled={busy}
          className="inline-flex items-center gap-1.5 rounded-md bg-rose-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-rose-500 disabled:cursor-not-allowed disabled:opacity-40"
        >
          <X className="h-4 w-4" />
          Reject
        </button>
      </div>
      {error ? (
        <p className="text-sm text-rose-600 dark:text-rose-400">{error}</p>
      ) : null}
    </div>
  );
}
