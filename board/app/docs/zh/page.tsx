import fs from "node:fs";
import path from "node:path";
import type { Metadata } from "next";
import Link from "next/link";

import { ManualDoc } from "@/components/manual-doc";

export const metadata: Metadata = {
  title: "EverLink · 部署配置与使用操作手册（中文）",
};

/**
 * The Chinese operations manual, served from the committed markdown in
 * board/content/. STATIC: the file is read at build time (no DB, no runtime
 * fs), so it renders on Vercel with nothing configured. English (the default)
 * lives at /docs.
 */
export default function DocsZhPage() {
  const source = fs.readFileSync(
    path.join(process.cwd(), "content", "manual.zh.md"),
    "utf-8",
  );
  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-3 border-b border-zinc-200 pb-4 dark:border-zinc-800">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-100">
            部署配置与使用操作手册
          </h1>
          <p className="mt-1 text-sm text-zinc-500 dark:text-zinc-400">
            中文 · 部署 / 配置 / 使用 / 避坑 全量参考
          </p>
        </div>
        <Link
          href="/docs"
          className="text-sm font-medium text-sky-600 hover:underline dark:text-sky-400"
        >
          English version →
        </Link>
      </header>
      <ManualDoc source={source} />
    </div>
  );
}
