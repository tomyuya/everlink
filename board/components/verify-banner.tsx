import { ExternalLink, ShieldAlert, ShieldQuestion } from "lucide-react";

import type { LinkSlot, SlotCheck } from "@/lib/types";
import { VERDICT_META, cn, isProbeInconclusive } from "@/lib/utils";

/**
 * Human-verification affordance for a decision card.
 *
 * Every EverLink verdict comes from an automated probe reading a page from a
 * datacenter IP. That has two honest limits, and this banner surfaces both:
 *   1. the probe can be BLOCKED (bot-wall / captcha / timeout) even though the
 *      link opens fine for a real person -> `needs_human_recheck`; and
 *   2. even a confident negative (dead / unavailable) is a machine reading, not
 *      a human click — on-page text (reviews, Q&A) can mislead it.
 *
 * The board is human-in-the-loop by design: whoever reviews a card is the final
 * arbiter. So every affected link gets a one-click "open it yourself", with the
 * framing escalated to a warning when the probe itself was inconclusive.
 */
export function VerifyBanner({
  slots,
  checks,
}: {
  slots: LinkSlot[];
  checks: SlotCheck[];
}) {
  const links = slots.filter((s) => s.url);
  if (!links.length) return null;

  const inconclusive = checks.some(isProbeInconclusive);
  const verdict = checks
    .map((c) => c.final_verdict)
    .find((v) => v && v !== "healthy");
  const verdictLabel = verdict ? VERDICT_META[verdict]?.label ?? verdict : null;
  const Icon = inconclusive ? ShieldQuestion : ShieldAlert;

  return (
    <div
      className={cn(
        "rounded-lg border p-3",
        inconclusive
          ? "border-amber-300 bg-amber-50 dark:border-amber-500/40 dark:bg-amber-500/10"
          : "border-sky-200 bg-sky-50 dark:border-sky-500/30 dark:bg-sky-500/10",
      )}
    >
      <div className="flex items-start gap-2">
        <Icon
          className={cn(
            "mt-0.5 h-4 w-4 shrink-0",
            inconclusive
              ? "text-amber-600 dark:text-amber-400"
              : "text-sky-600 dark:text-sky-400",
          )}
        />
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium text-zinc-800 dark:text-zinc-100">
            {inconclusive
              ? "Our automated probe couldn’t verify this link"
              : "Automated verdict — you are the final check"}
          </p>
          <p className="mt-1 text-xs leading-relaxed text-zinc-600 dark:text-zinc-300">
            {inconclusive ? (
              <>
                The probe was blocked or got an inconclusive response
                {verdictLabel ? <> (flagged “{verdictLabel}”)</> : null}. That is a
                limit of a script on a datacenter IP —{" "}
                <span className="font-medium text-zinc-800 dark:text-zinc-100">
                  it does not mean the link is broken for real users
                </span>
                , who usually open it fine in a browser.
              </>
            ) : (
              <>
                A script read this page from a datacenter IP and flagged it
                {verdictLabel ? <> as “{verdictLabel}”</> : null}. Anti-bot walls and
                on-page text (reviews, Q&amp;A) can mislead an automated read, so open
                the link yourself before deciding.
              </>
            )}
          </p>
          <div className="mt-2 flex flex-wrap gap-2">
            {links.map((s) => (
              <a
                key={s.id}
                href={s.url}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex max-w-full items-center gap-1.5 rounded-md bg-white px-2.5 py-1.5 text-xs font-medium text-zinc-800 ring-1 ring-zinc-300 hover:bg-zinc-50 dark:bg-zinc-800 dark:text-zinc-100 dark:ring-zinc-600 dark:hover:bg-zinc-700"
              >
                <ExternalLink className="h-3.5 w-3.5 shrink-0" />
                <span className="truncate">
                  {links.length === 1
                    ? "Open in your browser"
                    : s.anchor_text?.trim() || s.url}
                </span>
              </a>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
