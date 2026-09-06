import type { ReactNode } from "react";
import { Database, Globe } from "lucide-react";

/**
 * The two ways EverLink gets links to patrol — generic read-only crawl (the
 * zero-config default, path A) vs first-party DB snapshot (optional deep path B).
 * Shared by the home page (above the autonomous loop) and /how-it-works (above
 * the two-database model) so the onboarding message never drifts between pages.
 * The intro is intentionally FULL-WIDTH (no max-w-prose) per design.
 */
export function OnboardingPaths() {
  return (
    <section aria-label="Two ways to feed EverLink" className="space-y-3">
      <h2 className="text-sm font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
        Two ways to feed it · start with zero config
      </h2>
      <p className="text-[12px] leading-relaxed text-zinc-500 dark:text-zinc-400">
        EverLink does{" "}
        <strong className="text-zinc-700 dark:text-zinc-300">not</strong> need access to
        your database to start. Point it at any public sitemap or page URL and it crawls
        read-only over HTTP, extracting outbound links on the fly. Connecting your own DB
        is an <em>optional</em> deep path for block-level slots and write-back.
      </p>
      <div className="grid gap-3 md:grid-cols-2">
        <PathCard
          n="A"
          tone="default"
          icon={<Globe className="h-4 w-4" />}
          title="Generic read-only crawl — the default, zero config"
          cmd="scan --site https://your-site.com/sitemap.xml"
          lines={[
            "Works with ANY website — no source database, no code change.",
            "Read-only HTTP: fetches public pages and extracts outbound links live.",
            "L1/L2 detection needs zero AWS credentials; only the Judge's fix proposals need an LLM.",
            "Never writes back · honours robots.txt · ≤1 request per link · polite rate limit.",
          ]}
        />
        <PathCard
          n="B"
          tone="deep"
          icon={<Database className="h-4 w-4" />}
          title="First-party DB snapshot — optional deep path"
          cmd="<SITE>_DATABASE_URL + scripts/export_slots.py"
          lines={[
            "For your OWN site when you want block-level slots and write-back.",
            "Connects STRICTLY READ-ONLY; export_slots.py writes a data/slots_<site>.csv snapshot.",
            "Adds <SITE>_PUBLIC_ORIGIN so a relative /products/x becomes an absolute URL to probe.",
            "Write-back stays gated (approved cards only) and whitelisted per site.",
          ]}
        />
      </div>
    </section>
  );
}

function PathCard({
  n,
  title,
  cmd,
  lines,
  icon,
  tone,
}: {
  n: string;
  title: string;
  cmd: string;
  lines: string[];
  icon: ReactNode;
  tone: "default" | "deep";
}) {
  return (
    <div className="rounded-xl border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900">
      <div className="flex items-center gap-2">
        <span
          className={
            tone === "default"
              ? "text-emerald-600 dark:text-emerald-400"
              : "text-sky-600 dark:text-sky-400"
          }
        >
          {icon}
        </span>
        <span className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">
          {n} · {title}
        </span>
      </div>
      <code className="mt-2 inline-block rounded bg-zinc-100 px-1.5 py-0.5 text-[11px] text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300">
        {cmd}
      </code>
      <ul className="mt-2 space-y-1 text-[12px] leading-relaxed text-zinc-500 dark:text-zinc-400">
        {lines.map((l) => (
          <li key={l}>· {l}</li>
        ))}
      </ul>
    </div>
  );
}
