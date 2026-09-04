import type { DecisionStatus } from "@/lib/types";
import { STATUS_META, cn } from "@/lib/utils";

const FALLBACK_META = { label: "Unknown", className: "bg-zinc-500/15 text-zinc-600 dark:text-zinc-400 ring-zinc-500/30" };

export function StatusPill({
  status,
  className,
}: {
  status: DecisionStatus;
  className?: string;
}) {
  const meta = STATUS_META[status] ?? FALLBACK_META;
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset",
        meta.className,
        className,
      )}
    >
      {meta.label}
    </span>
  );
}
