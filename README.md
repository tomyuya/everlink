<p align="center">
  <img src="board/public/everlink-mark.svg" alt="EverLink logo" width="120" />
</p>

# EverLink

**An open-source (MIT), self-hosted link-rot patrol agent.** You clone the code, deploy
it on your own infrastructure, and fill in your own config — then it patrols the outbound
links of **your own site** every night: fixing what it can autonomously, and surfacing a
compact decision card **only when a human judgment is actually needed**.

> Built for the **AWS "Agents for Humans" Hackathon** (Professional Agents track) with
> the **Strands Agents SDK** and **Amazon Bedrock**.

**It is not a SaaS.** No sign-up, no hosting, no monthly fee, no multi-tenancy — just code
you run on your own server. The three sites that appear in this repo (**AethelGem /
HotDeals / FlashDeals**) are only the **maintainer's dogfooding examples** (the first user
is the author). When you deploy, you swap in your own site keys, databases, and domains.

<details>
<summary><b>What it does, in 30 seconds</b></summary>

EverLink patrols the outbound links of a content/affiliate site, detects link rot (dead
product pages, ended affiliate programs, price/availability drift, stale references),
*decides how to fix each one*, and surfaces a decision card **only when a human judgment
is actually needed**. It is not another broken-link *reporter* — it is a link *steward*.

</details>

## Deploy it — what you provide (the deployer contract)

EverLink is self-hosted, so at deploy time you provide what it cannot ship with. **Nothing
is hardcoded in the repo — no domain, no database address, no secret**; you supply all of
it through environment variables:

| # | You provide | How to configure | Why it's needed |
|---|-------------|------------------|-----------------|
| 1 | Your site's database (**read-only**) | env `<SITE>_DATABASE_URL` | The data source — the links to patrol are read from here |
| 2 | Your site's **public origin** | env `<SITE>_PUBLIC_ORIGIN` | Turns an internal relative link `/products/x` into an absolute URL before probing |
| 3 | EverLink's own database | env `EVERLINK_DATABASE_URL` | Stores the patrol data (decision cards / audit trail / check records) |
| 4 | An LLM | AWS Bedrock credentials | The reasoning brain for the Judge / Writer agents |
| 5 | A timer | Railway cron `0 3 * * *` (or any schedule) | Triggers the nightly patrol |

`<SITE>` is the key you give your own site (in the examples: `AETHELGEM` / `SANDCART` /
`HOTDEALS`). Full step-by-step runbook: **[`DEPLOYMENT.md`](DEPLOYMENT.md)**; visual
explainer: the board's **`/how-it-works`** page.

## The two databases (the key to understanding EverLink)

```
   (1) YOUR SITE'S DB   ·   <SITE>_DATABASE_URL   ·   READ-ONLY source
       ├─ your products / articles / links
       ├─ EverLink NEVER writes here
       └─ guard: db._assert_writable   (SET default_transaction_read_only=on)

                        │  read-only SELECT
                        ▼

   (2) EVERLINK'S OWN DB   ·   EVERLINK_DATABASE_URL   ·   the ONLY place it writes
       ├─ link_slots     a mirror of the links it patrols
       ├─ slot_checks    each probe's result
       ├─ decisions      the cards awaiting your approval
       └─ audit_log      every step, audited
```

- **(1) Source DB** — your own e-commerce / content site's database. EverLink connects
  **strictly read-only** (`SET default_transaction_read_only=on`) and reads the links to
  patrol from it. **It never writes to your source DB** — the write guard
  (`db._assert_writable`) rejects any write aimed at a source-DB host.
- **(2) EverLink DB** — the agent's own operational database: the link mirror, probe
  results, decision cards, and audit trail. This is the only place EverLink writes.

**Docs:** [`ARCHITECTURE.md`](ARCHITECTURE.md) (diagrams) · [`DEPLOYMENT.md`](DEPLOYMENT.md) (runbook) ·
[`EVALS_REPORT.md`](EVALS_REPORT.md) (eval evidence) · [`CONTRIBUTING.md`](CONTRIBUTING.md) (dev workflow & house rules) ·
[`SUBMISSION_CHECKLIST.md`](SUBMISSION_CHECKLIST.md) (phase gate).

---

## The problem

Content sites (reviews, deals, affiliate blogs) accumulate thousands of outbound
links that rot continuously:

