# You Approve Decisions, Not Links — Building EverLink for the "Agents for Humans" Hackathon

> **Blog draft** for builder.aws.com (spec §9 Phase I). The title contains the required
> phrase **"Agents for Humans"**. Publishing is an owner action; this is the prepared
> copy. Numbers below match the committed repo (`data/slots_summary.json`, `EVALS_REPORT.md`);
> re-confirm the live figures before publishing.

---

**Dek.** My three content sites carry 23,476 outbound link slots. The last time every one
of them was checked by hand: never. Broken-link checkers can *report* that number. None of
them can *decide what to do* about it. So I built an agent that does — and it only ever
interrupts me when a human judgment actually matters. This is EverLink, built with the
**Strands Agents SDK** and **Amazon Bedrock** for the AWS **"Agents for Humans"** hackathon.

## The problem nobody's tool actually solves

Content sites — reviews, deals, affiliate blogs — accumulate tens of thousands of outbound
links, and they rot continuously:

- a product page 404s or flips to *Currently unavailable*
- an affiliate program ends, and the redirect chain silently drops the tracking tag
- a price or claim in the surrounding sentence no longer matches the live page
- a reference link goes stale

At the scale of hundreds of articles, manual patrol is impossible. And the existing tools
stop at the wrong place. A broken-link checker tells you *which* links are dead. It never
tells you *what to do* — replace the URL, rewrite the anchor, rewrite the whole sentence,
drop the block, or escalate to a human. That last step is repetitive and judgment-heavy,
which is exactly the kind of work the **"Agents for Humans"** theme is asking us to hand to
an agent: something that *"runs autonomously in the background and only surfaces when
there's a real decision to make."*

## The one-sentence pitch

**EverLink keeps every link on your sites alive, current, and honest — while you sleep. It
surfaces as a notification, not an app; the only screen you open is an approval inbox.**

The first user is me. EverLink patrols my own production sites (dogfooding), so the demo is
real data, not a toy.

## Architecture: a pipeline, not a swarm

EverLink is an Orchestrator agent that composes three specialists as tools — an
**Agent-as-Tool pipeline**, deliberately *not* a Swarm:

```
cron → Orchestrator (Strands)
        ├─ Scanner  → tools: extract_slots, http_probe (L1), page_parse (L2)
        ├─ Judge    → tool: find_alternatives; emits a structured Proposal
        ├─ Push     → Resend email / Telegram: morning brief + decision cards
        ├─ Board    → Next.js approval inbox  ◄── Interrupt: approve / reject
        └─ Writer   → tools: snapshot_block, apply_fix, verify_fix, rollback
                       ↓
                   Neon Postgres + audit_log (hooks) + weekly report
```

The task is a sequential dependency chain — you can't judge a slot before you've scanned
it, and you can't write before a human approves — so peer-to-peer swarm exploration would
be the wrong tool. I'd rather be honest about the topology than claim a Swarm I don't need.
Full diagrams are in the repo's `ARCHITECTURE.md` (six Mermaid views, rendered by GitHub).

## Detection without a product API (and without lying)

Here's a constraint I hit immediately: RapidAPI, RainForest, and the Amazon PA-API were all
discontinued for my use. So there is no clean product-data API to ask "is this ASIN alive
and what does it cost?" EverLink detects link rot from the outside in, as a **pyramid**:

- **L1 — HTTP + redirect-chain analysis.** Status codes, and a specific trick: an affiliate
  hop that *loses its tracking parameter* along the redirect chain means the program ended,
  even though the final page returns 200.
- **L2 — stealthy page parse,** spent *only* where L1 is inconclusive. Price block gone,
  "Currently unavailable", out-of-stock markers. One request per link per night, rate-limited.
- **The honesty valve.** Anything blocked, throttled, or timed out is flagged
  `needs_human_recheck`. The agent knows its limits and refuses to fabricate a verdict.

## The creativity core: four steering policies

The part I'm proudest of isn't the scanning — it's the guardrails. A link-fixing agent that
can *write back* to your content is dangerous unless it's constrained. EverLink runs four
Steering policies as Strands hooks:

1. **DisclosurePolicy.** Affiliate-disclosure text is structurally immune. A block carrying
   disclosure keywords ("affiliate", "commission", "partner link", "sponsored") is marked
   `protected`, and *any* write action against it is cancelled — a dead link inside a
   disclosure never gets dropped. This is three layers: site-level fixed components sit
   outside the article-block pool entirely; keyword blocks are flagged; a regex backstop
   checks the write diff.
2. **EditorialPolicy.** A rewritten sentence must keep — or explicitly downgrade — the
   original factual claim. You can't carry a stale "$19.99, best in class" onto a new link.
3. **ScopePolicy.** Reference slots may never be `REPLACE_URL`; `DROP_BLOCK` is only allowed
   for incidental roles.
4. **WritePolicy.** Every Writer tool call must carry an *approved* `decision_id`, or the
   hook refuses it. No approval, no write. Full stop.

## The closed loop: verify, then roll back if wrong

Most automation stops at "I applied the change." EverLink doesn't. After an approved fix is
written — snapshot first, apply in a **single transaction** — the `verify_fix` tool
**re-probes the new URL** (L1 + L2) to confirm the link is genuinely alive again. If it
isn't, the writer **rolls back** to the snapshot and dead-letters the decision with a
rollback-recommendation card for a human.

That re-probe is the whole point of the "Impact" criterion: the agent doesn't claim success,
it *demonstrates* it. On the seeded demo night, 37 dead links verify back to zero — and I
show a rollback too, because a loop you never see fail is a loop you can't trust.

