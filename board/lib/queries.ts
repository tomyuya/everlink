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
  BoardSettings,
  CronOverview,
  Decision,
  DecisionRow,
  DecisionStatus,
  DecisionWithEvidence,
  LinkSlot,
  NightlyRunRow,
  Proposal,
  RedirectHop,
  RotationRow,
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

// --------------------------------------------------------------------------- //
// control plane — settings row + cron ledger (the board /settings page)
//
// The agent's nightly cron treats the `settings` row as its control plane and
// writes one `nightly_runs` row per fire (a full run OR an honest heartbeat
// skip). The board reads both and writes ONLY via the two guarded mutators
// below, each audited into `audit_log` like every other board write.
// --------------------------------------------------------------------------- //
export const DEFAULT_SETTINGS: BoardSettings = {
  rotation_cycle_days: 30,   // full-pass window: every active slot probed once
  run_hour_utc: 3,           // which hourly heartbeat actually runs the chain
  enabled: true,             // kill-switch for the cron
  run_requested_at: null,    // board "run now" request, consumed by the next fire
  run_requested_by: null,
};

/** Liveness floor (minutes) AND the on-demand threshold. A fire older than the
 * cadence-aware window (see cronOverview) means the Railway heartbeat is missing;
 * and only a cron ticking at least this often can pick up a Run-now within the
 * hour. The window itself widens to 1.5 × the cron's real period, so a healthy
 * DAILY cron is no longer flagged dead for 23h a day. */
export const HEARTBEAT_WINDOW_MIN = 75;

/** Cold-start grace (minutes) when the cadence is not yet learnable (<2 Railway
 * fires). A single [railway] row already proves the cron is wired and firing, and
 * we cannot yet tell hourly from daily — so bridge ONE daily gap instead of
 * false-alarming a healthy daily cron on its first day. An hourly cron resolves its
 * real cadence at the very next fire (within the hour), so this grace is short-lived
 * for the case that actually needs the strict floor. */
export const HEARTBEAT_UNKNOWN_WINDOW_MIN = 25 * 60;

/** Ledger rows the page shows: recent fires (liveness) + recent real runs. */
const LEDGER_FIRE_ROWS = 12;
const LEDGER_RUN_ROWS = 6;

const SETTINGS_KEYS = [
  "rotation_cycle_days", "run_hour_utc", "enabled",
  "run_requested_at", "run_requested_by", "updated_at", "updated_by",
] as const;

function parseSettings(raw: string | null): BoardSettings {
  const out: BoardSettings = { ...DEFAULT_SETTINGS };
  if (!raw) return out;
  const stored = safeJsonParse<Record<string, unknown>>(raw, {});
  for (const k of SETTINGS_KEYS) {
    if (k in stored) (out as unknown as Record<string, unknown>)[k] = stored[k];
  }
  return out;
}

/** The single 'main' settings row merged over defaults (missing row = defaults). */
export async function getSettings(): Promise<BoardSettings> {
  const sql = getSql();
  const rows = await query<{ value: string }[]>(
    sql`SELECT value FROM settings WHERE id = 'main'`,
  );
  return parseSettings(rows[0]?.value ?? null);
}

async function writeSettings(
  next: BoardSettings,
  event: string,
  by: string,
  extra: Record<string, unknown>,
): Promise<void> {
  const sql = getSql();
  await sql`INSERT INTO settings (id, value, updated_at)
            VALUES ('main', ${JSON.stringify(next)}, now())
            ON CONFLICT (id) DO UPDATE
              SET value = EXCLUDED.value, updated_at = now()`;
  await sql`INSERT INTO audit_log (agent, event, payload)
            VALUES ('board', ${event}, ${JSON.stringify({ by, ...extra, to: next })})`;
}

/**
 * PATCH-equivalent for the operator knobs. Validation lives in the API route;
 * this mirrors the Python `db.set_settings` read-modify-write and audits it.
 */