- a product page 404s or goes *Currently unavailable*
- an affiliate program ends (the redirect chain silently drops the tracking tag)
- a price/claim in the surrounding sentence no longer matches the live page
- an internal or reference link goes stale

At the scale of hundreds of articles and tens of thousands of links, manual
patrol is impossible. Existing broken-link checkers only **report** — they never
**decide what to do**. "Replace / rewrite the anchor / rewrite the sentence /
drop the block / escalate to a human" is a repetitive, judgment-heavy task.
That is exactly the work EverLink takes on.

## Who it's for

Independent publishers, affiliate creators, and small content teams (1–3 people
running several sites). The first user is the author — EverLink runs against real
production sites (dogfooding).

## Why an agent (and why "Agents for Humans")

The hackathon theme is an agent that *"runs autonomously in the background and
only surfaces when there's a real decision to make."* EverLink embodies this:

1. **Autonomous** — a nightly cron scans every link slot, probes it, and drafts a fix proposal. No human present.
2. **Surfaces** — proposals are aggregated into decision cards and *pushed* to you (email / Telegram). "It surfaces as a notification, not an app."
3. **Human-in-the-loop** — the only screen you open is a minimal approval inbox. Approve, reject (with a reason the agent remembers), or batch-approve low-risk fixes.
4. **Executes + verifies** — approved fixes are written back (snapshot first), then `verify_fix` re-probes to confirm the link is genuinely alive again. If it is not, the writer rolls back and dead-letters the decision.

## Architecture

> Full Mermaid diagrams — system context, nightly pipeline, agent topology, detection
> pyramid, write-back safety, and deployment — are in **[`ARCHITECTURE.md`](ARCHITECTURE.md)**
> (rendered natively by GitHub). The sketch below is the 30-second version.

```
[cron / AgentCore schedule]
        |
        v
 Orchestrator Agent (Strands)
   |-- Scanner Agent -- tools: extract_slots(adapter), http_probe (L1), page_parse (L2)
   |        | LinkSlot[] + CheckResult[]
   |        v
   |-- Judge Agent --- tool: find_alternatives
   |        | Proposal (Structured Output / Pydantic), gated by steering hooks
   |        v
   |-- Push layer (Resend email / Telegram) -- morning brief + decision cards
   |-- Decision Board (minimal inbox, read-only public view) <-- Interrupt: approve/reject
   |        | approved decision_id
   |        v
   +-- Writer Agent -- tools: snapshot_block, apply_fix, verify_fix, rollback
            |
            v
   [Neon Postgres] + audit_log (Hooks) + weekly report
```

- **Multi-agent as an Agent-as-Tool pipeline** (Orchestrator → Scanner → Judge → Writer). We deliberately do *not* use a Swarm: the task is a sequential dependency chain, not peer exploration.
- **Detection pyramid** — L1 HTTP status + redirect-chain analysis (an affiliate hop that loses its tracking parameter ⇒ program ended); L2 stealth page parse (price block gone / "Currently unavailable" / out-of-stock). L2 is spent only where L1 is inconclusive. No product API is used (RapidAPI / RainForest / Amazon PA-API are all discontinued for us). Anything blocked or that times out is flagged `needs_human_recheck` — the agent knows its limits and never fabricates a result.
- **Steering policies** (the creativity core):
  - `DisclosurePolicy` — affiliate-disclosure text is structurally immune; blocks containing disclosure keywords are `protected=1` and no write action may touch them.
  - `EditorialPolicy` — a rewritten sentence must keep (or explicitly downgrade) the original factual claim; no cross-sentence rewrites.
  - `ScopePolicy` — reference slots may not be `REPLACE_URL`; `DROP_BLOCK` only for incidental roles.
  - `WritePolicy` (Hooks) — any Writer tool call must carry an approved `decision_id`, else it is refused.
- **Interrupt, two tracks** — a synchronous gate for the live demo, and an asynchronous durable decision-queue worker for production. Same `Proposal` schema and write-gate on both.

## Strands Agents SDK features used

| Feature | Where |
|---|---|
| `@tool` | `extract_slots` / `http_probe` / `page_parse` / `find_alternatives`; Writer's `snapshot_block` / `apply_fix` / `verify_fix` / `rollback` |
| Multi-agent (Agent-as-Tool) | Orchestrator → Scanner → Judge → Writer |
| Steering | Disclosure / Editorial / Scope policies |
| Hooks (Before/AfterToolCall) | audit log + write gate |
| Interrupt | decision-card approval flow (sync gate + durable queue) |
| Structured Output (Pydantic) | `Proposal` schema |
| ConversationManager (SlidingWindow) | long nightly runs (Writer) |
| Strands Evals | 50-case evaluation suite → [`EVALS_REPORT.md`](EVALS_REPORT.md) |
| `BedrockModel` | Claude via Amazon Bedrock |
| OpenTelemetry | optional tracing (`everlink/tracing.py`) |

