import type { ReactNode } from "react";

import type { DecisionWithEvidence, LinkSlot, SlotCheck } from "@/lib/types";
import { VERDICT_META, cn, formatDateTime } from "@/lib/utils";

/**
 * The detection evidence behind a card: for every affected link slot, the L1 HTTP
 * probe (status + redirect chain), the L2 content verdict, and the final verdict
 * the judge reasoned over. This is what a human actually reads before approving.
 */
export function EvidenceChain({ data }: { data: DecisionWithEvidence }) {
  const { slots, checks } = data;
  const checkBySlot = new Map<string, SlotCheck>(checks.map((c) => [c.slot_id, c]));

  if (!slots.length) {
    return (
      <p className="text-sm text-zinc-500 dark:text-zinc-400">
        This card references no link slots.
      </p>
    );
  }

  return (
    <div className="space-y-3">
      {slots.map((slot) => (
        <SlotEvidence key={slot.id} slot={slot} check={checkBySlot.get(slot.id)} />
      ))}
    </div>
  );
}

function SlotEvidence({ slot, check }: { slot: LinkSlot; check?: SlotCheck }) {
  return (
    <div className="rounded-xl border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900">
      <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
        <span className="rounded bg-zinc-100 px-1.5 py-0.5 font-mono text-[11px] text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300">
          {slot.site}
        </span>
        <span className="text-xs uppercase tracking-wide text-zinc-400 dark:text-zinc-500">
          {slot.slot_type}
          {slot.block_type ? ` · ${slot.block_type}` : ""}
        </span>
        <span className="ml-auto font-mono text-[11px] text-zinc-400">{slot.id}</span>
      </div>

      {slot.article_title ? (
        <p className="mt-2 text-sm font-medium text-zinc-800 dark:text-zinc-200">
          {slot.article_title}
        </p>
      ) : null}

      <dl className="mt-3 space-y-1.5 text-xs">
        {slot.anchor_text ? (
          <Row label="Anchor">
            <span className="text-zinc-700 dark:text-zinc-300">{slot.anchor_text}</span>
          </Row>
        ) : null}
        <Row label="URL">
          <span className="break-all font-mono text-[11px] text-zinc-600 dark:text-zinc-400">
            {slot.url}
          </span>
        </Row>
        {slot.surrounding_sentence ? (
          <Row label="Context">
            <span className="italic text-zinc-500 dark:text-zinc-400">
              “{slot.surrounding_sentence}”
            </span>
          </Row>
        ) : null}
      </dl>

      <div className="mt-3 border-t border-zinc-100 pt-3 dark:border-zinc-800">
        <CheckDetail check={check} />
      </div>
    </div>
  );
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex gap-2">
      <dt className="w-16 shrink-0 text-zinc-400 dark:text-zinc-500">{label}</dt>
      <dd className="min-w-0 flex-1">{children}</dd>
    </div>
  );
}

function CheckDetail({ check }: { check?: SlotCheck }) {
  if (!check) {
    return (
      <p className="text-xs text-zinc-400 dark:text-zinc-500">
        No probe recorded for this slot.
      </p>
    );
  }
  const verdict = VERDICT_META[check.final_verdict];
  return (
    <div className="space-y-2 text-xs">
      <div className="flex flex-wrap items-center gap-2">
        <span className={cn("font-medium", verdict?.className ?? "text-zinc-600")}>
          {verdict?.label ?? check.final_verdict}
        </span>
        {check.l1_status != null ? (
          <span className="rounded bg-zinc-100 px-1.5 py-0.5 font-mono text-[11px] text-zinc-600 dark:bg-zinc-800 dark:text-zinc-400">
            HTTP {check.l1_status}
          </span>
        ) : null}
        {check.l2_verdict ? (
          <span className="text-zinc-500 dark:text-zinc-400">L2 · {check.l2_verdict}</span>
        ) : null}
        <span className="ml-auto text-zinc-400 dark:text-zinc-500">
          {formatDateTime(check.checked_at)}
        </span>
      </div>

      {check.redirect_chain?.length ? (
        <ol className="space-y-0.5 border-l border-zinc-200 pl-3 dark:border-zinc-700">
          {check.redirect_chain.map((hop, i) => (
            <li
              key={i}
              className="truncate font-mono text-[11px] text-zinc-500 dark:text-zinc-400"
            >
              <span className="text-zinc-400 dark:text-zinc-500">{hop.status}</span>{" "}
              {hop.url}
            </li>
          ))}
        </ol>
      ) : null}

      {check.l2_evidence ? (
        <p className="text-zinc-500 dark:text-zinc-400">{check.l2_evidence}</p>
      ) : null}
    </div>
  );
}
