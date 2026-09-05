/**
 * Board data access. These queries MIRROR the Python `everlink.queue.DbDecisionStore`
 * and `everlink.db` SQL exactly, so the board (TS) and the agent (Python) are two
 * views of ONE durable decision queue:
 *
 *   scan (Python) -> enqueue pending  ->  board approve/reject (TS)  ->  worker
 *   claims approved (Python) -> writer applies (pe1) -> mark applied (Python)
 *
 * The board's ONLY writes are decision status transitions (pending -> approved |
 * rejected), each guarded by `assertBoardWritable()` and scoped `WHERE status =
 * 'pending'` so a stale/double click can never re-decide a settled card.
 */
import { assertBoardWritable, getSql } from "./db";
import { safeJsonParse } from "./utils";
import type {
  AuditRow,
  Decision,
  DecisionRow,
  DecisionStatus,
  DecisionWithEvidence,
  LinkSlot,
  Proposal,
  RedirectHop,
  SlotCheck,
  SlotCheckRow,
  StatusCounts,
  WeeklyStats,
} from "./types";

/** neon's tagged template resolves to `Record<string, any>[]`; cast to the row type. */
async function query<T>(p: Promise<unknown>): Promise<T> {
  return (await p) as T;
}

const EMPTY_PROPOSAL: Proposal = {
  action: "ESCALATE_HUMAN",
  rationale: "(unparseable proposal)",
  risk_level: "high",
};

function rowToDecision(r: DecisionRow): Decision {
  return {
    id: r.id,
    affected_slot_ids: safeJsonParse<string[]>(r.affected_slot_ids, []),
    proposal: safeJsonParse<Proposal>(r.proposal, EMPTY_PROPOSAL),
    status: r.status,
    reject_reason: r.reject_reason,
    created_at: r.created_at,
    decided_at: r.decided_at,
  };
}

function rowToCheck(r: SlotCheckRow): SlotCheck {
  return {
    slot_id: r.slot_id,
    l1_status: r.l1_status,
    redirect_chain: safeJsonParse<RedirectHop[]>(r.l1_redirect_chain, []),
    l2_verdict: r.l2_verdict,
    l2_evidence: r.l2_evidence,
    final_verdict: r.final_verdict,
    checked_at: r.checked_at,
  };
}

// --------------------------------------------------------------------------- //
// reads
// --------------------------------------------------------------------------- //
export async function listDecisions(
  status: DecisionStatus | "all" = "pending",
  limit = 100,
): Promise<Decision[]> {
  const sql = getSql();
  const rows =
    status === "all"
      ? await query<DecisionRow[]>(
          sql`SELECT id, affected_slot_ids, proposal, status, reject_reason, created_at, decided_at
              FROM decisions ORDER BY created_at DESC LIMIT ${limit}`,
        )
      : await query<DecisionRow[]>(
          sql`SELECT id, affected_slot_ids, proposal, status, reject_reason, created_at, decided_at
              FROM decisions WHERE status = ${status}
              ORDER BY created_at DESC LIMIT ${limit}`,
        );
  return rows.map(rowToDecision);
}

export async function getDecision(id: string): Promise<Decision | null> {
  const sql = getSql();
  const rows = await query<DecisionRow[]>(
    sql`SELECT id, affected_slot_ids, proposal, status, reject_reason, created_at, decided_at
        FROM decisions WHERE id = ${id} LIMIT 1`,
  );
  return rows.length ? rowToDecision(rows[0]) : null;
}

export async function statusCounts(): Promise<StatusCounts> {
  const sql = getSql();
  const rows = await query<{ status: string; n: number }[]>(
    sql`SELECT status, count(*)::int AS n FROM decisions GROUP BY status`,
  );
  const out: StatusCounts = {};
  for (const r of rows) out[r.status] = r.n;
  return out;
}

export async function getSlotsByIds(ids: string[]): Promise<LinkSlot[]> {
  if (!ids.length) return [];
  const sql = getSql();
  return query<LinkSlot[]>(
    sql`SELECT id, site, article_id, article_title, block_id, block_type, slot_type,
               role, anchor_text, url, target_url, surrounding_sentence, regions,
               protected, status
        FROM link_slots WHERE id = ANY(${ids})`,
  );
}

/** Latest check per slot (the detection evidence chain for a card). */
export async function getLatestChecks(slotIds: string[]): Promise<SlotCheck[]> {
  if (!slotIds.length) return [];
  const sql = getSql();
  const rows = await query<SlotCheckRow[]>(
    sql`SELECT DISTINCT ON (slot_id) slot_id, l1_status, l1_redirect_chain,
               l2_verdict, l2_evidence, final_verdict, checked_at
        FROM slot_checks WHERE slot_id = ANY(${slotIds})
        ORDER BY slot_id, checked_at DESC`,
  );
  return rows.map(rowToCheck);
}

export async function getDecisionWithEvidence(
  id: string,
): Promise<DecisionWithEvidence | null> {
  const decision = await getDecision(id);
  if (!decision) return null;
  const [slots, checks] = await Promise.all([
    getSlotsByIds(decision.affected_slot_ids),
    getLatestChecks(decision.affected_slot_ids),
  ]);
  return { decision, slots, checks };
}

