# EverLink · Decision Board

The minimal human-in-the-loop screen for EverLink. The agent detects and fixes link rot
autonomously; **this board is the only place a human is asked to step in** — to approve or
reject the small set of fixes risky enough to need a decision.

Built for Phase D of the AWS *Agents for Humans* hackathon (spec §6, Interrupt).

## What it is

A standalone **Next.js 16 (App Router) + React 19 + Tailwind 4** app that talks directly to
EverLink's **own** Neon Postgres via `@neondatabase/serverless`. There is **no ORM and no
extra backend**: the board and the Python agent are two views of **one durable decision
queue** (`decisions` table), so the async interrupt track works end to end:

```
scan (Python)  ──enqueue pending──▶  decisions table  ◀──approve/reject──  board (TS)
                                              │
                                              ▼  claim approved (FOR UPDATE SKIP LOCKED)
                                        worker (Python) ──apply──▶ writer (pe1) ──mark applied──▶
```

The board's SQL in [`lib/queries.ts`](lib/queries.ts) **mirrors** `everlink.queue.DbDecisionStore`
exactly (same columns, same `WHERE status = 'pending'` scoping; the board lists
newest-first via `ORDER BY created_at DESC`, while the worker queue consumes FIFO). The GET `/api/decisions` response `{ counts, decisions }` is the same shape the Python
CLI's `decisions --json` emits — the board and the CLI are interchangeable clients.

## Pages

| Route | Purpose |
| --- | --- |
| `/` | **Home** — the one product page: hero + positioning badges (open-source MIT / self-hosted / not-a-SaaS), the six-stage pipeline diagram (Scan → Detect → Judge → You decide → Apply → Report), the Automation panel (live schedule, rotation budget, cron heartbeat state, entrypoint commands), the two feed paths, the write-safety boundary + deployer contract, and the dogfooding honesty note. Every DB read is optional, so it renders in full with no DB configured. Absorbed the old `/how-it-works`, which now 308-redirects here. |
| `/inbox` | **Inbox** — the working queue: filterable card list (pending/approved/applied/rejected/all) with multi-select + **batch approve/reject**; `?status=` deep-links each filter tab. |
| `/decision/[id]` | **Card detail** — the proposal, its rationale, and the full **evidence chain** (slot → L1 HTTP probe → redirect chain → L2 verdict → final verdict), plus single-card approve/reject. |
| `/audit` | **Audit trail** — the append-only `audit_log`, newest first. `?event=<type>` filters to one event type (e.g. `?event=steering_cancel`, `write`, `verify`, `rollback`, `dead_letter`) with a filter chip showing the row count and a *clear filter* link — the log outgrows the page window once nightly `tool_result` traffic piles up. |
| `/report` | **Weekly report** — live aggregates (links healed, slots fixed, decisions by status/action, audit events) over a 7/14/30-day window. pe3's scheduled digest reports these same numbers. |
| `/settings` | **Control plane** — rotation cycle + per-site coverage/daily-budget table, run hour (UTC), cron kill-switch, run-now (locked until a live cron heartbeat proves the Railway wiring), the precondition checklist with the one-time Railway steps, and the cron ledger. |

## API routes

| Method & path | Body / query | Effect |
| --- | --- | --- |
| `GET /api/decisions` | `?status=&limit=` | `{ counts, decisions }` |
| `POST /api/decisions` | `{ ids[], action, reason? }` | batch decide → `{ ok, requested, changed }` |
| `GET /api/decisions/[id]` | — | card + slots + latest checks |
| `PATCH /api/decisions/[id]` | `{ action, reason? }` | single decide → `409` if not pending |
| `GET /api/audit` | `?limit=` | `{ audit }` |
| `GET /api/report` | `?days=` | `WeeklyStats` |
| `POST /api/settings` | `{ rotation_cycle_days?, run_hour_utc?, enabled? }` | patch the control plane → `400` on an empty/invalid patch, `403` read-only |
| `POST /api/settings/run-now` | — | stamp a run-now request for the next cron fire → `409` while no cron heartbeat is alive |

## Safety

- **Reads**: `decisions`, `slot_checks`, `audit_log`, `link_slots`, `settings`, `nightly_runs` —
  EverLink's own operational tables.
- **Writes**: two kinds, both audited. A decision **status transition**
  (`pending → approved | rejected`), always scoped `WHERE status = 'pending'` so a
  stale/double click can never re-decide a settled card; and the **control plane**
  (the single `settings` row, plus a `run_requested` stamp the next cron fire consumes),
  each written with an `audit_log` row (`settings_change` / `run_requested`). The board
  **never** writes source content and **never** runs DDL.
- **Guard**: every write calls `assertBoardWritable()` ([`lib/db.ts`](lib/db.ts)), mirroring the
  Python `db._assert_writable` deny-list — a DSN whose host matches `EVERLINK_FORBIDDEN_HOSTS`
  is refused with `403` before any SQL runs. The board does not hold the source-site DSNs.
- **Read-only demo mode**: set `NEXT_PUBLIC_BOARD_READONLY=1` to serve the board as a public
  view with all decision buttons disabled.

## Setup

```bash
cd board
cp .env.example .env.local      # then set EVERLINK_DATABASE_URL to EverLink's own Postgres
npm install
npm run dev                     # http://localhost:3000
```

### Environment

| Var | Required | Notes |
| --- | --- | --- |
| `EVERLINK_DATABASE_URL` | yes (at runtime) | EverLink's **own** Neon/Postgres DSN. `DATABASE_URL` is accepted as a fallback. |
| `EVERLINK_FORBIDDEN_HOSTS` | recommended | Comma-separated deny-list of host fragments the board must never write to. |
| `NEXT_PUBLIC_BOARD_READONLY` | no | `1` = disable all decision writes (public demo view). |

The DB client is built **lazily** (`getSql()` on first request), so `tsc --noEmit` and
`next build` succeed with **no database configured**. Every page is `force-dynamic` and
wraps its queries in try/catch, rendering an honest "Database unavailable" state instead of
crashing when the DSN is missing.

## Build gate

```bash
npm run typecheck   # tsc --noEmit  → zero errors
npm run build       # next build    → zero errors
```

Next 16 no longer runs ESLint during `next build` (the config key was removed); the gate
for this board is **type + compile correctness** — `tsc --noEmit` plus `next build`, which
type-checks by default.

## Honesty note

This board renders whatever is in the decision queue. With no seeded data it shows empty
states — that is expected, not a bug. To see it populated, run a scan
(`python -m everlink scan`) or the demo seed script (`python scripts/seed_demo.py`)
against EverLink's own database. The board never fabricates decisions, evidence, or metrics.
