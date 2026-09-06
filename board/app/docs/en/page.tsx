import fs from "node:fs";
import path from "node:path";
import type { Metadata } from "next";
import Link from "next/link";

import { ManualDoc } from "@/components/manual-doc";

export const metadata: Metadata = {
  title: "EverLink · Operations Manual (EN)",
};

/**
 * The English operations manual, served from the committed markdown in
 * board/content/. STATIC: the file is read at build time (no DB, no runtime
 * fs), so it renders on Vercel with nothing configured.
 */
export default function DocsEnPage() {
  const source = fs.readFileSync(
    path.join(process.cwd(), "content", "manual.en.md"),
    "utf-8",
  );
  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-3 border-b border-zinc-200 pb-4 dark:border-zinc-800">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-100">
            Deployment, Configuration &amp; Operations Manual
          </h1>
          <p className="mt-1 text-sm text-zinc-500 dark:text-zinc-400">
            English · deploy / configure / operate / avoid the traps
          </p>
        </div>
        <Link
          href="/docs"
          className="text-sm font-medium text-sky-600 hover:underline dark:text-sky-400"
        >
          中文版 →
        </Link>
      </header>
      <ManualDoc source={source} />
    </div>
  );
}
