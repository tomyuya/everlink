# EverLink — Deployment, Configuration & Operations Manual (EN)

> **Version**: 2026-09-06 (repo commit `0378739` and later on `main`)
> **Audience**: first-time deployers / day-to-day operators / hackathon reviewers
> **Repo**: https://github.com/tomyuya/everlink (MIT, open-source, self-hosted, **not a SaaS**)
> **Companion docs**: `README.md` (positioning & architecture), `DEPLOYMENT.md` (deployment runbook),
> `DEMO_SCRIPT.md` / `DEMO_RUNSHEET.md` (demo scripts), `docs/specs/` (design specs)
> **Chinese twin**: `EverLink 部署配置与使用操作手册.md` (same directory; on the board:
> `/docs` serves this English manual, `/docs/zh` serves the Chinese one).
> When the two diverge, the repo `board/content/` copies are the served source of truth.

---

## 0. How to read this manual

| Your goal | Jump to |
|---|---|
| Understand what it is and its safety model | §1 |
| Run it locally (no cloud) | §2 |
| Look up an env var / CLI flag | §3 / §4 |
| Put it in production (Neon + Vercel + Railway) | §5 |
| Connect your own website | §6 |
| Review cards day-to-day, read reports | §7 |
| Troubleshoot / avoid known traps | §8 / §9 / §10 |

---

## 1. EverLink in five minutes

### 1.1 One-sentence positioning

EverLink is an **autonomous link-rot steward**: a nightly cron scans your content sites'
outbound links, an LLM Judge proposes fixes, and **only the risky fixes** stop for a human
on the Decision Board. Approved fixes are executed by the Writer through a gated
snapshot → apply → re-probe → rollback-on-failure path. Humans approve risk; everything
else is autonomous — the core thesis of the AWS "Agents for Humans" hackathon.

> **Two ways to feed it (remember this first — don't let "two databases" mislead you into
> thinking you must wire up a DB)**: EverLink does **not** need access to your database to start.
> - **Path A · generic read-only crawl (the default, zero config)**: `scan --site <your
>   sitemap / page URL>` fetches public pages over read-only HTTP and extracts outbound
>   links live — **works with ANY website, no code change, L1/L2 detection needs zero AWS
>   credentials, never writes back**, honours robots.txt, ≤1 request per link, polite rate
>   limit. This is the default on-ramp for new users (details §6.1).
> - **Path B · first-party DB snapshot (optional, deep)**: read-only connect to **your own**
>   source DB (`<SITE>_DATABASE_URL` + `scripts/export_slots.py` → `data/slots_<site>.csv`)
>   in exchange for block-level slots and gated write-back (details §6.2).
>
> The "two-database model" below is about the **write-safety boundary** (whether you take A
> or B, EverLink writes only to its own store, never to a source site); the "source-site
> database" in it is **an optional part of path B**, not a prerequisite for using EverLink.

### 1.2 The two-database model (the most important safety boundary)

```
Source-site production DBs (AethelGem / FlashDeals / HotDeals)   EverLink's OWN DB (Neon Postgres)
┌────────────────────────────────────┐        ┌──────────────────────────────────┐
│ articles / products / links        │        │ link_slots      link mirror      │
│                                    │ READ-  │ slot_checks     per-run probes   │
│  EverLink NEVER writes here  ◄─────┼─ONLY───┤ decisions       card queue       │
│  (SET read_only = on after connect)│        │ audit_log       full trail       │
│                                    │        │ write_snapshots before/after     │
└────────────────────────────────────┘        └──────────────▲───────────────────┘
                                                             │ only write path (gated)
                                                    Writer: snapshot → apply → verify
                                                    → rollback + dead-letter on failure
```

Key points:
- Source-site DBs are **read-only forever** (`SET default_transaction_read_only = on`).
- Every EverLink write lands in **its own store**: write-back = update the `link_slots`
  mirror row + a before/after `write_snapshots` audit — **never** a source site's
  production database. Wiring a real CMS is an explicit non-goal.
- Write-back whitelist `WRITEBACK_SITES = ("aethelgem",)` (`everlink/writer.py`): sites
  outside it return `skipped` even when approved (not an error, not dead-lettered).
- **AethelGem / FlashDeals (internal key `sandcart`) / HotDeals are demo sample sites**
  operated by the maintainer: the public deployment patrols them as examples and their
  data only demonstrates the mechanics. Self-hosters connect **their own sites** (§6);
  the sample sites create no coupling whatsoever.
- Dual-side write guards: `db._assert_writable` (agent) and `assertBoardWritable` (board)
  refuse any write aimed at a source host or the deny-list (`EVERLINK_FORBIDDEN_HOSTS`).

### 1.3 The three-agent pipeline

`Scanner → Judge → Writer`, sequential and single-responsibility (not a Swarm):
1. **Scanner**: L1 HTTP probe (≤1 request per link) + selective L2 page parse (second
   fetch only for soft-404 suspects). **Detection needs no LLM.**
2. **Judge**: a Strands SDK agent producing fix proposals; spec §6 steering hooks block or
   re-steer unsafe proposals (audited as `steering_cancel`). Production backend =
   **qwen via Bedrock Mantle** (a real LLM).
3. **Writer**: handles **approved** cards only: snapshot → apply → verify (re-probe must be
   Healthy) → rollback + dead-letter to `rejected` on failure.

### 1.4 Decision-card lifecycle

```
scan finds a problem → Judge proposes → aggregated card [pending]
        ├─ human approves → [approved] → worker claims → write + re-probe ok → [applied]
        │                                              └─ re-probe fails → rollback → [rejected] (dead-letter)
        ├─ human rejects (reason recorded; the agent remembers) → [rejected]
        └─ recheck proves false positive → [rejected] (auto reason + false_positive_retired audit)
```
The **same dead link across articles** aggregates into **one card** — a human reviews it once.

### 1.5 Honesty labels (demo / asset context)

