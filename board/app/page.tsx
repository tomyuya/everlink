import type { Metadata } from "next";
import Image from "next/image";
import Link from "next/link";
import type { ReactNode } from "react";
import { Boxes, Globe, ShieldCheck, Sparkles } from "lucide-react";

import { AutomationPanel, type ScheduleState } from "@/components/automation-panel";
import { DeployContract } from "@/components/deploy-contract";
import { OnboardingPaths } from "@/components/onboarding-paths";
import { Pipeline } from "@/components/pipeline";
import { cronOverview, getSettings, listAudit, parseLedgerReason } from "@/lib/queries";
import { relativeTime } from "@/lib/utils";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "EverLink · the autonomous link-rot steward",
};

/**
 * The ONE product page: what EverLink is, the loop it runs, how that loop runs
 * itself, how you feed it, and what you must provide to self-host it.
 *
 * This absorbed /how-it-works. The two pages rendered three whole components
 * verbatim in common (OnboardingPaths, Pipeline, AutomationPanel) and each
 * opened with its own "what EverLink is" hero, so a visitor who clicked through
 * read the same pitch twice. The sections that were genuinely unique to that
 * page — the write-safety boundary, the deployer contract, the dogfooding
 * honesty note — now live below, and the boundary + contract were merged into a
 * single DeployContract section because they listed the same two databases and
 * the same two env vars twice, forty lines apart. /how-it-works still resolves:
 * next.config.ts 308-redirects it here, so the README, the manuals and the
 * hackathon submission links keep working.
 *
 * DEGRADES HONESTLY: every read below is optional. With no EVERLINK_DATABASE_URL
 * (or before the control-plane schema is migrated) the page still renders in
 * full — the automation panel simply drops its live schedule chips rather than
 * inventing a cron time. That is why this stays try/catch instead of throwing.
 */
export default async function HomePage() {
  const { lastActivity, schedule } = await readLiveState();

  return (
    <div className="space-y-8">
      <Hero />

      {/* The loop, then how the loop runs itself — one continuous story. */}
      <Pipeline />
      <AutomationPanel lastActivity={lastActivity} schedule={schedule} />

      {/* Feeding it, then hosting it. OnboardingPaths carries the "you do NOT
          need to hand over your database" message, so it must land before the
          requirements below. */}
      <OnboardingPaths />
      <DeployContract />

      <ExampleDeploymentNote />
    </div>
  );
}

/**
 * Best-effort live state for the automation panel. A missing DB or an unmigrated
 * control plane must remove the live numbers, never blank the product page.
 */
async function readLiveState(): Promise<{
  lastActivity: string;
  schedule: ScheduleState | null;
}> {
  let lastActivity = "";
  let schedule: ScheduleState | null = null;

  try {
    const audit = await listAudit(1);
    lastActivity = relativeTime(audit[0]?.ts);
  } catch {
    /* No DB configured: the panel shows "—" for last activity. */
  }

  try {
    const settings = await getSettings();
    // The nightly_runs ledger can lag the settings table on a fresh deploy, so a
    // failure there must not throw away the schedule we did manage to read.
    const overview = await cronOverview().catch(() => null);
    const lastRun = overview?.last_run ?? null;
    // Quoted straight from the ledger row, trigger AND origin included, so
    // "33m ago · ok · --force · local" can never be read as an unattended cron
    // run. The origin tag is what nightly.py's run_origin() recorded about the
    // process that wrote the row — not a guess made here afterwards.
    const tagged = lastRun ? parseLedgerReason(lastRun.reason) : null;
    schedule = {
      runHourUtc: settings.run_hour_utc,
      cycleDays: settings.rotation_cycle_days,
      enabled: settings.enabled,
      lastRun:
        lastRun && tagged
          ? {
              label: [
                relativeTime(lastRun.started_at),
                lastRun.status,
                tagged.text,
                tagged.origin === "unknown" ? "untagged" : tagged.origin,
              ]
                .filter(Boolean)
                .join(" · "),
              ok: lastRun.status === "ok",
            }
          : null,
    };
  } catch {
    /* Control plane not migrated yet: documentation-only panel. */
  }

  return { lastActivity, schedule };
}

