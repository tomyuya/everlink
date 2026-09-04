"use client";

import { useState } from "react";
import { Check, Copy } from "lucide-react";

/**
 * Tiny copy-to-clipboard affordance for the read-only command snippets in the
 * Automation panel. Client-only because it touches navigator.clipboard; degrades
 * to a no-op (icon stays a Copy) when the clipboard API is unavailable.
 */
export function CopyButton({ text }: { text: string }) {
  const [done, setDone] = useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
      setDone(true);
      window.setTimeout(() => setDone(false), 1500);
    } catch {
      /* clipboard blocked (insecure context / permissions) — stay silent */
    }
  }

  return (
    <button
      type="button"
      onClick={copy}
      aria-label="Copy command"
      title="Copy command"
      className="inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-zinc-400 transition-colors hover:bg-zinc-700/60 hover:text-zinc-100"
    >
      {done ? <Check className="h-3.5 w-3.5 text-emerald-400" /> : <Copy className="h-3.5 w-3.5" />}
    </button>
  );
}