## Model providers (Strands "any model")

Every EverLink agent is built as `build_scanner(model)`, `build_judge(model)`,
`build_writer(conn, model)` — the `model` is **any** `strands.models.Model`, injected at a
single seam ([`everlink/llm.py`](everlink/llm.py)). Nothing downstream (detection, steering
hooks, decision queue, writer, evals) knows or cares which provider it is.

Three providers ship in-repo:

| Provider | What it is | When it runs |
|---|---|---|
| `llm.get_mantle_model()` → `OpenAIModel` | **real LLM (qwen) via the Bedrock Mantle gateway** (`bedrock-mantle.<region>.api.aws`) — the **deployed production judge** | `--judge mantle`, the live nightly (verified green 2026-09-04: 3 sites × 25 slots, real proposals) |
| `llm.get_model()` → `BedrockModel` | real Claude via Amazon Bedrock (direct SigV4) | `verify_bedrock.py`, `--judge bedrock`, once the account's Anthropic allowlist gate clears |
| `llm.StubModel` | offline, deterministic `Model` (scripted text + fixed structured output) | the 254-test suite, all offline Evals, `--dry-run` — **no longer** the production judge |

**The swap experiment.** Because the seam is one injected `Model`, changing provider is a
one-line change with no pipeline edit:

```python
from everlink import agents, llm
from everlink.llm import StubModel

judge = agents.build_judge(llm.get_model())   # real Claude (Bedrock)
judge = agents.build_judge(StubModel(...))     # offline deterministic (tests / CI)
```

Within Bedrock the model and region are env-overridable, so you can move between Claude
variants or cross-region inference profiles with **zero code change**:

```bash
BEDROCK_MODEL_ID=us.anthropic.claude-sonnet-4-6  AWS_REGION=us-east-1  # defaults
BEDROCK_MODEL_ID=us.anthropic.claude-haiku-4     AWS_REGION=us-west-2  # cheaper / faster
```

Strands' model layer is fully pluggable, so the same seam accepts any of its providers —
`AnthropicModel`, `OpenAIModel`, `GeminiModel`, `MistralModel`, `OllamaModel`,
`LiteLLMModel`, `SageMakerAIModel`, or a `ModelRouter` (`FallbackStrategy` /
`ClassifierStrategy`) for multi-provider failover. EverLink stays Bedrock-first for the
submission (spec §6) but is **not** Bedrock-locked.

### Bedrock access — an honest note (updated 2026-09-04)

Direct Anthropic-on-Bedrock (`BedrockModel`, SigV4) is gated by the **AWS account's
registration country and the request's source region**, not just credentials: an account
registered where Anthropic does not serve gets `ValidationException: Access to Anthropic
models is not allowed from unsupported countries…` on every call, even from a US container.

**The production judge therefore runs through Bedrock Mantle** — AWS's OpenAI-compatible
Bedrock gateway (`https://bedrock-mantle.<region>.api.aws/v1`), which empirically bypasses
that account-level allowlist gate (verified 2026-09-04: the same credentials rejected by
`bedrock-runtime` return HTTP 200 on Mantle). It is still a Bedrock endpoint and still pure
Strands SDK (`strands.models.openai.OpenAIModel`), so the submission's "Strands + Bedrock"
requirement holds with a **real LLM**, not a stub:

```bash
EVERLINK_JUDGE=mantle    # deployed nightly TODAY: real qwen judge via Bedrock Mantle
EVERLINK_JUDGE=bedrock   # direct Claude (SigV4) once the account allowlist gate clears
EVERLINK_JUDGE=stub      # offline fixture for dev / CI / --dry-run only
```

With `mantle`, the whole pipeline runs for real **and the per-problem judgment is a live
LLM call**: the current nightly scans 3 first-party sites × 25 slots and the Mantle judge
emits real structured proposals (REWRITE_SENTENCE / DROP_BLOCK / ESCALATE) whose rationale
refuses to fabricate replacement URLs. `StubModel` stays first-class for the offline
test/eval suite, but is **no longer** what runs in production.