| Label | Meaning |
|---|---|
| `[REAL]` | produced by a real production run |
| `[SEEDED REPLAY]` | seeded demo data replay |
| `[EST.]` | estimate |

### 1.6 The six concepts you must know first

Learn these six and every command output and every board card becomes readable.

**① LinkSlot and its role**
One "outbound-link position to patrol": which site, which block of which article, the raw URL, and a **role** (deciding how it may be fixed):

| slot_type | Meaning | Fix constraint |
|---|---|---|
| `component` | product/component link (a clickable outbound link in body copy) | may REPLACE_URL / REWRITE |
| `commercial` | commercial/affiliate link (carries tracking) | fixable, but a redirect that drops the tag → `program_ended` |
| `reference` | citation/reference link | **never REPLACE_URL** (ScopePolicy hard-blocks; rewrite or escalate only) |
| `internal` | same-site internal link | generic adapter skips by default; `--include-internal` opts in |

**② The L1 / L2 detection pyramid (cheap first, expensive later)**
- **L1 (HTTP layer)**: ≤1 request per link; reads the status code + analyses the redirect chain. E.g. an affiliate redirect that **drops the tracking param** mid-hop → `program_ended` (you drove traffic for free).
- **L2 (page-parse layer)**: fetches the body incognito to see "price block gone / Currently unavailable / out of stock". **L2 is spent only when L1 is inconclusive.**
- No product APIs at all (PA-API / RapidAPI / RainForest are all retired). Blocked or timed-out → `needs_human_recheck`, **never fabricated**.

**③ The three vocabularies of a decision card**
A card = one **verdict** + one **action** + one **risk**; the state machine is in §1.4.

| verdict | action |
|---|---|
| `healthy` | `REPLACE_URL` — swap in a better link |
| `dead` | `REWRITE_ANCHOR` — rewrite the anchor text |
| `program_ended` | `REWRITE_SENTENCE` — rewrite the sentence to match the landing page |
| `offer_changed` | `DROP_BLOCK` — drop the block (incidental roles only) |
| `needs_human_recheck` | `ESCALATE_HUMAN` — hand back to a human (unsure / fix rolled back) |

> **Merge rule**: `merge_key = scheme+host+path` (tracking query and fragment ignored). The **same dead link across articles** merges into **one card**, represented by the group's **highest-risk** proposal (fail-safe); a human reviews once and one approval heals every affected slot.

**④ Steering guardrails (the creative core: what Evals measure = what prod blocks, zero drift)**
`policy.py` is the **single source of truth** — the Evals harness and the runtime hooks enforce the **same pure functions**, so a violation the evals catch is exactly one production blocks. Three **hard** rules + one write gate:

| Guardrail | Mechanism | Effect |
|---|---|---|
| **Disclosure zero-modification** (DisclosurePolicy) | three layers: structural immunity (block_type/role IS a disclosure block) / explicit `protected=1` / keyword regex (affiliate, commission, sponsored…); **any layer flags = protected** (fail-safe) | a protected slot may never be touched by any MODIFYING_ACTION — `ESCALATE_HUMAN` only |
| **Reference zero-repoint** (ScopePolicy) | `slot_type=reference` + `REPLACE_URL` → violation | reference links are never re-pointed |
| **Inconclusive = escalate only** (verification) | when `verdict=needs_human_recheck` (probe refused / accessibility unknown), the only legal action is `ESCALATE_HUMAN` | forbids mutating live content on an uncertain measurement — a probe limit never becomes a false edit |
| **Write gate** (WritePolicy, `steering.make_write_gate` hook) | any Writer write-tool call **must carry an approved `decision_id`**, else `BeforeToolCall` refuses | no approval, no write |

> `REWRITE_SENTENCE` also carries an **editorial constraint (EditorialPolicy)**: a rewrite must preserve or explicitly downgrade the original factual claims — enforced via the Judge prompt + high-risk routing to a human (a soft constraint, not an oracle hard-block). Guardrails are **ON** by default; `--no-enforce` disables them (not advised).

**⑤ The two Interrupt tracks (one write gate, two ways to "wait for a human")**
- **Sync gate (`make_sync_approval_gate`)**: for live demos. A high-risk proposal fires Strands' native `event.interrupt`, pausing the agent loop and surfacing in `AgentResult.interrupts`; the operator replies `A` to approve (anything else rejects), and `run_judge_sync` resumes.
- **Async durable queue (`DecisionWorker`)**: for production. Cards land in the `decisions` table; a human approves out-of-band (board / notifications); the worker polls `claim_next_approved` → dispatches the Writer → `mark_applied`.
- Both tracks gate the **same high-risk fix, sit behind the same write_gate, and share one `Proposal` schema** — an unapproved action can never reach a site.