/**
 * Identity + positioning in one glance. Merges the old home hero (the product
 * pitch beside the brand illustration) with /how-it-works' "Positioning" block
 * (open-source, self-hosted, not a SaaS): the two were the same claim told
 * twice, so the paragraph now carries both and the badges carry the rest.
 *
 * Dropped on purpose: the second brand panel (it repeated the nav's vector mark
 * at display size) and the "Human-in-the-loop" badge (stage 4 of the pipeline
 * below says it better, and highlights it).
 */
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
          EverLink patrols your sites&rsquo; outbound links on a schedule, detects rot
          &mdash; dead pages, changed offers, ended affiliate programs &mdash; and{" "}
          <span className="font-medium text-zinc-900 dark:text-zinc-100">
            repairs what it safely can
          </span>
          . It stops at the decision inbox only when a fix is risky enough to need a
          human judgment; everything else heals on its own and leaves an audit trail.
          It is{" "}
          <span className="font-medium text-zinc-900 dark:text-zinc-100">
            open-source and self-hosted
          </span>
          : you clone the code, run it on your own infrastructure, and fill in your own
          config &mdash; no signup, no billing, no multi-tenancy.
        </p>

        <div className="mt-4 flex flex-wrap items-center gap-2 text-xs">
          <Link
            href="/inbox"
            className="rounded-md bg-zinc-900 px-3 py-1.5 font-medium text-white dark:bg-zinc-100 dark:text-zinc-900"
          >
            Review decisions
          </Link>
          <a
            href="https://github.com/tomyuya/everlink"
            target="_blank"
            rel="noopener noreferrer"
            className="rounded-md border border-zinc-300 px-3 py-1.5 font-medium text-zinc-700 hover:bg-zinc-100 dark:border-zinc-700 dark:text-zinc-200 dark:hover:bg-zinc-800"
          >
            Source on GitHub
          </a>
        </div>

        <div className="mt-3 flex flex-wrap items-center gap-2 text-xs">
          <Badge icon={<Boxes className="h-3.5 w-3.5" />} label="Open source · MIT" />
          <Badge
            icon={<ShieldCheck className="h-3.5 w-3.5" />}
            label="Self-hosted · not a SaaS"
          />
          <Badge
            icon={<Sparkles className="h-3.5 w-3.5" />}
            label="AWS Strands SDK + Bedrock"
          />
          <Badge
            icon={<Globe className="h-3.5 w-3.5" />}
            label="Any site · zero config"
          />
        </div>
      </div>

      <figure className="relative overflow-hidden rounded-2xl border border-zinc-200 bg-zinc-900 dark:border-zinc-800">
        <Image
          src="/everlink-logo.png"
          alt="Illustration: a robotic arm re-welding a broken chain link between web pages"
          width={1536}
          height={1024}
          className="h-auto w-full object-cover"
          priority
        />
        {/* Caption over the illustration's empty upper band: the reworded
            "any site / zero config" claim plus the two facts a first-time
            visitor most needs (read-only, LLM-free detection, human-approved
            writes). HTML, not baked into the raster, so it stays crisp and
            editable. pointer-events-none keeps it from eating clicks. */}
        <div className="pointer-events-none absolute left-5 top-5 max-w-[85%] space-y-1">
          <p className="text-sm font-semibold tracking-tight text-white drop-shadow-sm">
            Zero-config crawl of any site &mdash; read-only.
          </p>
          <p className="text-[11px] leading-relaxed text-zinc-300 drop-shadow-sm">
            Detection needs no LLM &middot; a human approves every write
          </p>
        </div>
      </figure>
    </section>
  );
}

function Badge({ icon, label }: { icon: ReactNode; label: string }) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full bg-zinc-100 px-2.5 py-1 font-medium text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300">
      {icon}
      {label}
    </span>
  );
}

/**
 * Honesty note: the three sites in this deployment are the maintainer's own
 * dogfooding example, not a multi-tenant product. Kept last, verbatim from the
 * old /how-it-works page — it is the one claim a reviewer could otherwise
 * misread, and it is true (no site key is hardcoded; see the deployer contract).
 */
function ExampleDeploymentNote() {
  return (
    <section className="rounded-xl border border-zinc-200 bg-zinc-50 p-4 text-[12px] leading-relaxed text-zinc-600 dark:border-zinc-800 dark:bg-zinc-900/50 dark:text-zinc-300">
      <strong className="text-zinc-900 dark:text-zinc-100">
        This deployment is an example.
      </strong>{" "}
      The AethelGem / HotDeals / FlashDeals sites in this board are the
      maintainer&apos;s own &mdash; the first user dogfooding EverLink. Their internal
      site keys (e.g. <code>sandcart</code> = FlashDeals) stand in for <em>your</em>{" "}
      site keys. When you deploy EverLink you point it at your own databases and
      origins; nothing about these example sites is baked into the code.
    </section>
  );
}