**Offline proof of provider-independence:** the entire 254-test suite *and* the 50-case
Evals run on the injected `StubModel`, so the orchestration, steering, hooks, queue, and
card merge are exercised with no cloud dependency. `scripts/verify_bedrock.py` is the one
operator step that swaps in real Claude and confirms a live call (creds → model → real
response); `run_evals --judge bedrock` then scores the REAL Judge with the same harness
and thresholds.

> **Honesty.** Offline (Stub) results prove detection (real deterministic code) and the
> guardrail / orchestration plumbing — **not** live LLM judgment quality. Real Judge
> quality is only scored on Bedrock. Authentication uses the standard AWS credential chain
> (SSO / profile / environment); set `AWS_REGION` + `BEDROCK_MODEL_ID` in `.env` and never
> hardcode long-lived keys. Hackathon participants can claim a Builder ID + **$200 AWS
> credits**.

## Evals (spec §8)

[`scripts/run_evals.py`](scripts/run_evals.py) runs the agent against an in-process fixture
server with known ground truth — deterministic, offline, no AWS creds. Full numbers and the
case distribution are in **[`EVALS_REPORT.md`](EVALS_REPORT.md)**.

The **FULL 50-case Phase F set** (stub backend) scores:

| Evaluator | Threshold | Result |
|---|---|---|
| detection accuracy (L1+L2 vs ground truth) | ≥ 90% | **50/50 = 100%** |
| steering violations (vs the policy oracle) | == 0 | **0** |
| disclosure zero-deletion (hard metric) | == 100% | **100%** |
| reference zero-`REPLACE_URL` (hard metric) | == 100% | **100%** |
| duplicate merged to one card (hard metric) | yes | **yes** (41 cards from 42 problem slots) |

```bash
python scripts/run_evals.py            # 30-case v1 subset
python scripts/run_evals.py --full     # FULL 50-case Phase F set
python scripts/run_evals.py --full --trace console   # + OpenTelemetry span tree
python scripts/run_evals.py --judge bedrock --full   # score the REAL Judge (needs creds)
```

> **Honesty.** With `judge_backend=stub` the detection figure is **real** (deterministic
> code, no LLM); the steering / hard-metric figures validate the policy **oracle** and the
> orchestration plumbing, **not** live LLM judgment (a stub always escalates). The oracle is
> proven non-vacuous by `test_oracle_catches_a_violating_judge`, which injects a Judge that
> blindly `REPLACE_URL`s everything and asserts the evaluators flag it.

## Detection honesty & false-positive control

A probe is a **measurement**, not a verdict on what a human will see. EverLink's
detector runs from a datacenter IP with a script's TLS fingerprint, so it can be
refused or misled in ways a real browser is not. Treating a probe limitation as
"the link is broken for users" is the fastest way to lose a publisher's trust, so
false positives are designed against explicitly:

| False-positive class | Symptom | Defence |
|---|---|---|
| **Bot-wall mislabelled as dead-to-users** | A retailer serves the probe a captcha/403; a card then claims the link is "inaccessible to users" | A blocked probe is `needs_human_recheck`, never `dead`. `recheck_policy` (steering hook) + `verification_violation` (policy oracle) allow **only** `ESCALATE_HUMAN` on an inconclusive verdict, and the Judge prompt forbids writing "inaccessible to users" from a probe-side block. |
| **UGC poisoning a live page** | A healthy product page judged dead because one review said "doesn't exist" | L2 reads **region-scoped** signals only (`<title>`, the first screen of visible text, the `#availability` container). A page carrying the product shell (`#productTitle`) can never be prose-judged dead/blocked — reviews, Q&A and JS strings are noise. A bare `"404"` substring is never a signal (it matches review ids / model numbers); a real 404 is caught by the HTTP status. |
| **Transient network blip** | A one-off timeout becomes a "needs recheck" card | One polite retry (1.5 s) on `TimeoutException` / `ConnectError` before classifying. |
| **Rationale contradicting its own evidence** | Card text invents a cause the evidence chain does not show | Judge evidence-discipline rule: the rationale may cite **only** the evidence lines provided. |

**Nothing is auto-fixed on an inconclusive probe.** When the detector cannot prove
a link is broken, the only permitted outcome is a human click-through. These rules
are one oracle (`everlink/policy.py`) consumed by *both* the runtime hooks and the
Evals scoring, so what is enforced in production is exactly what is measured.

