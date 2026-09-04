"use client";

import { useState } from "react";
import { ChevronDown, ChevronUp } from "lucide-react";

/** Lines of pretty-printed JSON shown before the expander kicks in. */
const CLAMP_LINES = 6;

/** Pretty-print a JSON payload column, falling back to the raw string. */
function pretty(payload: string | null): string {
  if (!payload) return "";
  try {
    return JSON.stringify(JSON.parse(payload), null, 2);
  } catch {
    return payload;
  }
}

/**
 * Audit payload cell. A long pretty-printed payload (e.g. a notify event listing
 * dozens of channels) would otherwise stretch one table row to dozens of lines and
 * wreck the trail's scanability. Show the first CLAMP_LINES lines with an explicit
 * "N more lines" expander: nothing is silently hidden — the full payload is one
 * click away, which keeps an audit log honest AND readable.
 */
export function AuditPayload({ payload }: { payload: string | null }) {
  const [open, setOpen] = useState(false);
  const text = pretty(payload);
  if (!text) {
    return <span className="text-xs text-zinc-400 dark:text-zinc-600">—</span>;
  }

  const lines = text.split("\n");
  const clamped = lines.length > CLAMP_LINES;
  const shown = open ? lines : lines.slice(0, CLAMP_LINES);
  const hidden = lines.length - CLAMP_LINES;

  return (
    <div className="max-w-xl">
      <pre className="overflow-x-auto whitespace-pre-wrap break-words font-mono text-[11px] leading-relaxed text-zinc-500 dark:text-zinc-400">
        {shown.join("\n")}
        {clamped && !open ? "\n…" : ""}
      </pre>
      {clamped ? (
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          className="mt-1 inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[11px] font-medium text-sky-600 transition-colors hover:bg-sky-50 dark:text-sky-400 dark:hover:bg-sky-950/40"
        >
          {open ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
          {open ? "Collapse" : `Expand ${hidden} more line${hidden === 1 ? "" : "s"}`}
        </button>
      ) : null}
    </div>
  );
}
