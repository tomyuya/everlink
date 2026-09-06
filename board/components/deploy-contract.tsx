import type { ReactNode } from "react";
import Link from "next/link";
import { Database, Globe, KeyRound, Timer } from "lucide-react";

/**
 * The self-hosting half of the landing page: WHERE EverLink writes (the safety
 * boundary) and WHAT a deployer must hand it.
 *
 * This is one section, not two. The old /how-it-works page carried a
 * "two-database model" block and a "deployer contract" block that each listed
 * the same two databases with their env vars — the reader met `<SITE>_DATABASE_URL`
 * and `EVERLINK_DATABASE_URL` twice, 40 lines apart, with the required/optional
 * distinction spelled out differently each time. Merging them keeps the write
 * boundary as the visual headline (it is the product's central trust claim) and
 * states each requirement exactly once.
 *
 * Every line here is checked against the code, not against the marketing draft:
 * the read-only session guard is `SET default_transaction_read_only = on` in
 * db.connect / scripts/export_slots.py, and db._assert_writable refuses a write
 * to a source host. The cron schedule matches railway.json (`0 * * * *`).
 */
export function DeployContract() {
  return (
    <section aria-label="Deploying EverLink" className="space-y-3">
      <div>
        <h2 className="text-sm font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
          Self-host it · what you provide, where it writes
        </h2>
        <p className="mt-1 text-[12px] leading-relaxed text-zinc-500 dark:text-zinc-400">
          EverLink hardcodes{" "}
          <strong className="text-zinc-700 dark:text-zinc-300">
            no domain, no database address, no secret
          </strong>{" "}
          — you supply all of it. The minimal deploy is{" "}
          <strong className="text-zinc-700 dark:text-zinc-300">
            a sitemap URL + EverLink&apos;s own database
          </strong>
          ; the LLM and your site&apos;s database are optional. Full runbook in{" "}
          <code className="rounded bg-zinc-100 px-1 dark:bg-zinc-800">DEPLOYMENT.md</code>.
        </p>
      </div>

      {/* The write-safety boundary: the two databases, once. */}
      <div className="grid gap-3 md:grid-cols-2">
        <RequirementCard
          icon={<Database className="h-4 w-4" />}
          tone="readonly"
          title="Your site's database"
          how="env <SITE>_DATABASE_URL"
          necessity="optional"
          lines={[
            "Only for deep path B, when you want block-level slots instead of a crawl.",
            "Opened STRICTLY READ-ONLY: SET default_transaction_read_only = on.",
            "db._assert_writable refuses any write aimed at a source host — this is the boundary that makes the whole product safe to point at production.",
          ]}
        />
        <RequirementCard
          icon={<Database className="h-4 w-4" />}
          tone="readwrite"
          title="EverLink's own database"
          how="env EVERLINK_DATABASE_URL"
          necessity="required"
          lines={[
            "The ONLY place EverLink writes: link_slots (its mirror), slot_checks, decisions, audit_log, settings, nightly_runs.",
            "Also what powers this board — without it the pages render, but empty.",
          ]}
        />
      </div>

      {/* The three things that are not a database. */}
      <div className="grid gap-3 sm:grid-cols-3">
        <RequirementCard
          icon={<Globe className="h-4 w-4" />}
          tone="plain"
          title="A sitemap or page URL"
          how="scan --site <url>"
          necessity="required"
          compact
          lines={["The zero-config default (path A): patrol any public site."]}
        />
        <RequirementCard
          icon={<KeyRound className="h-4 w-4" />}
          tone="plain"
          title="An LLM"
          how="AWS Bedrock credentials"
          necessity="optional"
          compact
          lines={["The Judge's fix proposals. Scan + L1/L2 detection need none."]}
        />
        <RequirementCard
          icon={<Timer className="h-4 w-4" />}
          tone="plain"
          title="A scheduler"
          how="Railway cron 0 * * * *"
          necessity="required"
          compact
          lines={[
            "Ticks hourly as a heartbeat; the chain itself runs once a day at the hour you set.",
          ]}
        />
      </div>

      <p className="text-[12px] text-zinc-500 dark:text-zinc-400">
        Run hour, rotation cycle, kill-switch and a run-now request live on{" "}
        <Link
          href="/settings"
          className="font-medium text-sky-600 hover:underline dark:text-sky-400"
        >
          /settings
        </Link>{" "}
        — no redeploy needed to change the schedule.
      </p>
    </section>
  );
}

function RequirementCard({
  icon,
  title,
  how,
  lines,
  tone,
  necessity,
  compact,
}: {
  icon: ReactNode;
  title: string;
  how: string;
  lines: string[];
  tone: "readonly" | "readwrite" | "plain";
  necessity: "required" | "optional";
  compact?: boolean;
}) {
  const iconCls =
    tone === "readonly"
      ? "text-sky-600 dark:text-sky-400"
      : tone === "readwrite"
        ? "text-emerald-600 dark:text-emerald-400"
        : "text-zinc-500 dark:text-zinc-400";
  return (
    <div className="rounded-xl border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900">
      <div className="flex flex-wrap items-center gap-2">
        <span className={iconCls}>{icon}</span>
        <span
          className={
            compact
              ? "text-[13px] font-semibold text-zinc-900 dark:text-zinc-100"
              : "text-sm font-semibold text-zinc-900 dark:text-zinc-100"
          }
        >
          {title}
        </span>
        <span
          className={
            necessity === "required"
              ? "ml-auto rounded-full bg-emerald-100 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300"
              : "rounded-full bg-zinc-100 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-zinc-500 dark:bg-zinc-800 dark:text-zinc-400"
          }
        >
          {necessity}
        </span>
      </div>
      <code className="mt-2 inline-block rounded bg-zinc-100 px-1.5 py-0.5 text-[11px] text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300">
        {how}
      </code>
      <ul className="mt-2 space-y-1 text-[12px] leading-relaxed text-zinc-500 dark:text-zinc-400">
        {lines.map((l) => (
          <li key={l}>· {l}</li>
        ))}
      </ul>
    </div>
  );
}
