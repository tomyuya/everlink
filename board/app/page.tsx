import type { Metadata } from "next";
import Image from "next/image";
import Link from "next/link";

import { AutomationPanel } from "@/components/automation-panel";
import { OnboardingPaths } from "@/components/onboarding-paths";
import { Pipeline } from "@/components/pipeline";
import { listAudit } from "@/lib/queries";
import { relativeTime } from "@/lib/utils";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "EverLink · the autonomous link-rot steward",
};

/**
 * The product home page — the public showcase: what EverLink is, the two ways
 * to feed it, the whole autonomous pipeline at a glance, and the nightly
 * entrypoint. Operational counters (awaiting / healed / decided) deliberately
 * live on /inbox, the working surface, so this page stays a clean
 * "understand in one glance" narrative for outsiders.
 */
export default async function HomePage() {
  let lastActivity = "";
  try {
    const audit = await listAudit(1);
    lastActivity = relativeTime(audit[0]?.ts);
  } catch {
    /* No DB configured: the showcase still renders; the panel shows "—". */
  }

  return (
    <div className="space-y-8">
      <Hero />

      {/* Two ways to feed EverLink — sits right above the loop so nobody reads
          the pipeline as "you must wire a database first". */}
      <OnboardingPaths />

      <Pipeline />

      <AutomationPanel lastActivity={lastActivity} />
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
          . It only stops at the decision inbox when a fix is risky enough to need a
          human judgment. Everything else heals on its own, on a schedule, and leaves an
          audit trail. Point it at{" "}
          <span className="font-medium text-zinc-900 dark:text-zinc-100">
            any sitemap or page URL
          </span>{" "}
          &mdash; it crawls read-only over HTTP, so you can start with no database access
          at all.
        </p>
        <div className="mt-4 flex flex-wrap items-center gap-2 text-xs">
          <Link
            href="/inbox"
            className="rounded-md bg-zinc-900 px-3 py-1.5 font-medium text-white dark:bg-zinc-100 dark:text-zinc-900"
          >
            Review decisions
          </Link>
          <span className="rounded-full bg-zinc-100 px-2.5 py-1 font-medium text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300">
            Works with any site · zero-config crawl
          </span>
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
