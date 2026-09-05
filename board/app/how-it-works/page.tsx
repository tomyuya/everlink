import type { Metadata } from "next";
import type { ReactNode } from "react";
import {
  Boxes,
  Database,
  Globe,
  KeyRound,
  Server,
  ShieldCheck,
  Timer,
} from "lucide-react";

import { AutomationPanel } from "@/components/automation-panel";
import { Pipeline } from "@/components/pipeline";

export const metadata: Metadata = {
  title: "EverLink · how it works",
};

/**
 * The product's "start here" page: what EverLink is, the two-database model, and
 * exactly what a deployer must provide. STATIC and READ-ONLY — it never calls
 * getSql(), so it renders (and `next build` passes) with NO database configured.
 * Board twin of the README deployer contract.
 */
export default function HowItWorksPage() {
  return (
    <div className="space-y-8">
      <Positioning />
      <TwoDatabaseModel />
      <DeployerContract />
      <Pipeline />
      <AutomationPanel lastActivity="" />
      <ExampleDeploymentNote />
    </div>
  );
}

/** One-glance positioning: open-source, self-hosted, NOT a SaaS. */
function Positioning() {
  return (
    <section className="space-y-3">
      <h1 className="text-2xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-100">
        How EverLink works
      </h1>
      <p className="max-w-prose text-sm leading-relaxed text-zinc-600 dark:text-zinc-300">
        EverLink is an{" "}
        <span className="font-medium text-zinc-900 dark:text-zinc-100">
          open-source, self-hosted
        </span>{" "}
        agent that patrols the outbound links of <em>your</em> sites every night,
        detects link rot, repairs what it safely can, and surfaces a decision card
        only when a fix needs a human. You clone the code, deploy it on your own
        infrastructure, and fill in your own config.
      </p>
      <div className="flex flex-wrap gap-2 text-xs">
        <Badge icon={<Boxes className="h-3.5 w-3.5" />} label="Open source · MIT" />
        <Badge icon={<Server className="h-3.5 w-3.5" />} label="Self-hosted" />
        <Badge
          icon={<ShieldCheck className="h-3.5 w-3.5" />}
          label="Not a SaaS · no signup, no billing"
        />
      </div>
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

/** The key mental model: your read-only source DB vs EverLink's own DB. */
function TwoDatabaseModel() {
  return (
    <section aria-label="Two-database model" className="space-y-3">
      <h2 className="text-sm font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
        Two databases · the key to understanding EverLink
      </h2>
      <div className="grid gap-3 md:grid-cols-2">
        <DbCard
          n="①"
          title="Your site's database (the data source)"
          env="<SITE>_DATABASE_URL"
          tone="readonly"
          lines={[
            "Your products / articles / links live here.",
            "EverLink connects STRICTLY READ-ONLY (default_transaction_read_only=on).",
            "EverLink NEVER writes here — db._assert_writable refuses any source-host write.",
          ]}
        />
        <DbCard
          n="②"
          title="EverLink's own database"
          env="EVERLINK_DATABASE_URL"
          tone="readwrite"
          lines={[
            "link_slots — a mirror of the links it patrols.",
            "slot_checks / decisions / audit_log — the run's own process data.",
            "The ONLY place EverLink writes.",
          ]}
        />
      </div>
    </section>
  );
}

function DbCard({
  n,
  title,
  env,
  lines,
  tone,
}: {
  n: string;
  title: string;
  env: string;
  lines: string[];
  tone: "readonly" | "readwrite";
}) {
  return (
    <div className="rounded-xl border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900">
      <div className="flex items-center gap-2">
        <Database
          className={
            tone === "readonly"
              ? "h-4 w-4 text-sky-600 dark:text-sky-400"
              : "h-4 w-4 text-emerald-600 dark:text-emerald-400"
          }
        />
        <span className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">
          {n} {title}
        </span>
      </div>
      <code className="mt-2 inline-block rounded bg-zinc-100 px-1.5 py-0.5 text-[11px] text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300">
        {env}
      </code>
      <ul className="mt-2 space-y-1 text-[12px] leading-relaxed text-zinc-500 dark:text-zinc-400">
        {lines.map((l) => (
          <li key={l}>· {l}</li>
        ))}
      </ul>
    </div>
  );
}

/** What a deployer must provide — board twin of the README contract table. */
function DeployerContract() {
  const items = [
    { icon: <Database className="h-4 w-4" />, what: "Your site's DB (read-only)", how: "env <SITE>_DATABASE_URL", why: "the links to patrol are read from here" },
    { icon: <Globe className="h-4 w-4" />, what: "Your site's public origin", how: "env <SITE>_PUBLIC_ORIGIN", why: "turns relative /products/x into an absolute URL to probe" },
    { icon: <Database className="h-4 w-4" />, what: "EverLink's own DB", how: "env EVERLINK_DATABASE_URL", why: "stores checks, decisions, audit" },
    { icon: <KeyRound className="h-4 w-4" />, what: "An LLM", how: "AWS Bedrock credentials", why: "the Judge / Writer brain" },
    { icon: <Timer className="h-4 w-4" />, what: "A scheduler", how: "Railway cron 0 3 * * *", why: "triggers the nightly patrol" },
  ];
  return (
    <section aria-label="Deployer contract" className="space-y-3">
      <h2 className="text-sm font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
        Deploy it · what you provide
      </h2>
      <p className="text-[12px] text-zinc-500 dark:text-zinc-400">
        EverLink hardcodes NO domain, DB address, or secret — you supply all of it.
        Full runbook in{" "}
        <code className="rounded bg-zinc-100 px-1 dark:bg-zinc-800">DEPLOYMENT.md</code>.
      </p>
      <ol className="grid gap-2 sm:grid-cols-2 lg:grid-cols-5">
        {items.map((it, i) => (
          <li
            key={it.what}
            className="rounded-xl border border-zinc-200 bg-white p-3 dark:border-zinc-800 dark:bg-zinc-900"
          >
            <div className="flex items-center gap-1.5 text-xs font-semibold text-zinc-700 dark:text-zinc-300">
              <span className="inline-flex h-5 w-5 items-center justify-center rounded-md bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300">
                {it.icon}
              </span>
              {i + 1}. {it.what}
            </div>
            <code className="mt-1.5 block truncate text-[10px] text-sky-700 dark:text-sky-400">
              {it.how}
            </code>
            <p className="mt-1 text-[11px] leading-relaxed text-zinc-500 dark:text-zinc-400">
              {it.why}
            </p>
          </li>
        ))}
      </ol>
    </section>
  );
}

/** Honesty note: the three sites here are the maintainer's dogfooding example. */
function ExampleDeploymentNote() {
  return (
    <section className="rounded-xl border border-zinc-200 bg-zinc-50 p-4 text-[12px] leading-relaxed text-zinc-600 dark:border-zinc-800 dark:bg-zinc-900/50 dark:text-zinc-300">
      <strong className="text-zinc-900 dark:text-zinc-100">
        This deployment is an example.
      </strong>{" "}
      The AethelGem / HotDeals / FlashDeals sites in this board are the maintainer&apos;s
      own — the first user dogfooding EverLink. Their internal site keys (e.g.{" "}
      <code>sandcart</code> = FlashDeals) stand in for <em>your</em> site keys. When
      you deploy EverLink you point it at your own databases and origins; nothing
      about these example sites is baked into the code.
    </section>
  );
}
