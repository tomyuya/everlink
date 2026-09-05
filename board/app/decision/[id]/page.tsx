import type { Metadata } from "next";
import type { ReactNode } from "react";
import Link from "next/link";
import { ArrowLeft, FileWarning } from "lucide-react";
import { notFound } from "next/navigation";

import { DecisionActions } from "@/components/decision-actions";
import { EvidenceChain } from "@/components/evidence-chain";
import { RiskBadge } from "@/components/risk-badge";
import { StatusPill } from "@/components/status-pill";
import { VerifyBanner } from "@/components/verify-banner";
import { EmptyState } from "@/components/empty-state";
import { isReadonly } from "@/lib/db";
import { getDecisionWithEvidence } from "@/lib/queries";
import { ACTION_LABEL, formatDateTime } from "@/lib/utils";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "Decision · EverLink Board",
};

export default async function DecisionPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;

  let data = null as Awaited<ReturnType<typeof getDecisionWithEvidence>>;
  let dbError: string | null = null;
  try {
    data = await getDecisionWithEvidence(id);
  } catch (e) {
    dbError = e instanceof Error ? e.message : "Failed to load decision";
  }

  if (dbError) {
    return (
      <div className="space-y-4">
        <BackLink />
        <EmptyState
          title="Database unavailable"
          hint={dbError}
          icon={<FileWarning className="h-8 w-8" />}
        />
      </div>
    );
  }

  if (!data) notFound();

  const { decision, slots, checks } = data;
  const { proposal } = decision;

  return (
    <div className="space-y-6">
      <BackLink />

      <div className="rounded-xl border border-zinc-200 bg-white p-5 dark:border-zinc-800 dark:bg-zinc-900">
        <div className="flex flex-wrap items-center gap-2">
          <StatusPill status={decision.status} />
          <RiskBadge risk={proposal.risk_level} />
          <h1 className="text-lg font-semibold text-zinc-900 dark:text-zinc-100">
            {ACTION_LABEL[proposal.action] ?? proposal.action}
          </h1>
          <span className="ml-auto font-mono text-xs text-zinc-400">{decision.id}</span>
        </div>

        {proposal.rationale ? (
          <p className="mt-3 text-sm leading-relaxed text-zinc-700 dark:text-zinc-300">
            {proposal.rationale}
          </p>
        ) : null}

        <div className="mt-4">
          <VerifyBanner slots={slots} checks={checks} />
        </div>

        <dl className="mt-4 grid gap-3 sm:grid-cols-2">
          {proposal.new_url ? (
            <Field label="New URL">
              <span className="break-all font-mono text-xs text-sky-700 dark:text-sky-400">
                {proposal.new_url}
              </span>
            </Field>
          ) : null}
          {proposal.new_anchor ? (
            <Field label="New anchor">{proposal.new_anchor}</Field>
          ) : null}
          {proposal.new_sentence ? (
            <Field label="New sentence">{proposal.new_sentence}</Field>
          ) : null}
          {decision.reject_reason ? (
            <Field label="Reject reason">
              <span className="text-rose-600 dark:text-rose-400">
                {decision.reject_reason}
              </span>
            </Field>
          ) : null}
          <Field label="Created">{formatDateTime(decision.created_at)}</Field>
          <Field label="Decided">{formatDateTime(decision.decided_at)}</Field>
        </dl>

        <div className="mt-5 border-t border-zinc-100 pt-4 dark:border-zinc-800">
          <DecisionActions
            id={decision.id}
            status={decision.status}
            readonly={isReadonly()}
          />
        </div>
      </div>

      <section className="space-y-3">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
          Evidence chain · {slots.length} slot{slots.length === 1 ? "" : "s"}
        </h2>
        <EvidenceChain data={data} />
      </section>
    </div>
  );
}

function BackLink() {
  return (
    <Link
      href="/inbox"
      className="inline-flex items-center gap-1 text-sm text-zinc-500 hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-100"
    >
      <ArrowLeft className="h-4 w-4" />
      Inbox
    </Link>
  );
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <dt className="text-xs uppercase tracking-wide text-zinc-400 dark:text-zinc-500">
        {label}
      </dt>
      <dd className="mt-0.5 text-sm text-zinc-700 dark:text-zinc-300">{children}</dd>
    </div>
  );
}
