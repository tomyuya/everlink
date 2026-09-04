import type { ReactNode } from "react";
import Link from "next/link";
import {
  Activity,
  ArrowRight,
  BarChart3,
  Inbox,
  Radar,
  Sparkles,
  Wrench,
} from "lucide-react";

import { cn } from "@/lib/utils";

interface Stage {
  icon: ReactNode;
  title: string;
  desc: string;
  /** Where this stage is visible on the board (makes the tabs one loop, not fragments). */
  href?: string;
  hrefLabel?: string;
  /** The human-in-the-loop step — the reason this board exists. */
  highlight?: boolean;
}

const STAGES: Stage[] = [
  {
    icon: <Radar className="h-4 w-4" />,
    title: "Scan",
    desc: "Crawl first-party pages and inventory every outbound link slot.",
  },
  {
    icon: <Activity className="h-4 w-4" />,
    title: "Detect",
    desc: "Probe HTTP status + redirect chain (L1), then selectively fetch & read the page (L2).",
  },
  {
    icon: <Sparkles className="h-4 w-4" />,
    title: "Judge",
    desc: "A Strands agent on AWS Bedrock proposes the safest fix and scores its risk.",
  },
  {
    icon: <Inbox className="h-4 w-4" />,
    title: "You decide",
    desc: "Only fixes risky enough to need a human land here as cards. Approve or reject.",
    href: "/",
    hrefLabel: "Inbox",
    highlight: true,
  },
  {
    icon: <Wrench className="h-4 w-4" />,
    title: "Apply",
    desc: "The worker snapshots, writes the approved fix, then verifies it took.",
  },
  {
    icon: <BarChart3 className="h-4 w-4" />,
    title: "Report",
    desc: "Every step is appended to the audit trail and folded into the weekly digest.",
    href: "/report",
    hrefLabel: "Report",
  },
];

/**
 * The whole product in one glance: EverLink's autonomous loop, with the single
 * human step highlighted. Rendered on the landing page so a first-time visitor
 * (or a judge) immediately sees what the product does and where the board fits.
 * Server-safe (no hooks); each stage optionally deep-links to the tab that shows it.
 */
export function Pipeline() {
  return (
    <section aria-label="How EverLink works">
      <div className="flex items-baseline justify-between gap-2">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
          How it works · one autonomous loop
        </h2>
        <Link
          href="/audit"
          className="text-xs font-medium text-sky-600 hover:underline dark:text-sky-400"
        >
          Audit trail
        </Link>
      </div>

      <ol className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-6">
        {STAGES.map((s, i) => (
          <li key={s.title} className="relative">
            <div
              className={cn(
                "flex h-full flex-col gap-1.5 rounded-xl border p-3",
                s.highlight
                  ? "border-sky-300 bg-sky-50 ring-1 ring-sky-200 dark:border-sky-800 dark:bg-sky-950/40 dark:ring-sky-900"
                  : "border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-900",
              )}
            >
              <div
                className={cn(
                  "flex items-center gap-1.5 text-xs font-semibold",
                  s.highlight
                    ? "text-sky-700 dark:text-sky-300"
                    : "text-zinc-700 dark:text-zinc-300",
                )}
              >
                <span
                  className={cn(
                    "inline-flex h-5 w-5 items-center justify-center rounded-md",
                    s.highlight
                      ? "bg-sky-600 text-white"
                      : "bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300",
                  )}
                >
                  {s.icon}
                </span>
                {s.title}
              </div>
              <p className="text-[11px] leading-relaxed text-zinc-500 dark:text-zinc-400">
                {s.desc}
              </p>
              {s.href ? (
                <Link
                  href={s.href}
                  className="mt-auto text-[11px] font-medium text-sky-600 hover:underline dark:text-sky-400"
                >
                  Open {s.hrefLabel} →
                </Link>
              ) : null}
            </div>
            {i < STAGES.length - 1 ? (
              <ArrowRight
                aria-hidden
                className="pointer-events-none absolute -right-1.5 top-1/2 hidden h-3 w-3 -translate-y-1/2 text-zinc-300 dark:text-zinc-700 lg:block"
              />
            ) : null}
          </li>
        ))}
      </ol>
    </section>
  );
}