**⑥ needs_human_recheck (honest degradation — EverLink's integrity)**
When a probe is blocked by an anti-bot wall, times out, or lacks evidence, it **does not guess a verdict**; it says "I'm not sure, a human should recheck" and raises an `ESCALATE_HUMAN` card. A scan coming back **all** `needs_human_recheck` usually means the target (e.g. Amazon) blocked L2 with a captcha — **correct degradation, not a bug** (use `--no-l2` for L1 only, or test a first-party sample site).

### 1.7 Safety guardrails at a glance (why it can't wreck your site)

Every guardrail below is **enforced in code**, not a verbal promise:

| Guardrail | Mechanism | Effect |
|---|---|---|
| **Source sites read-only** | `SET default_transaction_read_only = on` right after connecting | physically read-only against source DBs |
| **Write deny-list** | `db._assert_writable` checks the target DSN host: matching any source-connection var or `EVERLINK_FORBIDDEN_HOSTS` → raises `ProductionWriteRefused` | a production source instance can never be written, even by mistake |
| **Writes only to its own DB** | every write-back lands in EverLink's own `EVERLINK_DATABASE_URL` (mirror row + snapshot audit) | business DB and EverLink ops DB are physically isolated |
| **Three-layer disclosure protection** | see §1.6 DisclosurePolicy | compliance copy is structurally immune |
| **Write gate** | see §1.6 WritePolicy (hooks) | no approval = no write |
| **Snapshot + re-probe + rollback** | snapshot → apply → verify_fix; rollback + dead-letter on failure | a bad edit auto-reverts, leaving no dirty data |
| **Write-back whitelist** | `WRITEBACK_SITES = ("aethelgem",)`; outside it, even approved cards return `skipped` (not an error, not dead-lettered) | write-back scope is controlled and auditable |
| **Honest degradation** | blocked/timeout/insufficient evidence → `needs_human_recheck` | detection results are never fabricated |
| **Zero secrets in repo** | the repo ships only `.env.example`; real `.env` / credentials / exported CSVs are all gitignored | the public repo holds no secrets |

---

## 2. Local quick start

### 2.1 Prerequisites

- Python ≥ 3.11 (repo validated on 3.12), git
- Optional: a local Postgres (or a free Neon instance); **detection runs with zero AWS credentials**

### 2.2 Install

```bash
git clone https://github.com/tomyuya/everlink.git
cd everlink
python -m venv .venv && .venv\Scripts\activate        # Windows
pip install -e ".[dev]"                                # pytest / strands deps included
```

### 2.3 Minimal env

Copy `.env.example` → `.env`. **One variable is enough** for detection:

```ini
EVERLINK_DATABASE_URL=postgresql://user:pass@host/neondb?sslmode=require
```

The schema is created **idempotently on first connect** (`db.ensure_schema` reads
`schema.sql`) — no manual DDL. Without any DSN, `scan --dry-run` still works (pure
read-only report, nothing persisted).

> **Where does the source data come from?** `EVERLINK_DATABASE_URL` is EverLink's
> **own process ledger** (probe results / decision cards / audit) — **not a source-site
> database**. Monitored link data arrives via two paths, neither needing this variable:
> 1. **generic live crawl (the default path for new users)**: `scan --site <your sitemap /
>    page URL>` fetches the target site's public pages over read-only HTTP and extracts
>    outbound links on the fly — **no source-DB configuration at all** (§6.1);
> 2. **first-party CSV snapshots (the deep path)**: **the deployer themself** runs
>    `scripts/export_slots.py` against **their own** source DB (`<SITE>_DATABASE_URL` /
>    the env trio, used only at export time) to produce `data/slots_<site>.csv`; the three
>    CSVs committed to the repo are mirrors of the maintainer's demo sample sites (§6.2).
>
> In short: source data is always obtained by *you* from *your own site* (crawl or
> export); EverLink's own DB only records the process ledger.

### 2.4 First read-only scan

```bash
# any website, zero credentials, zero DB writes:
python -m everlink scan --site https://example.com/sitemap.xml --dry-run

# the repo's committed first-party snapshots (data/slots_*.csv):
python -m everlink scan --site aethelgem --dry-run --judge none
```

Success = a `scan report ... verdicts: {...}` block. Add `--judge mantle` only when you
have AWS credentials (§3.1).

### 2.5 Tests and offline gates

```bash
python -m pytest -q                                              # all green
python scripts/nightly.py --dry-run --judge none --skip-notify   # cron rehearsal, mutates nothing
python scripts/verify_bedrock.py                                 # with creds: Bedrock connectivity
python scripts/run_evals.py                                      # Strands Evals suite (spec §8)
```

### 2.6 Safest → most real: seven progressive practice scenarios

Start at **A** and work down; each step is a little more "real" than the last. Single entrypoint `python -m everlink <subcommand>` (repo root, venv active).

| Scenario | Command | What you see / note |
|---|---|---|
| **A Offline dry run** (safest: no writes, no notify, no AWS) | `python -m everlink scan --site aethelgem --limit 20 --judge stub --dry-run` | `stub` = offline deterministic fake model; `--dry-run` = write nothing |
| **B Real detection on one site** (still no writes) | `python -m everlink scan --site aethelgem --limit 50 --judge none --dry-run` | `none` = detection only, zero creds; Amazon et al. often hit anti-bot → honest `needs_human_recheck` (correct, not a bug); L2 ≈ 15–20s/link, add `--no-l2` to speed up |
| **C Scan any site/sitemap** (not limited to the three samples) | `python -m everlink scan --site https://any-site/sitemap.xml --limit 30 --judge none --dry-run` | goes through the generic read-only adapter (§6.1), zero code, zero creds |
| **D View the inbox** (needs `EVERLINK_DATABASE_URL` first) | `python -m everlink decisions --status pending` / `--json` | without a DSN it prints `unavailable` and exits 2 (a designed degradation, not a crash) |
| **E Approve/reject a card** | `python -m everlink decide dec-abc123 --approve` / `--reject --reason "disclosure block is protected"` | same `DecisionStore` as the board; the reject reason is remembered by the agent |
| **F Execute approved fixes** (worker write-back) | `python -m everlink worker --once` / `--once --handler null` (safe no-op: mark applied, write nothing) | per card: snapshot → apply → verify_fix re-probe; failure auto-rolls back + dead-letters + hands you an `ESCALATE_HUMAN` card |
| **G One-shot full auto** (what the production cron runs) | `python scripts/nightly.py` (offline smoke: `--dry-run --judge none`) | scan→notify→worker --once→(Monday) report; thin orchestration, no hidden logic, audit byte-identical to manual (§4.8) |

> Want the board to show something? `python scripts/seed_demo.py --dry-run` previews the plan; drop `--dry-run` to inject **[SEEDED REPLAY]** demo data (every row tagged `demo-seed`, cleanly removed with `--reset` without touching real data). An empty board is a **normal empty state**, not a bug.

---

## 3. Environment variable reference

### 3.1 Agent side (Railway / local)

| Variable | Required | Purpose & notes |
|---|---|---|
| `EVERLINK_DATABASE_URL` | ✅ | EverLink's **own** Neon pooled DSN; the board shares it |
| `AWS_REGION` | for Judge | production `us-east-1` |
| `BEDROCK_MODEL_ID` | for Judge=bedrock | direct Claude, e.g. `us.anthropic.claude-sonnet-4-6` |
| `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` | for Judge | or attach an IAM role; **never hardcode/commit** |
| `EVERLINK_JUDGE` | optional | `mantle` (**code-level default**: qwen via the Bedrock Mantle gateway, bypasses the account-level Anthropic allowlist gate) / `bedrock` (direct Claude) / `stub` (offline fixture) / `none` (detection only) |
| `BEDROCK_MANTLE_API_KEY` | optional | local/demo path: a console-minted key used verbatim as the OpenAI api_key; **production/IAM leaves it unset** = bearer tokens minted on demand (long jobs survive token expiry) |
| `BEDROCK_MANTLE_MODEL_ID` | optional | default `qwen.qwen3-next-80b-a3b-instruct` (**non-reasoning**; rationale in §8 trap 11) |
| `BEDROCK_MANTLE_REASONING` | optional | `reasoning_effort`; empty by default; set (e.g. `low`) only when switching to a reasoning model, accepting its multi-turn limits |
| `EVERLINK_NIGHTLY_SITES` | optional | default `aethelgem,sandcart,hotdeals` (the demo sample sites) |
| `EVERLINK_WEEKLY_DAY` | optional | weekday the weekly digest folds into the nightly; default `mon` |
| `EVERLINK_CRON_ORIGIN` | optional | `railway` = attribute ledger rows to the platform even if Railway's own `RAILWAY_*` vars are absent. The board counts ONLY `[railway]` rows as proof the cron is wired (`nightly.run_origin`), so a laptop rehearsal can never unlock *Run now* |
| `EVERLINK_FORBIDDEN_HOSTS` | optional | extra write deny-list (host fragments) |
| `RESEND_API_KEY` / `RESEND_FROM` / `EVERLINK_NOTIFY_EMAIL` | email push | **all three** must be set for the email channel to be active; otherwise delivery is honestly `skipped` |
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` | optional | second push channel |
| `EVERLINK_BOARD_URL` | recommended | board ROOT; notifications deep-link `/inbox`, `/decision/<id>`, `/report` |
| `<SITE>_PUBLIC_ORIGIN` | per site | required when a source DB stores internal links as bare relative paths (e.g. `SANDCART_PUBLIC_ORIGIN=https://…`); otherwise scheme-less URLs fail the SSRF guard and the whole site surfaces as false `needs_human_recheck`. Unset = left as-is, **never a guessed domain** |
| `AETHELGEM_/SANDCART_/HOTDEALS_DATABASE_URL` | export only | read-only source DSNs for `scripts/export_slots.py`; the nightly never uses them |
| `EVERLINK_AEG_ENV` / `EVERLINK_SANDCART_ENV` / `EVERLINK_HOTDEALS_ENV` | export only | absolute paths to each source project's **.env**; `export_slots.py` resolves DSNs from them at runtime (nothing hardcoded); blank = skip that site |
| `EVERLINK_FORCE` | optional | `1` = re-export even when the CSV already exists |
| `FIXTURE_PORT` | tests only | offline fixture server port, default 8787 |
| `EVERLINK_ALLOW_LOCALNET` | **never in prod** | `1` disables the SSRF guard's private-IP block; the fixture server sets it automatically; blank in production = full protection |
| `EVERLINK_HTTP_TRUST_ENV` | optional | `1` = probes/crawls trust system proxy env; default direct (truer signal, hermetic) |

> ⚠️ **Empty AWS-credential trap**: an *empty* `AWS_PROFILE=` / `AWS_ACCESS_KEY_ID=` still
> counts as "set" — botocore prefers the empty value over `~/.aws/credentials`. Symptom:
> `aws sts get-caller-identity` works but Mantle token minting fails with
> "Failed to mint Bedrock Mantle bearer token … Verify your AWS credentials".
> **Comment the lines out entirely** instead of leaving them empty.

### 3.2 Board side (Vercel)

| Variable | Required | Purpose & notes |
|---|---|---|
| `EVERLINK_DATABASE_URL` | ✅ | same Neon DSN as the agent (board reads + decision transitions only) |
| `EVERLINK_FORBIDDEN_HOSTS` | optional | same write guard as the agent |
| `NEXT_PUBLIC_BOARD_READONLY` | optional | `1` = public look-but-don't-touch view (hides checkboxes/buttons). **`NEXT_PUBLIC_` vars are inlined at build time**: adding/removing/changing requires a **rebuild** to take effect (§8 trap 2) |

### 3.3 Platform behaviour notes

- **Railway env names and values must not contain double quotes `"`** — Railpack fails with
  `secret ID missing for "" environment variable`.
- Paid Railway accounts **cannot deploy via CLI**: first deployment must be done in the
  Dashboard by connecting the GitHub repo.

---

## 4. CLI reference (`python -m everlink …`)

### 4.1 `scan` — discover + detect link rot (read-only)

```bash
python -m everlink scan --site <first-party key | page URL | sitemap URL> [flags]
```

| Flag | Default | Notes |
|---|---|---|
| `--site` | required | `aethelgem` / `sandcart` (FlashDeals) / `hotdeals` read CSV snapshots; **anything else** goes through the generic read-only adapter (sitemap / page / URL list auto-detected) |
| `--limit` | 25 | max slots to scan |
| `--rate-delay` | 1.0 | seconds between requests (politeness line — don't lower it) |
| `--timeout` | 15.0 | per-request timeout |
| `--no-l2` | off | L1 only, skip page parsing |
| `--judge` | `none` | `none`=detection only (zero creds) / `stub` / `bedrock` / `mantle` |
| `--no-enforce` | off | disable steering hooks (ON by default; they block/re-steer unsafe proposals) |
| `--dry-run` | off | **write nothing to any database** |
| `--max-pages` | generic:25 | generic adapter page cap |
| `--include-internal` | off | generic: also report same-host links |

Output: `verdicts` counts → problem list (L1 status / L2 verdict / evidence / proposal risk)
→ aggregated decision-card counts (high-risk = single-card approval, rest batchable).
Non-dry-run writes `slot_checks` + `audit_log` and idempotently enqueues pending cards
(**already-decided cards are never resurrected by a re-scan**).

### 4.2 `decisions` — inspect the queue (the board's read model)

```bash
python -m everlink decisions --status pending --limit 20
python -m everlink decisions --json        # same shape the board consumes
```
`--status`: `all|pending|approved|rejected|expired|applied` (default pending).

### 4.3 `decide` — approve/reject one card (CLI twin of the board buttons)

```bash
python -m everlink decide dec-abc123 --approve
python -m everlink decide dec-abc123 --reject --reason "disclosure block is protected"
```
Same `DecisionStore` transition as the board; the reject reason is remembered by the agent.

### 4.4 `recheck` — re-probe pending cards, retire proven false positives

```bash
python -m everlink recheck                      # default dry-run: prints what would retire
python -m everlink recheck --confirm 3 --apply  # retire only after 3 consecutive all-healthy
```
- A card retires only when **every slot re-probes Healthy**; any still-bad slot = real problem, left untouched.
- `--confirm N` counters bot-wall hosts (e.g. Amazon) that flip verdicts between probes;
  flipping cards are reported **UNSTABLE** and left for a human, never silently dropped.

### 4.5 `worker` — claim and execute approved cards (async Interrupt track)

```bash
python -m everlink worker --once                     # one poll then exit (what nightly uses)
python -m everlink worker --interval 5               # resident loop, Ctrl-C stops
python -m everlink worker --once --handler null      # safe no-op: mark applied, write nothing
```
`--handler writer` (default) = the real chain: snapshot → apply → verify (Healthy re-probe
required) → rollback + dead-letter to `rejected` on failure; fully audited. Writes only
EverLink's own mirror.

### 4.6 `notify` — push the queue to the operator (Resend email / Telegram)

```bash
python -m everlink notify --dry-run          # compose + print, zero network sends
python -m everlink notify                    # risk-routed: medium/high single-card, low batched
python -m everlink notify --brief            # morning digest
python -m everlink notify --channel email    # single channel
```
Delivery is reported honestly: `sent` (real 2xx) / `skipped` (no credentials) / `failed`
(4xx/5xx/transport). Every real push writes an `audit_log` `notify` row.

### 4.7 `report` — weekly report (the board /report numbers as a digest)

```bash
python -m everlink report --dry-run
python -m everlink report --json             # twin of /api/report
python -m everlink report --days 7
```
Python and the board `/report` run the **same five aggregates** — numbers never drift.

### 4.8 `scripts/nightly.py` — the full-chain cron entrypoint (the scheduler's ONE command)

Drives, in order, the **exact same subcommands** a human would (thin orchestration;
`plan_steps` is a pure, unit-tested function):

| Step | Content | Notes |
|---|---|---|
| 1 | `scan --site <each> --judge <backend>` | one pass per site; sources read-only |
| 2 | `notify` | pushes freshly surfaced cards; `--skip-notify` skips |
| 3 | `worker --once --handler writer` | drains human-approved cards; **honestly skipped under `--dry-run`** (it writes) |
| 4 | `report` | only when today = `--weekly-day` (default mon) or `--weekly` forces it |

**Honest degradation** (nothing faked): a step exiting 2 = degraded (e.g. Judge
unavailable → detection still ran) and the chain **continues**; a raised exception =
recorded as -1 and the chain continues (one bad site never kills the night); the summary
prints ok/degraded/FAIL/skip per step. Flags: `--sites` / `--judge` / `--limit` /
`--channel` / `--brief` / `--handler` / `--weekly` / `--weekly-day` / `--days` /
`--skip-notify` / `--skip-worker` / `--dry-run`.

### 4.9 Bundled scripts quick reference (`scripts/`)

| Script | Purpose |
|---|---|
| `nightly.py` | full-chain cron entrypoint (§4.8) |
| `export_slots.py` | read-only export of `data/slots_<site>.csv` (Phase-A; env trio points at source .env files) |
| `seed_demo.py` | demo/offline DB seeding (source of `[SEEDED REPLAY]` data) |
| `run_evals.py` | Strands Evals suite (spec §8; needs credentials) |
| `verify_bedrock.py` / `verify_strands.py` | credential / SDK connectivity checks |
| `fixture_server.py` | offline fixture site (port 8787; sets ALLOW_LOCALNET itself) |
| `check_links.py` / `scan_site.py` / `load_slots.py` | point troubleshooting tools |
| `discover_schema.py` / `probe_target_tables.py` | source-schema reconnaissance (read-only) |
| `probe_samples.py` / `probe_timing.py` | probe samples / timing baselines |

---

## 5. Production deployment

### 5.0 Topology

```
        nightly cron (Railway, 03:00 UTC)               human (email / Telegram)
                 │                                                 │
                 ▼                                                 ▼
   ┌───────────────────────────┐                    ┌──────────────────────────┐
   │ Railway service (Docker)  │  enqueue decisions │ Vercel: Next.js board    │
   │ python scripts/nightly.py │ ─────────────────► │ inbox / audit / report   │
   │  1 scan (Scanner→Judge)   │  (Neon Postgres)   │ approve / reject         │
   │  2 notify (Resend/TG)     │ ◄───────────────── │ (status transition only) │
   │  3 worker (apply+verify)  │  approved cards    └──────────────────────────┘
   │  4 report (Mon weekly)    │
   └───────────────────────────┘
                 │ Bedrock (Judge/Writer LLM)          Neon Postgres (us-east-1)
                 └──────────────────────────────────►  decisions / slot_checks /
                                                       audit_log / link_slots / snapshots
```

### 5.1 Neon database

1. Create a project at console.neon.tech, region **us-east-1** (matches the board's Vercel region).
2. Copy the **pooled** connection string (`…-pooler…?sslmode=require`) = `EVERLINK_DATABASE_URL`.
3. Schema self-creates idempotently on first connect; to apply explicitly:
   `psql "$EVERLINK_DATABASE_URL" -f schema.sql`.
4. It must be EverLink's **own** database — never a source site's production instance.

### 5.2 Vercel (the Decision Board)

The board lives in `board/` (its own Vercel project root; `board/vercel.json` pins the
framework + **iad1**).

**Git integration (recommended; what production uses)**: import the repo in the Vercel
dashboard → Root Directory = `board` → pushes to main go live. Env vars via dashboard or CLI:

```bash
vercel env add EVERLINK_DATABASE_URL production
vercel env add EVERLINK_FORBIDDEN_HOSTS production      # optional
vercel --prod
```

**Read-only switch**: `NEXT_PUBLIC_BOARD_READONLY=1` = public look-but-don't-touch view.
The production deployment **does not set it** = fully interactive (checkboxes, batch bar,
per-card Approve/Reject all live).
> ⚠️ `NEXT_PUBLIC_` vars are **inlined at build time**: after adding/removing one you must
> wait for a rebuild (push or manual Redeploy) — removing the env alone changes nothing.

### 5.3 Railway (the autonomous agent + cron)

Repo root = Railway service root; builds the `Dockerfile` (`railway.json` pins
`builder: DOCKERFILE`); image `CMD` = `python scripts/nightly.py` (runs once and exits —
exactly what a cron wants).

1. **Connect via Dashboard** (paid accounts cannot deploy via CLI): New Project →
   Deploy from GitHub repo → confirm Dockerfile builder → set Variables (§3.1 table).
2. **Cron MUST be set manually in the Dashboard** (the biggest trap of this project, §8 trap 1):
   Service → **Settings** →
   - `Cron Schedule` = Custom = `0 * * * *` (hourly heartbeat)
   - `Restart Policy` = **Never**
   - `Custom Start Command` = `python scripts/nightly.py`
   - optional Variable `EVERLINK_CRON_ORIGIN=railway` (see §3.1)
   After saving, the page shows the next run time.
   > The GATE, not the schedule, decides when the chain runs: an hourly cron logs ~23 honest
   > heartbeat skips a day and runs the chain only on the fire matching the board's run hour —
   > which is also what lets `/settings` → *Run now* be picked up within the hour. A daily
   > schedule set to the run hour (`0 3 * * *`) runs the chain as well, but leaves *Run now*
   > locked and the heartbeat precondition red for 23h a day. This production instance is
   > still on the daily `0 3 * * *` (`nextCronRunAt` 2026-09-07T03:00:00Z) — switching it to
   > hourly in the Dashboard is the one remaining manual step.
3. Trigger the chain by hand (without waiting for cron):
   ```bash
   railway run python scripts/nightly.py --dry-run --judge none   # safe rehearsal
   railway run python scripts/nightly.py                          # the real full chain
   ```

**Two observed platform behaviours**:
- `railway.json` is config-as-code (deprecated, supported until 2026-12-01): it applies to
  **that deployment only and never writes back to service settings**. The cronSchedule in
  the repo never took effect historically — the scheduler only honours Dashboard settings.
- Before cron was configured, **every deployment also ran one nightly** (notify included).
  Once cron IS configured a deployment is `buildOnly`: it rebuilds the image and starts
  nothing, and the next cron fire runs on that newest image. Verified 2026-09-06 — push at
  09:17:52Z, deploy `bd57dc6b` SUCCESS at 09:17:55Z with `buildOnly: true`, and no new
  `nightly_runs` row. So push-to-deploy is safe after the schedule is set.

**First-party scan data**: `data/slots_*.csv` are committed and `COPY`-baked into the image,
so a repo-based build patrols the demo sample slots out of the box. If your fork must not
carry site data in git: Railway volume at `/app/data` (recommended) / private prebuilt
image / pure generic zero-data mode.

### 5.4 Post-deploy validation checklist

```bash
cd board && npm run typecheck && npm run build          # board: zero errors
python -m pytest -q                                      # agent: all green
python -m everlink scan --site aethelgem --dry-run       # slot count matches the DB
python -m everlink decisions --json                      # the board's read model
python -m everlink report --json                         # /api/report twin
railway status --json | findstr nextCronRunAt            # cron scheduled (non-null)
```
Then open the Vercel URL → approve a card → `python -m everlink worker --once` → card goes
applied and `audit_log` gains write/verify rows = end-to-end闭环 (closed loop) proven.

---

## 6. Connecting sites

> **The three built-in sites (`aethelgem` / `sandcart` / `hotdeals`) are demo sample sites
> only** — the committed CSVs are public link mirrors of the maintainer's own sites so a
> fork sees the full pipeline out of the box; production self-hosting connects YOUR sites.

**There is no hardcoded site-count ceiling** (a site is just a string key; DB columns are
text; board labels fall back to the raw key). The real ceiling is runtime cost: the nightly
window (single container, serial, once a day) + Judge LLM cost + crawl politeness; the
current model's comfort zone is **tens of sites / tens of thousands of links**.

### 6.1 Generic zero-code onboarding (any site, today)

```bash
python -m everlink scan --site https://your-site.com/sitemap.xml --judge mantle
```
- Input auto-detected: sitemap (contains `sitemap` or ends `.xml`) / single page / URL list.
- Read-only crawl, **never writes back**, honours robots.txt (fail-open), descriptive UA,
  ≤1 request per link.
- Defaults: `max_pages=25`, `max_slots=500` per site, 1s between pages — the anti-ban
  etiquette line; don't raise it casually.
- L1/L2 detection needs zero AWS credentials; only Judge proposals need an LLM.

### 6.2 First-party deep onboarding checklist (CSV snapshots / block-level slots / write-back)

1. Add the key to `SITES` in `everlink/adapters.py`;
2. Add `<SITE>_PUBLIC_ORIGIN` (required for relative internal links) and
   `<SITE>_DATABASE_URL` (export only) to env;
3. Run `python scripts/export_slots.py` to produce `data/slots_<site>.csv` (URLs + flags only, no secrets);
4. (optional write-back) add the key to `WRITEBACK_SITES` in `everlink/writer.py` —
   **not adding it defaults to skipped, which is safe**;
5. Board needs zero changes (display-layer `SITE_LABEL` mapping; unknown keys fall back).

### 6.3 Naming note

Public copy uses brand names (e.g. FlashDeals); internal identifiers keep historical keys
(e.g. `sandcart`) — the board display layer already maps them. No physical rename (an
existing risk-vs-benefit decision).

---

## 7. Day-to-day operations & the board

### 7.1 Page guide (production: everlink-seven.vercel.app)

| Page | What to look at |
|---|---|
| `/` | the ONE product page: the four positioning badges (open-source MIT / self-hosted, not a SaaS / AWS Strands SDK + Bedrock / zero-config crawl of any site), the six-stage pipeline, the automation panel with its live schedule and the newest ledger run quoted verbatim — trigger and origin included, so a laptop rehearsal cannot be read as an unattended cron run — the two feed paths, the write-safety boundary + deployer contract. (`/how-it-works` was merged into it and now 308-redirects.) |
| `/docs` | this manual (English; `/docs/zh` for Chinese) |
| `/inbox` | the review battlefield: status tabs + checkboxes + batch Approve/Reject bar |
| `/decision/<id>` | one card: rationale, NEW SENTENCE, evidence chain (slot-level L1/L2), live Approve/Reject buttons (pending) or settled notice (decided) |
| `/audit` | full audit stream, filterable (`?event=write` / `verify` / `rollback` / `dead_letter` / `steering_cancel`…) |
| `/report` | weekly numbers (healed / created / decided), twin of CLI `report` |
| `/settings` | the control plane: rotation cycle + per-site coverage/budget, run hour (UTC), cron kill-switch, run-now (locked until a live cron heartbeat attributable to Railway — the ledger tags every row with its origin, so a run started on a laptop does not count), precondition checklist, cron ledger with an origin column |

### 7.2 Review workflow

1. Receive the email/Telegram push (medium/high single-card, low batched) → deep-link in.
2. Read the evidence chain: L1 status, L2 verdict, `Open in your browser` to verify
   yourself (the last line of defence against bot-wall misreads).
3. Approve (enters the worker queue) or Reject (fill a reason; the agent remembers).
4. Batch: tick several low-risk cards in the inbox → batch bar approves/rejects at once.
5. The next nightly's worker step executes approved cards; `/audit?event=write` and
   `?event=verify` each gain a row, the card goes applied, Evidence re-probes Healthy = loop closed.

### 7.3 Notifications & weekly report

- Nightly step 2 notifies (risk-routed); step 4 (default Monday) sends the weekly digest.
- Channel activation rules in §3.1; `notify --dry-run` previews copy without sending.

---

## 8. Traps & gotchas (production-verified)

| # | Trap | Symptom | Root cause | Fix |
|---|---|---|---|---|
| 1 | **Railway cron ignores railway.json** | no nightly at 03:00, `nextCronRunAt: null` | config-as-code applies per-deployment only, never writes back to service settings (deprecated) | set Cron Schedule / Restart / Start Command in Dashboard → Settings; verify via `railway status --json` |
| 2 | **NEXT_PUBLIC_ inlined at build** | removed the readonly env but buttons still grey | Vercel bakes `NEXT_PUBLIC_*` into JS at build | rebuild after env change (push or Redeploy) |
| 3 | **Double quotes in Railway env** | build fails: `secret ID missing for ""` | Railpack parses an empty-named variable | no `"` in names or values |
| 4 | **Deploy runs a nightly — only BEFORE cron is set** | "unexpected" notification after a push | with no cron schedule Railway treats the service as a long-running one and executes the start command on deploy; once cron IS set the deploy is `buildOnly` and starts nothing (verified 2026-09-06, deploy `bd57dc6b`) | before cron: accept it (free catch-up run) or time pushes; after cron: nothing to do |
| 5 | **Relative internal links misfire** | whole site `needs_human_recheck` | scheme-less URLs rejected by the SSRF guard | set `<SITE>_PUBLIC_ORIGIN` |
| 6 | **Bot-wall verdict flapping** | same card healthy↔offer_changed minutes apart | Amazon et al. serve good/bad pages alternately to datacenter IPs | `recheck --confirm 3`; UNSTABLE cards stay for humans |
| 7 | **railway logs stuck in `more`** | terminal frozen at `-- More --` | Windows pager | run in background or query DB / `railway status --json` |
| 8 | **Windows quoting / Chinese-path mangle** | `python -c` SyntaxError, curl `-w` garbage | transport layer strips quotes | always write UTF-8 script files |
| 9 | **Secrets in repo/logs** | security incident | — | platform env only; repo ships `.env.example`; scripts never print DSNs |
| 10 | **Write-back misread** | believing source-site production content changes | doc wording vs code drift | remember the two-database model: writes land in EverLink's mirror + snapshot audit |
| 11 | **Reasoning models break the real Judge** | single-turn probe fine, real scan raises `StructuredOutputException` | gpt-oss-family `reasoningContent` is incompatible with the deep multi-turn Chat Completions loop (steering hooks + recurse) | default qwen is non-reasoning; set `BEDROCK_MANTLE_REASONING` only after switching to a reasoning model |
| 12 | **Empty AWS credential vars** | `aws cli` fine but Mantle mint fails | empty `AWS_PROFILE=`/`AWS_ACCESS_KEY_ID=` still override the chain | comment the lines out entirely (§3.1 warning) |

---

## 9. Tips & verification command kit

```bash
# is cron really scheduled? (non-null = yes)
railway status --json | findstr /C:"cronSchedule" /C:"nextCronRunAt"

# did the nightly land? (the audit column is ts, NOT created_at)
psql "$EVERLINK_DATABASE_URL" -c "SELECT max(ts), count(*) FROM audit_log;"
psql "$EVERLINK_DATABASE_URL" -c "SELECT status, count(*) FROM decisions GROUP BY 1;"

# last occurrence per key event
psql "$EVERLINK_DATABASE_URL" -c "SELECT event, max(ts) FROM audit_log GROUP BY 1 ORDER BY 2 DESC;"

# board open-state DOM self-check (checkboxes > 0 and no Read-only string = open)
curl -s https://<board>/inbox | findstr /C:"checkbox" /C:"Read-only"

# false-positive retirement trio (dry list → confirm probes → apply)
python -m everlink recheck
python -m everlink recheck --confirm 3
python -m everlink recheck --confirm 3 --apply

# preview notification copy (zero sends)
python -m everlink notify --dry-run --brief
```

Tips:
- Before demos/recordings, run `decisions --json` to align spoken counts with on-screen numbers.
- High-risk cards are **single-card approval by design** — the batch bar ignoring them is a feature.
- The weekly digest and `/report` share aggregates; quote one of those two, never hand-compute.

---

## 10. Troubleshooting FAQ

**Q: The nightly cron didn't run?**
→ `railway status --json` → `nextCronRunAt`. null = Dashboard never configured (trap 1).
Non-null but no rows = check that run's log under Railway Deployments/Cron Runs.

**Q: Board buttons grey / "Read-only view" visible?**
→ `NEXT_PUBLIC_BOARD_READONLY` is 1, or was removed without a rebuild (trap 2).

**Q: `scan` prints `[everlink] Mantle unavailable` / exit 2?**
→ AWS credentials/region issue; offline use `--judge none` (detection still real) or `stub`.

**Q: notify reports all `skipped`?**
→ the email trio (`RESEND_API_KEY`/`RESEND_FROM`/`EVERLINK_NOTIFY_EMAIL`) or the TG pair is incomplete.

**Q: An approved card never goes applied?**
→ the worker runs only in nightly step 3 or a manual `worker --once`; check
`/audit?event=write`; a failed re-probe rolls back and dead-letters to rejected
(see `dead_letter` events).

**Q: Generic scan returns 0 links?**
→ robots.txt Disallow (fail-open covers unreadable robots only; a real Disallow is honoured),
or all links are internal (add `--include-internal`).

**Q: Notification copy garbled on a Windows console?**
→ the CLI reconfigures UTF-8 itself; if still broken, prefix `set PYTHONIOENCODING=utf-8`.

**Q: The board opens empty?**
→ the decision queue has no data (a normal empty state, not a bug). Run `python scripts/seed_demo.py` (demo) or a real `scan` (drop `--dry-run`) to persist rows.

**Q: worker raises `ProductionWriteRefused`?**
→ the DSN points at a source site or a denied host — **the guardrail is protecting you**. Confirm `EVERLINK_DATABASE_URL` points at EverLink's own DB, not any source/production DB (§1.7).

**Q: scan returns all `needs_human_recheck`?**
→ the target (e.g. Amazon) blocked L2 with a captcha/anti-bot wall. **Correct honest degradation**, not broken. Add `--no-l2` for L1 only, or test a first-party sample site.

**Q: scan is slow?**
→ L2 costs ≈15–20s per real link. Lower `--limit`, add `--no-l2`, or raise `--rate-delay`.

**Q: `everlink` module not found / `npm run dev` port taken?**
→ former: confirm you're in the repo root with the venv active. Latter: kill the occupying process or `npm run dev -- -p 3001`.

---

## 11. Glossary & related docs

| Term | Meaning |
|---|---|
| slot / LinkSlot | one monitored link position (site, anchor, url, protected, slot_type, …) |
| slot_type (role) | `component` product/component · `commercial` affiliate · `reference` citation (never repointed) · `internal` same-site |
| L1 / L2 | L1 = HTTP status + redirect-chain probe (≤1 request/link); L2 = incognito body parse (soft-404 / price-gone / out-of-stock), spent only when L1 is inconclusive |
| verdict | `healthy` / `dead` / `program_ended` / `offer_changed` / `needs_human_recheck` |
| action | `REPLACE_URL` / `REWRITE_ANCHOR` / `REWRITE_SENTENCE` / `DROP_BLOCK` / `ESCALATE_HUMAN` |
| decision card | an aggregated fix proposal awaiting review (pending→approved/rejected→applied); the same link across articles merges into one |
| steering / policy oracle | `policy.py`'s three hard rules (disclosure zero-modification / reference zero-repoint / inconclusive→escalate) + the write_gate; Evals and runtime share the same functions (measured = blocked), audited as `steering_cancel` |
| Interrupt (two tracks) | sync gate (live-demo in-band approval) + async durable-queue worker (production out-of-band approval), both behind write_gate |
| needs_human_recheck | honest-degradation marker: blocked/timeout/insufficient evidence → hand to a human, never fabricate |
| snapshot / rollback / dead-letter | before-write snapshot / auto-revert on failed re-probe / return the card to rejected + audit |
| StubModel / Mantle | offline deterministic fake model (tests/evals) / AWS Bedrock's OpenAI-compatible gateway (production Judge path, qwen) |
| seed | deterministic demo replay dataset, tagged `demo-seed`, cleanly removed with `--reset` |
| generic crawl (path A) | the zero-config default: read-only HTTP crawl of any sitemap/page URL, no source DB, never writes back |
| ProductionWriteRefused | write-guard exception raised when a DSN points at a source/denied host — protects production DBs |

Related docs: repo `README.md` / `DEPLOYMENT.md` / `ARCHITECTURE.md` / `DEVPOST.md` /
`SUBMISSION_CHECKLIST.md` / `docs/specs/2026-09-05-self-hosted-onboarding-and-origin-config-design.md`
(origin of the env-only configuration decision).
