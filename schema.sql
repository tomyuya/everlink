-- EverLink operational schema (PostgreSQL / Neon)
-- Source of truth: spec §5. Idempotent — safe to re-run.
--
-- IMPORTANT: these tables live in EverLink's OWN database
-- (EVERLINK_DATABASE_URL). They MUST NOT be created in any source site's
-- production database — those are read-only for this project. The three source
-- sites are accessed read-only; the only writes EverLink performs are (a) into
-- these tables and (b) gated content write-back (Phase E), which targets a
-- non-production / test instance of the write-back site.

BEGIN;

CREATE TABLE IF NOT EXISTS link_slots (
  id TEXT PRIMARY KEY,                   -- '{site}:{article_id}:{block_id}:{idx}'
  site TEXT NOT NULL,                    -- aethelgem | sandcart | hotdeals
  article_id TEXT NOT NULL,
  article_title TEXT NOT NULL,
  block_id TEXT NOT NULL,
  block_type TEXT NOT NULL,              -- product_card | paragraph | cta_box | product_entry | ...
  slot_type TEXT NOT NULL,               -- commercial | reference | internal | component
  role TEXT,                             -- core_recommendation | incidental | NULL (unjudged)
  anchor_text TEXT,
  url TEXT NOT NULL,
  target_url TEXT,                       -- after redirect resolution
  surrounding_sentence TEXT,
  regions TEXT,                          -- JSON array, e.g. ["us","ca","uk","es"]
  protected INTEGER NOT NULL DEFAULT 0,  -- 1 => disclosure-bearing, no write action allowed
  status TEXT NOT NULL DEFAULT 'active', -- active | stale | archived
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_slots_site_status ON link_slots(site, status);
CREATE INDEX IF NOT EXISTS idx_slots_url ON link_slots(url);

CREATE TABLE IF NOT EXISTS slot_checks (
  id BIGSERIAL PRIMARY KEY,
  slot_id TEXT NOT NULL REFERENCES link_slots(id) ON DELETE CASCADE,
  checked_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  l1_status INTEGER,                     -- final HTTP status
  l1_redirect_chain TEXT,                -- JSON array of {url, status}
  l2_verdict TEXT,                       -- ok | dead | price_anomaly | unavailable | blocked
  l2_evidence TEXT,
  final_verdict TEXT NOT NULL,           -- healthy | dead | offer_changed | program_ended | needs_human_recheck
  UNIQUE(slot_id, checked_at)
);
CREATE INDEX IF NOT EXISTS idx_checks_slot ON slot_checks(slot_id, checked_at DESC);

CREATE TABLE IF NOT EXISTS decisions (
  id TEXT PRIMARY KEY,                   -- decision card id
  affected_slot_ids TEXT NOT NULL,       -- JSON array (cross-article / cross-site merged card)
  proposal TEXT NOT NULL,                -- JSON: {action, new_url, new_anchor, new_sentence, rationale, risk_level}
  status TEXT NOT NULL DEFAULT 'pending',-- pending | approved | rejected | expired | applied
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  decided_at TIMESTAMPTZ,
  reject_reason TEXT
);
CREATE INDEX IF NOT EXISTS idx_decisions_status ON decisions(status, created_at DESC);

CREATE TABLE IF NOT EXISTS write_snapshots (
  id BIGSERIAL PRIMARY KEY,
  slot_id TEXT NOT NULL REFERENCES link_slots(id) ON DELETE CASCADE,
  decision_id TEXT NOT NULL REFERENCES decisions(id),
  before_json TEXT NOT NULL,
  after_json TEXT NOT NULL,
  applied_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  rolled_back_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_snap_slot ON write_snapshots(slot_id);

CREATE TABLE IF NOT EXISTS audit_log (
  id BIGSERIAL PRIMARY KEY,
  ts TIMESTAMPTZ NOT NULL DEFAULT now(),
  agent TEXT NOT NULL,
  event TEXT NOT NULL,                   -- tool_call | tool_result | steering_guide | steering_cancel | interrupt | write | rollback
  payload TEXT
);
CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit_log(ts DESC);

CREATE TABLE IF NOT EXISTS eval_runs (
  id BIGSERIAL PRIMARY KEY,
  run_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  case_id TEXT NOT NULL,
  expected TEXT NOT NULL,
  actual TEXT NOT NULL,
  passed BOOLEAN NOT NULL
);

COMMIT;