export async function updateSettings(
  patch: Partial<Pick<BoardSettings, "rotation_cycle_days" | "run_hour_utc" | "enabled">>,
  by: string,
): Promise<BoardSettings> {
  assertBoardWritable();
  const current = await getSettings();
  const next: BoardSettings = {
    ...current,
    ...patch,
    updated_at: new Date().toISOString(),
    updated_by: by,
  };
  await writeSettings(next, "settings_change", by, { from: current });
  return next;
}

/** Board "run now": stamps a request the NEXT cron fire consumes and clears. */
export async function requestRun(by: string): Promise<BoardSettings> {
  assertBoardWritable();
  const current = await getSettings();
  const next: BoardSettings = {
    ...current,
    run_requested_at: new Date().toISOString(),
    run_requested_by: by,
    updated_at: new Date().toISOString(),
    updated_by: by,
  };
  await writeSettings(next, "run_requested", by, {});
  return next;
}

/** A ledger row's `reason` is `[origin] verdict` — written by nightly.py's `tag_reason`.
 *
 * Why the tag exists: without it a bare `python scripts/nightly.py` on a laptop
 * writes a row byte-identical to a Railway cron fire, and /settings duly reported
 * one such rehearsal as "last cron fire 2026-09-06 08:13:15" while the real cron
 * had never fired once. Filtering on trigger text (`--force`) only ever caught the
 * rows that admitted to being manual; attribution has to come from the process
 * that wrote the row, not from a guess made afterwards.
 *
 * Untagged rows (written before the tag landed) parse to origin "unknown" and are
 * NOT counted as fires: liveness fails towards "not proven", never towards a false
 * green that would unlock Run now on the strength of a laptop rehearsal.
 */
export type LedgerOrigin = "railway" | "local" | "unknown";

export interface LedgerReason {
  origin: LedgerOrigin;
  /** The verdict with the machine tag stripped — what a human should read. */
  text: string;
}

const ORIGIN_TAG = /^\[(railway|local)\]\s*/i;

export function parseLedgerReason(reason: string | null | undefined): LedgerReason {
  const raw = (reason ?? "").trim();
  const match = ORIGIN_TAG.exec(raw);
  if (!match) return { origin: "unknown", text: raw };
  return {
    origin: match[1].toLowerCase() as LedgerOrigin,
    text: raw.slice(match[0].length),
  };
}

/** True only for a row the Railway cron itself wrote. */
function isCronFire(row: NightlyRunRow): boolean {
  return parseLedgerReason(row.reason).origin === "railway";
}

/** Median of a numeric sample (robust centre: one outlier can't drag it). */
function median(xs: number[]): number {
  const s = [...xs].sort((a, b) => a - b);
  const mid = s.length >> 1;
  return s.length % 2 ? s[mid] : (s[mid - 1] + s[mid]) / 2;
}

/** The cron ledger + liveness: is the Railway heartbeat actually ticking?
 *
 * An hourly cron logs ~23 heartbeat skips a day, so `runs` merges the newest
 * fires with the newest REAL runs: a fire-only window would push the last full
 * run off the page within hours and /settings could no longer answer "did it
 * run?". `fires` stays fire-only because liveness must count every tick — but
 * only the platform-driven ones (see isCronFire), never a laptop rehearsal.
 *
 * Liveness is CADENCE-AWARE: the window is inferred from the observed gap between
 * Railway fires (period_min), so a healthy daily cron reads alive all day instead
 * of going red for 23h — the false alarm that made /settings look permanently
 * broken. Run-now is gated separately (run_now_available) because "is the cron
 * healthy?" and "can it honour an on-demand run within the hour?" are different
 * questions a single hardcoded 75-min check used to conflate.
 */