export async function listAudit(limit = 100, event?: string): Promise<AuditRow[]> {
  const sql = getSql();
  // Optional event-type filter (e.g. ?event=steering_cancel) so a specific trail
  // stays reachable once the append-only log grows past the page window.
  const filter = event && /^[a-z_]{3,40}$/.test(event) ? event : undefined;
  if (filter) {
    return query<AuditRow[]>(
      sql`SELECT id, ts, agent, event, payload FROM audit_log
          WHERE event = ${filter}
          ORDER BY ts DESC, id DESC LIMIT ${limit}`,
    );
  }
  return query<AuditRow[]>(
    sql`SELECT id, ts, agent, event, payload FROM audit_log
        ORDER BY ts DESC, id DESC LIMIT ${limit}`,
  );
}

// --------------------------------------------------------------------------- //
// writes — decision status transitions ONLY (guarded, pending-scoped)
// --------------------------------------------------------------------------- //
export async function approveDecision(id: string): Promise<boolean> {
  assertBoardWritable();
  const sql = getSql();
  const rows = await query<{ id: string }[]>(
    sql`UPDATE decisions SET status = 'approved', decided_at = now()
        WHERE id = ${id} AND status = 'pending' RETURNING id`,
  );
  return rows.length > 0;
}

export async function rejectDecision(id: string, reason = ""): Promise<boolean> {
  assertBoardWritable();
  const sql = getSql();
  const rows = await query<{ id: string }[]>(
    sql`UPDATE decisions SET status = 'rejected', decided_at = now(),
               reject_reason = ${reason || null}
        WHERE id = ${id} AND status = 'pending' RETURNING id`,
  );
  return rows.length > 0;
}

export interface BatchResult {
  requested: number;
  changed: number;
}

/** Approve or reject many pending cards at once (README: "batch-approve low-risk"). */
export async function batchDecide(
  ids: string[],
  action: "approve" | "reject",
  reason = "",
): Promise<BatchResult> {
  if (!ids.length) return { requested: 0, changed: 0 };
  assertBoardWritable();
  const sql = getSql();
  const rows =
    action === "approve"
      ? await query<{ id: string }[]>(
          sql`UPDATE decisions SET status = 'approved', decided_at = now()
              WHERE id = ANY(${ids}) AND status = 'pending' RETURNING id`,
        )
      : await query<{ id: string }[]>(
          sql`UPDATE decisions SET status = 'rejected', decided_at = now(),
                     reject_reason = ${reason || null}
              WHERE id = ANY(${ids}) AND status = 'pending' RETURNING id`,
        );
  return { requested: ids.length, changed: rows.length };
}

// --------------------------------------------------------------------------- //
// weekly report — live aggregates over the last N days (pe3 mirrors this SQL)
// --------------------------------------------------------------------------- //
export async function weeklyStats(days = 7): Promise<WeeklyStats> {
  const sql = getSql();
  const since = new Date(Date.now() - days * 86_400_000).toISOString();

  const [byStatus, byAction, auditEvents, healed, decided] = await Promise.all([
    query<{ status: string; n: number }[]>(
      sql`SELECT status, count(*)::int AS n FROM decisions
          WHERE created_at >= ${since}::timestamptz GROUP BY status`,
    ),
    query<{ action: string | null; n: number }[]>(
      sql`SELECT proposal::jsonb ->> 'action' AS action, count(*)::int AS n
          FROM decisions WHERE created_at >= ${since}::timestamptz GROUP BY 1`,
    ),
    query<{ event: string; n: number }[]>(
      sql`SELECT event, count(*)::int AS n FROM audit_log
          WHERE ts >= ${since}::timestamptz GROUP BY event`,
    ),
    query<{ links_healed: number; slots: number }[]>(
      sql`SELECT count(*)::int AS links_healed,
                 COALESCE(sum(jsonb_array_length(affected_slot_ids::jsonb)), 0)::int AS slots
          FROM decisions WHERE status = 'applied'
            AND decided_at >= ${since}::timestamptz`,
    ),
    query<{ n: number }[]>(
      sql`SELECT count(*)::int AS n FROM decisions
          WHERE decided_at >= ${since}::timestamptz
            AND status IN ('approved', 'rejected', 'applied')`,
    ),
  ]);

  const toRecord = (rs: { [k: string]: string | number | null }[], key: string) => {
    const out: Record<string, number> = {};
    for (const r of rs) out[String(r[key] ?? "unknown")] = Number(r.n ?? 0);
    return out;
  };

  return {
    window_days: days,
    generated_at: new Date().toISOString(),
    by_status: toRecord(byStatus, "status"),
    by_action: toRecord(byAction, "action"),
    audit_events: toRecord(auditEvents, "event"),
    links_healed: healed[0]?.links_healed ?? 0,
    slots_affected_by_applied: healed[0]?.slots ?? 0,
    decisions_created: byStatus.reduce((a, r) => a + Number(r.n ?? 0), 0),
    decisions_decided: decided[0]?.n ?? 0,
  };
}
