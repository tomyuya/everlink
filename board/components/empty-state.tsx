import type { ReactNode } from "react";

export function EmptyState({
  title,
  hint,
  icon,
}: {
  title: string;
  hint?: string;
  icon?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-zinc-300 py-16 text-center dark:border-zinc-700">
      {icon ? <div className="mb-3 text-zinc-400">{icon}</div> : null}
      <p className="text-sm font-medium text-zinc-700 dark:text-zinc-300">{title}</p>
      {hint ? (
        <p className="mt-1 max-w-sm text-xs text-zinc-500 dark:text-zinc-400">{hint}</p>
      ) : null}
    </div>
  );
}