export async function cronOverview(): Promise<CronOverview> {
  const sql = getSql();
  const [fires, realRuns] = await Promise.all([
    query<NightlyRunRow[]>(
      sql`SELECT id, kind, status, reason, started_at, finished_at, summary
          FROM nightly_runs ORDER BY started_at DESC LIMIT ${LEDGER_FIRE_ROWS}`,
    ),
    query<NightlyRunRow[]>(
      sql`SELECT id, kind, status, reason, started_at, finished_at, summary
          FROM nightly_runs WHERE kind = 'run'
          ORDER BY started_at DESC LIMIT ${LEDGER_RUN_ROWS}`,
    ),
  ]);
  const merged = new Map<number, NightlyRunRow>();
  for (const r of [...fires, ...realRuns]) merged.set(r.id, r);
  // Compare by epoch ms, NOT by string: neon hands timestamptz back as Date
  // objects even though the row type says string, so localeCompare() would throw
  // (and the page would fall back to its "schema missing" branch).
  const rows = [...merged.values()]
    .sort(
      (a, b) => new Date(b.started_at).getTime() - new Date(a.started_at).getTime(),
    )
    .slice(0, LEDGER_FIRE_ROWS);
  const cronFires = fires.filter(isCronFire);
  const lastCronFire = cronFires[0] ?? null;
  const lastCronFireMs = lastCronFire
    ? new Date(lastCronFire.started_at).getTime()
    : null;
  // Infer the cron's REAL period from the gap between consecutive Railway fires
  // instead of assuming hourly. `cronFires` is newest-first (fires came back
  // ORDER BY started_at DESC), so each adjacent pair is one tick interval. Median
  // — not mean — so a single missed fire or a hand-forced extra run cannot skew
  // it: a daily cron yields ~1440 min, an hourly one ~60.
  const fireMs = cronFires.map((r) => new Date(r.started_at).getTime());
  const gapsMin: number[] = [];
  for (let i = 0; i + 1 < fireMs.length; i++) {
    const gap = (fireMs[i] - fireMs[i + 1]) / 60_000;
    if (gap > 0) gapsMin.push(gap);
  }
  const periodMin = gapsMin.length ? median(gapsMin) : null;
  // Liveness window: 1.5 × the real period, never stricter than the 75-min floor.
  // A healthy daily cron (period 1440) stays alive for 36h — long enough to bridge
  // its next 24h fire — so it reads GREEN all day, yet still flips RED if a daily
  // fire is actually missed. An hourly cron (period 60) behaves as before.
  // Cold start (<2 Railway fires => period unknown) gets a one-day grace instead of
  // the 75-min floor: a single [railway] row already proves the cron is wired, and
  // assuming hourly there would false-alarm a daily cron on its very first day.
  const windowMs =
    periodMin !== null
      ? Math.max(HEARTBEAT_WINDOW_MIN * 60_000, periodMin * 1.5 * 60_000)
      : HEARTBEAT_UNKNOWN_WINDOW_MIN * 60_000;
  const heartbeatAlive =
    lastCronFireMs !== null && Date.now() - lastCronFireMs <= windowMs;
  // Run-now needs a fire SOON, which only a CONFIRMED sub-hourly-ish cadence can
  // promise. An UNKNOWN cadence stays locked (honest: one fire is not yet proof it
  // fires often enough), and a confirmed daily cadence stays locked too (the
  // request would sit until the next 03:00). Both point at the hourly switch.
  const runNowAvailable =
    heartbeatAlive && periodMin !== null && periodMin <= HEARTBEAT_WINDOW_MIN;
  return {
    runs: rows,
    fires,
    last_fire_at: lastCronFire?.started_at ?? null,
    period_min: periodMin,
    heartbeat_alive: heartbeatAlive,
    run_now_available: runNowAvailable,
    last_run: realRuns[0] ?? null,
  };
}

/** Per-site rotation coverage inside the current cycle window. */
export async function rotationCoverage(cycleDays: number): Promise<RotationRow[]> {
  const sql = getSql();
  const cutoff = new Date(Date.now() - cycleDays * 86_400_000).toISOString();
  return query<RotationRow[]>(
    sql`SELECT site,
               count(*) FILTER (WHERE status = 'active')::int AS active,
               count(*) FILTER (WHERE status = 'active'
                                  AND last_checked_at >= ${cutoff}::timestamptz)::int AS covered,
               count(*) FILTER (WHERE status = 'active'
                                  AND last_checked_at IS NOT NULL)::int AS checked,
               min(last_checked_at) FILTER (WHERE status = 'active') AS oldest
        FROM link_slots GROUP BY site ORDER BY site`,
  );
}
