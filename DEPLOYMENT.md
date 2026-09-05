# EverLink — Deployment Runbook

This is the **scaffold + runbook** for EverLink's live deployment (spec §7 line 245,
§9 Phase F, §12-5). It documents the exact, reproducible steps to put the two moving
parts online:

* **the Decision Board** — a Next.js inbox → **Vercel**
* **the autonomous agent** — the Strands/Bedrock Python loop → **Railway** (container),
  with **AWS Bedrock AgentCore** as the stretch (§9 熔断: if AgentCore is not reached, the
  live demo runs on Vercel + Railway and AgentCore appears only in the architecture diagram)
* **the database** — EverLink's OWN operational store → **Neon Postgres**

> **HONESTY / scope.** The files added here (`Dockerfile`, `.dockerignore`, `railway.json`,
> `board/vercel.json`, `scripts/nightly.py`) are validated **offline**: the board type-checks
> and builds, the JSON configs parse, the Dockerfile's `COPY` sources all exist, and the cron
> entrypoint's step-planning is unit-tested. Actually creating the live URLs is an
> **operational action on YOUR Vercel / Railway / Neon / AWS accounts** — it is not performed
> by the scaffold and no live URL is claimed here until you run the steps below.

---

## Topology

```
        nightly cron (Railway, 03:00 UTC)                 human (email / Telegram)
                 │                                                 │
                 ▼                                                 ▼
   ┌───────────────────────────┐                    ┌──────────────────────────┐
   │  Railway service (Docker) │  enqueue decisions │  Vercel: Next.js board    │
   │  python scripts/nightly.py│ ─────────────────► │  inbox / audit / report   │
   │   1 scan (Scanner→Judge)  │   (Neon Postgres)  │  approve / reject         │
   │   2 notify (Resend/TG)    │ ◄───────────────── │  (status transition only) │
   │   3 worker (apply+verify) │   approved cards   └──────────────────────────┘
   │   4 report (Mon, weekly)  │
   └───────────────────────────┘
                 │  Bedrock (Judge/Writer LLM)          Neon Postgres (us-east-1)
                 └──────────────────────────────────►   decisions / slot_checks /
                                                         audit_log / link_slots / snapshots
```

Both the board and the agent talk to the **same Neon database**. The board's only write is a
decision status transition (`pending → approved | rejected`); the agent's writes are guarded by
`db._assert_writable` (board side: `assertBoardWritable`) so neither can ever point a write at a
source site's production host or the forbidden Blue-Neon instance.

---

## Prerequisites

| Thing | Why | Where |
|---|---|---|
| Neon Postgres project | EverLink's own store | console.neon.tech (or the Neon Vercel Marketplace integration) |
| Vercel account + project | hosts the board | vercel.com |
| Railway account + project | hosts the agent container + cron | railway.com |
| AWS Builder ID + Bedrock access | the Judge/Writer LLM (`us.anthropic.claude-sonnet-4-6`) | console.aws.amazon.com/bedrock |
| Resend API key (+ verified sender) | email push | resend.com |
| Telegram bot token + chat id | optional second push channel | @BotFather |

All secrets are injected as **platform environment variables** — never committed. The repo ships
only `.env.example` / `board/.env.example` with placeholders.

---

## Step 1 — Neon database

