/**
 * Types for the EverLink decision board, mirroring the Python `everlink.model`
 * Pydantic schemas and the spec §5 tables. Two shapes per persisted entity:
 *   - `*Row`  = exactly what Postgres returns (JSON columns arrive as TEXT).
 *   - domain  = the parsed shape the UI consumes (JSON columns decoded).
 *
 * Keeping these in sync with everlink/model.py is what lets the board (TS) and the
 * agent (Python) share ONE durable decision queue without an ORM in between.
 */

export type Action =
  | "REPLACE_URL"
  | "REWRITE_ANCHOR"
  | "REWRITE_SENTENCE"
  | "DROP_BLOCK"
  | "ESCALATE_HUMAN";

export type RiskLevel = "low" | "medium" | "high";

export type DecisionStatus =
  | "pending"
  | "approved"
  | "rejected"
  | "expired"
  | "applied";

export type Verdict =
  | "healthy"
  | "dead"
  | "offer_changed"
  | "program_ended"
  | "needs_human_recheck";

export type SlotType = "commercial" | "reference" | "internal" | "component";

/** Judge structured output (spec §6). */
export interface Proposal {
  action: Action;
  new_url?: string | null;
  new_anchor?: string | null;
  new_sentence?: string | null;
  rationale: string;
  risk_level: RiskLevel;
}

/** A surfaced decision card (spec §5 `decisions`), parsed. */
export interface Decision {
  id: string;
  affected_slot_ids: string[];
  proposal: Proposal;
  status: DecisionStatus;
  reject_reason?: string | null;
  created_at?: string | null;
  decided_at?: string | null;
}

/** Raw `decisions` row: JSON columns are TEXT until parsed. */
export interface DecisionRow {
  id: string;
  affected_slot_ids: string;
  proposal: string;
  status: DecisionStatus;
  reject_reason: string | null;
  created_at: string | null;
  decided_at: string | null;
}

/** One outbound link location (spec §5 `link_slots`). */
export interface LinkSlot {
  id: string;
  site: string;
  article_id: string;
  article_title: string;
  block_id: string;
  block_type: string;
  slot_type: SlotType;
  role?: string | null;
  anchor_text?: string | null;
  url: string;
  target_url?: string | null;
  surrounding_sentence?: string | null;
  regions?: string | null;
  protected: number;
  status: string;
}

export interface RedirectHop {
  url: string;
  status: number;
}

/** Latest probe outcome for a slot (spec §5 `slot_checks`), parsed. */
export interface SlotCheck {
  slot_id: string;
  l1_status?: number | null;
  redirect_chain: RedirectHop[];
  l2_verdict?: string | null;
  l2_evidence?: string | null;
  final_verdict: Verdict;
  checked_at?: string | null;
}

/** Raw `slot_checks` row (redirect chain is JSON TEXT). */
export interface SlotCheckRow {
  slot_id: string;
  l1_status: number | null;
  l1_redirect_chain: string | null;
  l2_verdict: string | null;
  l2_evidence: string | null;
  final_verdict: Verdict;
  checked_at: string | null;
}

/** Append-only audit trail row (spec §5 `audit_log`). */
export interface AuditRow {
  id: number;
  ts: string;
  agent: string;
  event: string;
  payload: string | null;
}

/** A decision card joined with the slots it affects + their latest evidence. */
export interface DecisionWithEvidence {
  decision: Decision;
  slots: LinkSlot[];
  checks: SlotCheck[];
}

/** Live-computed weekly summary (the board's report view; pe3 mirrors this SQL). */
export interface WeeklyStats {
  window_days: number;
  generated_at: string;
  by_status: Record<string, number>;
  by_action: Record<string, number>;
  audit_events: Record<string, number>;
  links_healed: number;
  slots_affected_by_applied: number;
  decisions_created: number;
  decisions_decided: number;
}

/** Status counts across the whole queue (the inbox header). */
export type StatusCounts = Record<string, number>;