## Interrupt, two tracks

Strands' Interrupt maps onto EverLink in two ways that share one `Proposal` schema and one
write gate:

- **Track 1 (sync)** — a hook-level gate that blocks for a live approval, used in the demo.
- **Track 2 (async)** — the Judge's proposal lands in a `decisions` table (`pending`); the
  board flips it to `approved`/`rejected`; a durable worker polls approved decisions and
  drives the Writer. This is Interrupt expressed as a **durable decision queue** — the
  production path, so a nightly run never blocks on a human being awake.

## Test it, don't trust it: 50-case Evals + tracing

I don't ask anyone to take the agent's word for it. `scripts/run_evals.py --full` runs a
**50-case** suite against an in-process fixture server with known ground truth — fully
offline, no AWS creds. On the stub backend it scores:

| Evaluator | Threshold | Result |
|---|---|---|
| detection accuracy (L1+L2 vs ground truth) | ≥ 90% | **50/50 = 100%** |
| steering violations (vs the policy oracle) | == 0 | **0** |
| disclosure zero-deletion (hard metric) | == 100% | **100%** |
| reference zero-`REPLACE_URL` (hard metric) | == 100% | **100%** |
| duplicate merged to one card (hard metric) | yes | **yes** (41 cards / 42 problem slots) |

The oracle is proven non-vacuous: `test_oracle_catches_a_violating_judge` injects a Judge
that blindly `REPLACE_URL`s everything and asserts the evaluators flag it. And because the
Strands SDK ships OpenTelemetry instrumentation, `--trace console` renders the whole run as
one span tree — `everlink.evals.run` → `{detect, judge, score}`, with Strands' own
`chat` / `execute_tool` spans nested under the judge because the trace context propagates.
One trace, end to end.

**The honest caveat.** With the stub backend, the *detection* number is real deterministic
code, but the *steering* and *hard-metric* numbers validate the policy **oracle** and the
orchestration plumbing — not live LLM judgment quality. Real Judge quality is scored on
Bedrock with the identical harness: `run_evals --judge bedrock --full`.

## "Any model," one seam

Every agent is `build_scanner(model)` / `build_judge(model)` / `build_writer(conn, model)`.
The `model` is any `strands.models.Model`, injected at a single seam (`everlink/llm.py`).
Nothing downstream — detection, steering, queue, writer, evals — knows or cares which
provider it is. The submission path is `BedrockModel` (Claude), but the same seam accepts
`AnthropicModel`, `OpenAIModel`, `GeminiModel`, `MistralModel`, `OllamaModel`,
`LiteLLMModel`, `SageMakerAIModel`, or a `ModelRouter` with a `FallbackStrategy` for
multi-provider failover. Within Bedrock, the model id and region are env-overridable, so
moving between Claude variants or cross-region inference profiles is zero code change.

The whole 253-test suite *and* the 50-case Evals run on an injected offline `StubModel`,
which is the real proof of provider-independence: the orchestration is exercised with no
cloud dependency at all.

## Strands features used

| Feature | Where |
|---|---|
| `@tool` | `extract_slots` / `http_probe` / `page_parse` / `find_alternatives`; Writer's `snapshot_block` / `apply_fix` / `verify_fix` / `rollback` |
| Multi-agent (Agent-as-Tool) | Orchestrator → Scanner → Judge → Writer |
| Steering | Disclosure / Editorial / Scope policies |
| Hooks (Before/AfterToolCall) | audit log + write gate |
| Interrupt | two-track approval (sync gate + durable queue) |
| Structured Output (Pydantic) | the `Proposal` schema |
| ConversationManager (SlidingWindow) | long nightly Writer runs |
| Strands Evals | 50-case suite |
| `BedrockModel` | Claude via Amazon Bedrock |
| OpenTelemetry | optional tracing (`everlink/tracing.py`) |

## Deploy + safety

The board deploys to Vercel; the store is Neon Postgres; the nightly cron runs on Railway
(with an AgentCore runtime as the stretch path). Two safety rules are non-negotiable and
enforced in code:

- **All source-site database access is read-only** (`default_transaction_read_only = on`
  after connect). Write-back happens only through the gated Writer path, and only to
  AethelGem block content in the hackathon scope.
- **A write guardrail** (`db._assert_writable`) refuses any DSN whose host matches a
  source-site connection var or a deny-list — the production instance can never be written,
  even by accident. Secrets live only in `.env`; the repo ships `.env.example` with
  placeholders, and a secrets scan is part of the submission gate.

## What's next

Write-back is AethelGem-only for the hackathon; extending it to the other two sites is on
the roadmap. There's no L3 exact-price API (none exists for me), so price-drift detection
stays at the page-parse layer. And the approval inbox is web-only by design — it's meant to
be the *one* screen, not a suite.

If you run content sites and you're tired of being a broken-link *reporter*'s audience, the
repo is public and the offline path runs end to end with no AWS account:
`pip install -r requirements.txt && python scripts/run_evals.py --full`.

**You approve decisions, not links.** That's the whole idea — and it's what "Agents for
Humans" means to me: an agent that does the repetitive, judgment-heavy work in the
background, and treats a human's attention as the scarce resource it is.

---

*Built with the Strands Agents SDK and Amazon Bedrock for the AWS "Agents for Humans"
hackathon (Professional Agents track). MIT-licensed; the repo, architecture diagrams, and
eval report are linked from the README.*
