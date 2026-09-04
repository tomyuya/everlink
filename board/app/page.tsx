import type { Metadata } from "next";
import Image from "next/image";
import Link from "next/link";
import { HeartPulse, Inbox as InboxIcon, ListChecks, Timer } from "lucide-react";

import { AutomationPanel } from "@/components/automation-panel";
import { EmptyState } from "@/components/empty-state";
import { InboxClient } from "@/components/inbox-client";
import { Pipeline } from "@/components/pipeline";
import { isReadonly } from "@/lib/db";
import { listAudit, listDecisions, statusCounts, weeklyStats } from "@/lib/queries";
import { relativeTime } from "@/lib/utils";
import type { Decision, DecisionStatus, StatusCounts, WeeklyStats } from "@/lib/types";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "Inbox · EverLink Board",
};

const VALID = new Set(["pending", "approved", "applied", "rejected", "expired", "all"]);

export default async function InboxPage({
  searchParams,
}: {
  searchParams: Promise<{ status?: string }>;
}) {
  const sp = await searchParams;
  const raw = sp.status ?? "pending";
  const status = (VALID.has(raw) ? raw : "pending") as DecisionStatus | "all";

  let decisions: Decision[] = [];
  let counts: StatusCounts = {};
  let stats: WeeklyStats | null = null;
  let lastActivity = "";
  let dbError: string | null = null;
  try {
    const [d, c, s, audit] = await Promise.all([
      listDecisions(status, 200),
      statusCounts(),
      weeklyStats(30),
      listAudit(1),
    ]);
    decisions = d;
    counts = c;
    stats = s;
    lastActivity = relativeTime(audit[0]?.ts);
  } catch (e) {
    dbError = e instanceof Error ? e.message : "Failed to load decisions";
  }

  return (
    <div className="space-y-8">
      <Hero />

      {!dbError && stats ? (
        <Pulse
          pending={counts.pending ?? 0}
          healed={stats.links_healed}
          decided={stats.decisions_decided}
          lastActivity={lastActivity}
        />
      ) : null}

      <Pipeline />

      <AutomationPanel lastActivity={lastActivity} />

      <div id="inbox" className="space-y-5 border-t border-zinc-200 pt-6 dark:border-zinc-800">
        <div>
          <h2 className="text-xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-100">
            Decision inbox
          </h2>
          <p className="mt-1 text-sm text-zinc-500 dark:text-zinc-400">
            The one place EverLink stops for a human. Approve, reject, or batch the
            low-risk fixes it surfaced above.
          </p>
        </div>

        {dbError ? (
          <EmptyState
            title="Database unavailable"
            hint={dbError}
            icon={<InboxIcon className="h-8 w-8" />}
          />
        ) : (
          <InboxClient
            decisions={decisions}
            counts={counts}
            status={status}
            readonly={isReadonly()}
          />
        )}
      </div>
    </div>
  );
}

/** Brand hero: what the product is, in one glance, with the brand illustration. */
function Hero() {
  return (
    <section className="grid items-center gap-6 lg:grid-cols-[1.1fr_1fr]">
      <div>
        <div className="flex items-center gap-3">
          {/* Vector mark: crisp at any size (the raster illustration blurs when small). */}
          <img
            src="/everlink-mark.svg"
            alt=""
            aria-hidden
            className="h-11 w-11 rounded-xl"
            width={44}
            height={44}
          />
          <div>
            <h1 className="text-2xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-100">
              EverLink
            </h1>
            <p className="text-sm font-medium text-sky-700 dark:text-sky-400">
              The autonomous link-rot steward
            </p>
          </div>
        </div>
        <p className="mt-4 max-w-prose text-sm leading-relaxed text-zinc-600 dark:text-zinc-300">
          EverLink continuously scans your sites&rsquo; outbound links, detects rot
          (dead pages, changed offers, ended programs), and{" "}
          <span className="font-medium text-zinc-900 dark:text-zinc-100">
            repairs it itself
          </span>
          . It only stops here — at this board — when a fix is risky enough to need a
          human judgment. Everything else heals on its own, on a schedule, and leaves an
          audit trail.
        </p>
        <div className="mt-4 flex flex-wrap items-center gap-2 text-xs">
          <Link
            href="#inbox"
            className="rounded-md bg-zinc-900 px-3 py-1.5 font-medium text-white dark:bg-zinc-100 dark:text-zinc-900"
          >
            Review decisions
          </Link>
          <span className="rounded-full bg-zinc-100 px-2.5 py-1 font-medium text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300">
            Built on AWS Strands SDK + Bedrock
          </span>
          <span className="rounded-full bg-zinc-100 px-2.5 py-1 font-medium text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300">
            Human-in-the-loop
          </span>
        </div>
      </div>

      <figure className="overflow-hidden rounded-2xl border border-zinc-200 bg-zinc-900 dark:border-zinc-800">
        <Image
          src="/everlink-logo.png"
          alt="Illustration: a robotic arm re-welding a broken chain link between web pages"
          width={1536}
          height={1024}
          className="h-auto w-full object-cover"
          priority
        />
      </figure>
    </section>
  );
}

/** Live proof the loop is running, even when the inbox is (happily) empty. */
function Pulse({
  pending,
  healed,
  decided,
  lastActivity,
}: {
  pending: number;
  healed: number;
  decided: number;
  lastActivity: string;
}) {
  const tiles = [
    { icon: <InboxIcon className="h-4 w-4" />, label: "Awaiting you", value: String(pending), accent: "text-amber-600 dark:text-amber-400" },
    { icon: <HeartPulse className="h-4 w-4" />, label: "Links healed · 30d", value: String(healed), accent: "text-emerald-600 dark:text-emerald-400" },
    { icon: <ListChecks className="h-4 w-4" />, label: "Decisions decided · 30d", value: String(decided), accent: "text-sky-600 dark:text-sky-400" },
    { icon: <Timer className="h-4 w-4" />, label: "Last activity", value: lastActivity || "—", accent: "text-zinc-600 dark:text-zinc-300" },
  ];
  return (
    <section aria-label="Pipeline health" className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
      {tiles.map(({ icon, label, value, accent }) => (
        <div
          key={label}
          className="rounded-xl border border-zinc-200 bg-white p-3 dark:border-zinc-800 dark:bg-zinc-900"
        >
          <div className={`flex items-center gap-1.5 text-xs ${accent}`}>
            {icon}
            <span className="font-medium">{label}</span>
          </div>
          <p className="mt-1.5 text-xl font-semibold tabular-nums text-zinc-900 dark:text-zinc-100">
            {value}
          </p>
        </div>
      ))}
    </section>
  );
}