1. Create a Neon project (region **us-east-1**, to match the board's Vercel region below).
2. Copy the pooled connection string (`…-pooler…?sslmode=require`). This is `EVERLINK_DATABASE_URL`.
3. The schema is created **idempotently at first connect** (`db.ensure_schema`, reads `schema.sql`),
   so no manual DDL is required. To apply it explicitly instead:
   ```bash
   psql "$EVERLINK_DATABASE_URL" -f schema.sql
   ```
4. This database must be EverLink's **own** — never a source site's production instance.

## Step 2 — Vercel (the Decision Board)

The board lives in `board/` (its own Vercel project root). `board/vercel.json` pins the framework
and the **iad1** (us-east-1) region so the Serverless API routes sit next to Neon.

```bash
cd board
npm install
npm run typecheck     # tsc --noEmit  -> zero errors (spec §12-4)
npm run build         # next build    -> succeeds with NO database configured
vercel link           # or connect the Git repo in the Vercel dashboard (root dir = board)
vercel env add EVERLINK_DATABASE_URL production   # the Neon pooled DSN from Step 1
vercel env add EVERLINK_FORBIDDEN_HOSTS production # optional deny-list (host fragments)
vercel env add NEXT_PUBLIC_BOARD_READONLY production  # "1" => public read-only demo view
vercel --prod
```

* **Public demo link** (spec §7 line 244): set `NEXT_PUBLIC_BOARD_READONLY=1` on a deployment to
  serve a login-free, look-but-don't-touch inbox so judges never hit an empty/locked state.
* The board reads `decisions / slot_checks / audit_log / link_slots` and renders the inbox, the
  audit stream, and the `/report` page (the weekly numbers `everlink report` mirrors).

## Step 3 — Railway (the autonomous agent + cron)

The repo root is the Railway service root. Railway finds the `Dockerfile` and builds it
(`railway.json` pins `builder: DOCKERFILE`). The default `CMD` runs one full nightly chain and
exits — exactly what a Railway cron wants.

```bash
railway link          # or connect the Git repo in the Railway dashboard
railway up            # builds the Dockerfile, deploys the agent image
```

Set the service's environment variables (Railway dashboard → Variables, or `railway variables set`):

```
# Bedrock / AWS (the Judge + Writer LLM) — use an IAM role or scoped keys, never hardcoded
AWS_REGION=us-east-1
BEDROCK_MODEL_ID=us.anthropic.claude-sonnet-4-6
AWS_ACCESS_KEY_ID=…            AWS_SECRET_ACCESS_KEY=…      # or attach an IAM role

# EverLink's OWN store (same Neon DSN as the board)
EVERLINK_DATABASE_URL=postgresql://…-pooler…/everlink?sslmode=require
EVERLINK_FORBIDDEN_HOSTS=…      # optional extra deny-list

# Surfacing
RESEND_API_KEY=…   RESEND_FROM=EverLink <brief@yourdomain.com>   EVERLINK_NOTIFY_EMAIL=you@x.com
TELEGRAM_BOT_TOKEN=…   TELEGRAM_CHAT_ID=…
EVERLINK_BOARD_URL=https://<your-board>.vercel.app   # board ROOT; notifications deep-link to /inbox, /decision/<id>, /report

# Cron tuning (all optional — sensible defaults are built in)
EVERLINK_NIGHTLY_SITES=aethelgem,sandcart,hotdeals
EVERLINK_JUDGE=mantle          # deployed TODAY: real qwen via Bedrock Mantle. bedrock = direct Claude (SigV4); stub = offline fixture; none = detection only
EVERLINK_WEEKLY_DAY=mon         # weekday the weekly digest folds into the nightly run
```

> **Choosing `EVERLINK_JUDGE` (updated 2026-09-04).** The deployed nightly runs `mantle`:
> a real LLM (qwen) served through AWS's **Bedrock Mantle** gateway
> (`https://bedrock-mantle.<region>.api.aws/v1`), which bypasses the account-level
> Anthropic allowlist gate that blocks direct `BedrockModel`/SigV4 calls
> (`ValidationException: … unsupported countries …`) on accounts registered where Anthropic
> does not serve. Mantle is still a Bedrock endpoint and still pure Strands SDK
> (`OpenAIModel`), so detection, steering, the decision queue, the writer, the board *and
> the per-problem judgment* all run for real. Use `bedrock` for direct Claude once the
> account allowlist gate clears; `stub` remains for offline dev / CI / `--dry-run`.

**Cron.** `railway.json` declares `cronSchedule: "0 3 * * *"` (Railway crons run in **UTC**) with
`restartPolicyType: NEVER` (run once per schedule, then idle). Confirm/adjust it under
Service → Settings → Cron. To trigger the loop by hand right now (spec §12-5):

```bash
railway run python scripts/nightly.py --dry-run --judge none   # safe: no writes, no sends
railway run python scripts/nightly.py                          # the real full chain
```

> Config-as-code (`railway.json`) is a deprecated-but-supported Railway feature (valid through
> 2026-12-01, which covers the hackathon). The same start command + cron schedule can be set in
> the dashboard or via Railway's Infrastructure-as-Code if you prefer the non-deprecated path.

> Observed platform behavior: Railway also runs the start command **once per deployment**
> (not only on the cron schedule), so every `git push` / redeploy performs one full nightly —
> including its notify step. Plan pushes accordingly, or accept one duplicate nightly per
> deploy as the cost of shipping.

### Data provisioning for the first-party scan (important, honest)

The three first-party adapters read `data/slots_<site>.csv` (the Phase-A read-only export
that carries the `protected`/disclosure flags). **This repo commits those CSVs** (they are
the maintainer's own sites' public link mirrors — URLs and flags only, no secrets) and the
Dockerfile `COPY data/` bakes them into the image, so a repo-based Railway build scans out
of the box: this deployment patrols 77 first-party slots every night.

If your fork must NOT carry site link data in git, negate the CSVs in `.gitignore` and
choose one:

1. **Volume mount** (recommended): export locally (`python scripts/export_slots.py`), then attach
   the CSVs to the service at `/app/data` via a Railway volume.
2. **Private prebuilt image**: `docker build` on a machine where `data/slots_*.csv` exist, then
   push to a **private** registry and deploy that image. (The image then contains your own sites'
   link data — keep the registry private.)
3. **Zero-data / demo**: the read-only `generic` adapter needs no CSV —
   `python -m everlink scan --site https://any-site/sitemap.xml` crawls live. This is the
   §11 "scan any blog" demo shot and works out-of-the-box in the container.

The board shows whatever lives in `EVERLINK_DATABASE_URL` — in this deployment, the real
nightly's output. For a fresh or offline demo DB, use the seed tooling in `scripts/`
(Phase F) to populate one.

### Public origin per site (`<SITE>_PUBLIC_ORIGIN`)

If a source database stores internal links as bare relative paths (e.g. FlashDeals'
`/products/...`), set that site's public origin so the adapter can absolutize them at
ingestion — otherwise the probe-side SSRF guard rejects a scheme-less URL and the whole
site surfaces as false `needs_human_recheck` cards. Symmetric with `<SITE>_DATABASE_URL`
(e.g. `SANDCART_PUBLIC_ORIGIN=https://your-store.example.com`). Sites whose links are
already absolute need no origin. Nothing is hardcoded: an unset origin leaves relative
URLs untouched rather than guessing a domain.

---

## AWS Bedrock AgentCore (the stretch — §9 熔断)

AgentCore Runtime deploys an agent as a container that **serves HTTP** and is invoked per session.
The image built here is a **one-shot cron runner** (its `CMD` executes the nightly chain and exits),
which is the right shape for Railway but **not** yet an HTTP server. To promote the same image to
AgentCore you would add a minimal HTTP entrypoint (e.g. a FastAPI app exposing `/health` +
`POST /invoke` that calls `everlink.cli.main([...])`), package it with the AgentCore Runtime API,
and let AgentCore's scheduler replace the Railway cron.

That wrapper is intentionally **not** built in this scaffold: per the spec's circuit-breaker, if
AgentCore is not reached in time the live demo runs on **Vercel + Railway** and AgentCore is
represented in the **architecture diagram** only. The `Dockerfile` is the shared, portable artifact
that makes the AgentCore path a small step rather than a rewrite.

---

## Post-deploy validation (spec §12)

```bash
# board
cd board && npm run typecheck && npm run build          # §12-4: zero errors + build succeeds

# agent (offline gates — no cloud needed)
python -m pytest -q                                      # full suite green
python scripts/nightly.py --dry-run --judge none --skip-notify   # cron wiring, mutates nothing

# end-to-end against the live DB + URLs (§12-2/3/5)
python -m everlink scan --site aethelgem --dry-run       # slot count matches the DB
python -m everlink decisions --json                      # the board's read model
python -m everlink report --json                         # the /api/report twin
# then open the Vercel URL, approve a card, and run: python -m everlink worker --once
```

`§12-5` is satisfied when the Vercel URL loads **and** one manual `nightly.py` run completes the
scan → notify → worker chain against the live DB.

---

## Environment variable reference

| Variable | Used by | Purpose |
|---|---|---|
| `EVERLINK_DATABASE_URL` | board + agent | EverLink's OWN Neon Postgres (pooled DSN) |
| `EVERLINK_FORBIDDEN_HOSTS` | board + agent | extra write deny-list (host fragments) |
| `NEXT_PUBLIC_BOARD_READONLY` | board | `1` = public read-only demo view |
| `AWS_REGION`, `BEDROCK_MODEL_ID`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` | agent | Bedrock LLM (Judge/Writer) |
| `AETHELGEM_/SANDCART_/HOTDEALS_DATABASE_URL` | export only | read-only source DBs (Phase-A CSV export) |
| `<SITE>_PUBLIC_ORIGIN` | agent (scan) | Public origin for absolutizing a site's relative internal links; symmetric with `<SITE>_DATABASE_URL`; unset = leave relative URLs as-is |
| `RESEND_API_KEY`, `RESEND_FROM`, `EVERLINK_NOTIFY_EMAIL` | agent | email push (all three required to activate) |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | agent | optional Telegram push |
| `EVERLINK_BOARD_URL` | agent | board ROOT embedded in every notification (deep-linked to `/inbox`, `/decision/<id>`, `/report`) |
| `EVERLINK_NIGHTLY_SITES`, `EVERLINK_JUDGE`, `EVERLINK_WEEKLY_DAY` | agent (cron) | nightly chain tuning |

See `.env.example` (agent) and `board/.env.example` (board) for annotated placeholders.
