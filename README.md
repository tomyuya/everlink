# EverLink

**Keeps every link on your content sites alive, current, and honest — while you sleep.**

EverLink is an autonomous background agent that patrols the outbound links of a
content/affiliate site, detects link rot (dead products, ended affiliate programs,
price/availability drift, stale references), *decides how to fix each one*, and
surfaces a compact decision card **only when a human judgment is actually needed**.
It is not another broken-link *reporter* — it is a link *steward*.

> Built for the **AWS "Agents for Humans" Hackathon** (Professional Agents track)
> with the **Strands Agents SDK** and **Amazon Bedrock**.

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
4. **Executes + verifies** — approved fixes are written back (snapshot first), then `verify_fix` re-probes to confirm the link is genuinely alive again.

## Architecture

```
[cron / AgentCore schedule]
        |
        v
 Orchestrator Agent (Strands)
   |-- Scanner Agent -- tools: extract_slots(adapter), http_probe, page_parse
   |        | LinkSlot[] + CheckResult[]
   |        v
   |-- Judge Agent --- tools: find_alternatives, draft_proposal
   |        | Proposal[] (Structured Output / Pydantic)
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
- **Detection pyramid** — L1 HTTP status + redirect-chain analysis (an affiliate hop that loses its tracking parameter ⇒ program ended); L2 stealth page parse (price block gone / "Currently unavailable" / out-of-stock). No product API is used (RapidAPI / RainForest / Amazon PA-API are all discontinued for us). Anything blocked or times out is flagged `needs_human_recheck` — the agent knows its limits and never fabricates a result.
- **Steering policies** (the creativity core):
  - `DisclosurePolicy` — affiliate-disclosure text is structurally immune; blocks containing disclosure keywords are `protected=1` and no write action may touch them.
  - `EditorialPolicy` — a rewritten sentence must keep (or explicitly downgrade) the original factual claim; no cross-sentence rewrites.
  - `ScopePolicy` — reference slots may not be `REPLACE_URL`; `DROP_BLOCK` only for incidental roles.
  - `WritePolicy` (Hooks) — any Writer tool call must carry an approved `decision_id`, else it is refused.
- **Interrupt, two tracks** — a synchronous track for the live demo, and an asynchronous durable decision-queue track for production. Same `Proposal` schema and write-gate on both.

## Strands Agents SDK features used

| Feature | Where |
|---|---|
| `@tool` | scan / detect / write-back tools |
| Multi-agent (Agent-as-Tool) | Orchestrator → Scanner → Judge → Writer |
| Steering | Disclosure / Editorial / Scope policies |
| Hooks (Before/AfterToolCall) | audit log + write gate |
| Interrupt | decision-card approval flow |
| Structured Output (Pydantic) | `Proposal` schema |
| ConversationManager (SlidingWindow) | long nightly runs |
| Strands Evals | 50-case evaluation suite |
| `BedrockModel` | Claude via Amazon Bedrock |
| OpenTelemetry | tracing (stretch) |

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
| **sandcart** (section product links) | 76 | internal 76 |
| **Total** | **23,476** | component 23,374 · reference 21 · commercial 5 · internal 76 |

Notes on the snapshot:

- `component` slots are product links rendered from a structured source (AethelGem `product_card`/`product_grid` blocks; hotdeals `products[]` asin → region-aware `amazon.{tld}/dp/{asin}`). These are the highest-value link-rot targets.
- hotdeals' link assets live in `products[]` jsonb, **not** in the article HTML — the content is plain prose with only 3 inline `<a>` links across 1,025 articles.
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

# 4. Verify the Strands + Bedrock wiring
python scripts/verify_strands.py

# 5. (Phase A) export the read-only LinkSlot snapshot from the three sites
python scripts/export_slots.py
```

### AWS / Bedrock auth

EverLink uses `strands.models.BedrockModel`. Authentication flows through the
standard AWS credential chain (SSO / profile / environment). Set `AWS_REGION`
and `BEDROCK_MODEL_ID` in `.env`; do **not** hardcode long-lived keys. Hackathon
participants can apply for the **$200 AWS credits**.

## Security & secrets

- This repo contains **only** `.env.example`. Real `.env`, credentials, and exported data CSVs are gitignored.
- All database access is **read-only** (`SET default_transaction_read_only = on` after connect). Write-back happens only through the agent's gated Writer path, and only to AethelGem block content in the hackathon scope.
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