### "Why not fetch the links via Google first?"

A reasonable idea — open each link *as if* arriving from a Google search. We
evaluated it and it does **not** address the root cause:

- Amazon's block keys on **IP reputation and TLS/HTTP fingerprint**, not the
  `Referer`. A datacenter IP is refused whether it arrives "from Google" or direct,
  so the referrer path changes nothing that matters.
- Scraping the SERP itself adds a **second** block surface (Google's own bot-wall)
  and a ToS question, just to reach a link we already hold.

The honest fix is the one above: **region-scoped measurement** (don't be fooled by
what a page merely says), **semantic honesty** (a refused probe means "I couldn't
verify", never "it's dead for everyone"), and a **human-verification loop** as the
final arbiter — which is the whole point of an "Agents for Humans" submission.

### The human-verification loop

- **On the board**, every decision card resting on a probe verdict shows a
  one-click **"Open in your browser"** banner (escalated to a warning when the probe
  was inconclusive), plus clickable URLs in the evidence chain. The reviewer — not
  the probe — decides.
- **`python -m everlink recheck`** re-probes pending cards with the *current*
  detector and retires the ones that no longer reproduce — a card surfaced before a
  fix would otherwise sit in the inbox as a lie. Dry-run by default; `--apply`
  rejects + audits proven false positives and never touches a card whose link is
  still genuinely unhealthy.

```bash
python -m everlink recheck                 # dry-run: which pending cards are now false positives?
python -m everlink recheck --apply         # retire + audit them (real problems left alone)
python -m everlink recheck dec-43dcbc9770  # re-probe one card
```

## Dataset (Phase A snapshot)

`scripts/export_slots.py` performs **read-only** `SELECT`s against the three
production sites and emits a `LinkSlot` CSV per site. Connection strings are
resolved at runtime from each source project's own `.env` and are **never**
stored in this repo. The CSVs carry production content, so they are **gitignored**;
only the aggregate `data/slots_summary.json` is committed for transparency.

The Phase A snapshot (`data/slots_summary.json`) covers **23,476 link slots**
across the three production sites:

| Site | Slots | Breakdown |
|---|---|---|
| **AethelGem** (Django block content) | 15,795 | component 15,772 · reference 19 · commercial 4 |
| **hotdeals** (products[] jsonb → amazon) | 7,605 | component 7,602 · reference 2 · commercial 1 |
| **sandcart** = FlashDeals (flashdeals.today; dropshipping storefront, section product links) | 76 | internal 76 |
| **Total** | **23,476** | component 23,374 · reference 21 · commercial 5 · internal 76 |

Notes on the snapshot:

- `component` slots are product links rendered from a structured source (AethelGem `product_card`/`product_grid` blocks; hotdeals `products[]` asin → region-aware `amazon.{tld}/dp/{asin}`). These are the highest-value link-rot targets.
- hotdeals' link assets live in `products[]` jsonb, **not** in the article HTML — the content is plain prose with only 3 inline `<a>` links across 1,025 articles.
- `internal` slots (sandcart = **FlashDeals**, an independent dropshipping storefront) are stored in the source DB as relative `/products/...` paths. The adapter absolutizes them against the site's **configured public origin** (`<SITE>_PUBLIC_ORIGIN` env var — the deployer sets their own; nothing is hardcoded in the repo) so probes hit the real storefront instead of failing the SSRF scheme check. FlashDeals' links are internal product pages, **not** Amazon affiliate URLs (only AethelGem and hotdeals carry amazon.{tld}/dp links). `sandcart` is the maintainer's internal example site key — substitute your own when you deploy.
- `protected=0` everywhere is expected: affiliate-disclosure text lives in **site-level fixed components**, which are structurally outside the article-block pool (see `DisclosurePolicy` layer (a)). The disclosure guard still fires on any block that *does* carry disclosure keywords.
- CSVs are gitignored (production content); only `data/slots_summary.json` is committed.

## Getting started

```bash
# 1. Python 3.14 recommended
python -m venv .venv && .venv\Scripts\activate    # Windows
# source .venv/bin/activate                        # macOS/Linux

# 2. Install deps (Strands Agents SDK is a hard requirement)
pip install -r requirements.txt

# 3. Configure
copy .env.example .env    # then fill in real values; NEVER commit .env

# 4. Verify the wiring — offline SDK surface, then (with creds) a real Bedrock call
python scripts/verify_strands.py     # offline: imports, hooks, conversation manager, @tool
python scripts/verify_bedrock.py     # real: creds -> model -> live Claude call (exit 0/2/3)

# 5. Run the loop OFFLINE with ZERO setup (no DB, no CSV, no AWS creds, no internet):
#    terminal 1 — the bundled fixture site with known ground truth:
python scripts/fixture_server.py              # http://127.0.0.1:8787
#    terminal 2 — scan it (localhost needs the documented SSRF opt-in):
set EVERLINK_ALLOW_LOCALNET=1                 # Windows; `export` on macOS/Linux
python -m everlink scan --site http://127.0.0.1:8787/link-farm --include-internal --judge stub --dry-run
#    -> dead / soft-404 / price-anomaly / program_ended verdicts with evidence chains,
#       honest stub proposals, and 3 decision cards. Nothing is written anywhere.
#    Point it at YOUR site instead (live crawl, respects robots.txt):
python -m everlink scan --site https://your-site.com/sitemap.xml --judge stub --dry-run
python -m everlink decisions --status pending --json   # the board's read model (needs .env DSN)

# 6. Score the agent (spec §8) — 30-case v1 subset, or the FULL 50-case Phase F set
python scripts/run_evals.py --full

# 7. Push the queue to the operator — Resend email / Telegram.
#    --dry-run composes + prints and sends NOTHING. A real push activates a channel
#    only when its credentials are set (email: RESEND_API_KEY + RESEND_FROM +
#    EVERLINK_NOTIFY_EMAIL; telegram: TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID); with
#    none set, delivery is honestly reported as "skipped" — never faked.
python -m everlink notify --brief --dry-run    # compose the morning digest
python -m everlink notify --dry-run            # risk-route pending cards

# 8. Load the demo dataset (41-problem-slot replay), then drain + report on it
python scripts/seed_demo.py --dry-run          # show the plan, touch nothing
python -m everlink worker --once               # apply approved: snapshot -> apply -> verify
python -m everlink report --days 7             # weekly report (the board /report numbers)

# 9. Approval inbox (Next.js board)
cd board
copy .env.example .env.local    # set EVERLINK_DATABASE_URL = EverLink's own Postgres
npm install && npm run dev      # http://localhost:3000 (honest empty states without a DB)

# 10. (Phase A) export the read-only LinkSlot snapshot from the three sites
python scripts/export_slots.py
```

## Development

The whole gate is **offline**: the injected `StubModel` plus an in-process fixture server
mean the tests and Evals need **no AWS creds and no database**.

```bash
python scripts/verify_strands.py                 # offline Strands SDK surface gate
python -m pytest -q                              # full offline suite (agents/steering/hooks/queue/writer/ssrf/…)
python scripts/run_evals.py --full               # 50-case eval harness (spec §8)
cd board && npm run typecheck && npm run build   # board gate: tsc + next build, no DB needed
```

GitHub Actions (`.github/workflows/ci.yml`) runs exactly these gates on every push and
PR — the Python suite + `verify_strands.py`, then the board's `npm ci && typecheck &&
build`. Workflow, honesty rules, and the PR checklist live in
[`CONTRIBUTING.md`](CONTRIBUTING.md).

## Security & secrets

- This repo contains **only** `.env.example`. Real `.env`, credentials, and exported data CSVs are gitignored.
- All source-site database access is **read-only** (`SET default_transaction_read_only = on` after connect). Write-back happens only through the agent's gated Writer path, and only to AethelGem block content in the hackathon scope.
- A write guardrail (`db._assert_writable`) refuses any DSN whose host matches a source-site connection var or the `EVERLINK_FORBIDDEN_HOSTS` deny-list — the production Blue-Neon instance can never be written, even by accident.
- A `gitleaks`-clean check is part of the submission gate (see `SUBMISSION_CHECKLIST.md`).

## Scope (non-goals)

- Not a commercial product / multi-tenant SaaS / billing.
- Write-back is AethelGem-only for the hackathon; sandcart/hotdeals write-back is on the roadmap.
- No L3 exact-price API integration (none available).
- The minimal approval inbox is web-only (no mobile app).

## Roadmap / phases

See [`SUBMISSION_CHECKLIST.md`](SUBMISSION_CHECKLIST.md) for the phase gate and
the full deliverables list.

## License

MIT — see [`LICENSE`](LICENSE).
