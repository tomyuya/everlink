import type { DecisionStatus } from "@/lib/types";
import { STATUS_META, cn } from "@/lib/utils";

export function StatusPill({
  status,
  className,
}: {
  status: DecisionStatus;
  className?: string;
}) {
  const meta = STATUS_META[status];
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
