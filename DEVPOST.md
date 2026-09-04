# EverLink — Devpost Submission Copy (Phase I)

Prepared text for the Devpost submission form (spec §10-1: problem / who / how). Pasting it
into Devpost and clicking submit is an **owner action**. Figures match the committed repo
(`data/slots_summary.json`, `EVALS_REPORT.md`); re-confirm live numbers before submitting.

---

## Project title

**EverLink**

## Tagline (one line)

Keeps every link on your content sites alive, current, and honest — while you sleep. You
approve decisions, not links.

## Track

Professional Agents — the repetitive, judgment-heavy work that eats a creator's day.

---

## Description

### Inspiration

I run three content sites. Between them they carry **23,476 outbound link slots** — product
cards, affiliate links, references. The last time every one of them was checked by hand?
**Never.** They rot a little every day: a product 404s, an affiliate program quietly ends,
a price drifts from the sentence that cites it. Readers notice before I do, and every stale
link costs trust, SEO, and commission.

The tools that exist are broken-link *checkers*. They **report** which links are dead. Not
one of them **decides what to do** — replace the URL, rewrite the anchor, rewrite the whole
sentence, drop the block, or escalate to a human. That last part is the repetitive,
judgment-heavy work, and it's exactly what the **"Agents for Humans"** theme asks us to hand
to an agent: something that runs autonomously in the background and only surfaces when
there's a real decision to make.

### What it does

EverLink is an autonomous link *steward*, not another reporter. Every night:

1. **It patrols.** A cron scans every link slot across my production sites (read-only) and
   detects rot — HTTP status and redirect-chain analysis at L1, a stealthy page parse at L2
   only where L1 is inconclusive. An affiliate hop that loses its tracking parameter means
   the program ended, even on a 200 response.
2. **It decides.** A Judge agent (Claude on Amazon Bedrock) drafts a structured fix
   `Proposal` for each problem — and four Steering policies constrain it (see below).
3. **It surfaces.** Proposals aggregate into decision cards (duplicates across articles
   merge into one), pushed to me by email / Telegram as a morning brief. *It surfaces as a
   notification, not an app.*
4. **It waits for a human.** The only screen I open is a minimal approval inbox. I
   batch-approve low-risk fixes, and reject the risky ones *with a reason the agent
   remembers* so it won't re-propose the same thing.
5. **It executes and verifies.** Approved fixes are written back — snapshot first, single
   transaction — then `verify_fix` **re-probes the new link** to confirm it's genuinely
   alive. If it isn't, the writer rolls back and dead-letters the decision.
6. **It reports.** A weekly digest plus a full audit log of every tool call.

**Who it's for:** independent publishers, affiliate creators, and small content teams —
one to three people running several sites. The first user is me (dogfooding on real
production data).

### How we built it

**Strands Agents SDK** throughout, **Amazon Bedrock** (Claude) as the model.

- **Multi-agent as an Agent-as-Tool pipeline** — an Orchestrator composes a Scanner, a
  Judge, and a Writer as tools. Deliberately *not* a Swarm: the task is a sequential
  dependency chain, not peer exploration, and I'd rather be honest about the topology.
- **Steering (the creativity core) — four policies as hooks:**
  - `DisclosurePolicy` — affiliate-disclosure text is structurally immune; a block with
    disclosure keywords is `protected` and *any* write against it is cancelled. A dead link
    inside a disclosure never gets dropped.
  - `EditorialPolicy` — a rewritten sentence must keep or explicitly downgrade the original
    factual claim; no stale price rides onto a new link.
  - `ScopePolicy` — reference slots are never `REPLACE_URL`; `DROP_BLOCK` only for
    incidental roles.
  - `WritePolicy` — every Writer tool call must carry an approved `decision_id`, else it's
    refused.
- **Interrupt, two tracks** — a synchronous gate for the live demo, and an asynchronous
  durable decision-queue worker for production. Same `Proposal` schema, same write gate.
- **Hooks** — every tool call is audited; the write gate is a `BeforeToolCall` hook.
- **Structured Output (Pydantic)** — the Judge is forced to emit a typed `Proposal`.
- **Detection with no product API** — RapidAPI / RainForest / Amazon PA-API were all
  discontinued for me, so detection works from the outside in (HTTP + page parse). Anything
  blocked or timed out is flagged `needs_human_recheck` — the agent never fabricates a
  result.
- **"Any model," one seam** — every agent takes an injected `strands.models.Model`. The
  deployed nightly runs a **real Bedrock model** (qwen via AWS's Bedrock Mantle gateway,
  which bypasses the account-level Anthropic allowlist gate that blocks direct SigV4
  Claude), and the same seam accepts `BedrockModel` / Anthropic / OpenAI / Gemini /
  Mistral / Ollama / LiteLLM / SageMaker providers or a `ModelRouter` failover. The entire
  254-test suite and the 50-case Evals run offline on an injected `StubModel` — the real
  proof of provider-independence.
- **OpenTelemetry** — optional tracing renders a run as one span tree (`run → {detect,
  judge, score}`), with Strands' own model/tool spans nested under the judge.
- **Deploy** — Next.js board on Vercel, Neon Postgres store, nightly cron on Railway
  (AgentCore runtime as the stretch path). Source-site DB access is strictly read-only, and
  a write guardrail (`db._assert_writable`) refuses any DSN matching a source-site or
  deny-list host, so the production instance can never be written even by accident.

### Challenges we ran into

- **No product-data API.** With PA-API / RapidAPI / RainForest unavailable, I built a
  two-layer detection pyramid from raw HTTP signals and stealthy page parsing, and made
  "I can't tell" a first-class, honest verdict (`needs_human_recheck`).
- **A write-back agent is dangerous.** Letting an LLM edit live content demanded real
  guardrails: snapshot-before-write in a single transaction, four steering policies, a
  decision-id write gate, and a `verify_fix` re-probe that rolls back on failure.
- **Interrupt without blocking a nightly run.** Strands' Interrupt maps to two tracks — a
  sync gate for the demo and a durable decision queue for production — so autonomy never
  depends on a human being awake.
- **Honesty about what's real.** Offline stub results prove detection and the guardrail
  plumbing; the *live* LLM judgment now runs for real in production through Bedrock Mantle
  (qwen), scored with the identical harness. I keep the offline and live paths clearly
  separated so no stub result is ever passed off as model judgment.

### Accomplishments we're proud of

- A **50-case evaluation suite** that scores detection ≥ 90% (100% on stub), zero steering
  violations, and three hard metrics at 100% — disclosure zero-deletion, reference
  zero-`REPLACE_URL`, duplicate merged to one card. A test injects a rule-breaking Judge to
  prove the oracle isn't vacuous.
- The **closed loop**: `verify_fix` re-probes after every write and rolls back on failure.
  On the seeded demo night, 37 dead links verify back to zero — and I show a rollback too.
- **254 passing tests**, fully offline; a `generic` read-only adapter that scans any blog
  EverLink has never seen; a seeded live board so a judge never opens an empty inbox.
- Six Mermaid **architecture diagrams** rendered natively on GitHub, and a secrets-clean
  repo (only `.env.example`, placeholders, gitignored data snapshots).

### What we learned

- **Autonomy is earned, not toggled.** EverLink's write access comes from three layers —
  steering policies, a decision-id write gate, and a `verify_fix` re-probe — not from
  trusting the model. We shipped the guardrails first and let autonomy grow inside them.
- **"I can't tell" is a valid verdict.** Making `needs_human_recheck` first-class (instead
  of guessing on blocked or timed-out pages) is what makes the agent trustworthy enough to
  run unattended on production content.
- **Detection and judgment are different jobs.** Deterministic code proves a link is dead;
  deciding the fix is judgment. Keeping them separate — and scoring them with separate
  harnesses — kept our evals honest about what the stub proves and what only a live model
  (or a human) can.
- **Humans should approve decisions, not links.** Merging duplicate problems across
  articles into one card turned forty interruptions into one. An empty inbox on a good
  night is the product working, not a missing feature.
- **Provider independence is availability.** When account-level Bedrock access stalled
  mid-hackathon, the single injected-Model seam kept every nightly run alive and let me
  swap in the Bedrock Mantle gateway (qwen) to restore a **real** LLM judge with zero
  pipeline edits. The honesty-driven design doubled as resilience.

### What's next for EverLink

Write-back is AethelGem-only for the hackathon; extending it to the other two sites is next.
Price-drift detection stays at the page-parse layer until a real L3 price API exists. And
the inbox stays deliberately minimal — one screen, not a suite.

---

## Built with

`strands-agents` · `amazon-bedrock` · `anthropic-claude` · `python` · `next.js` ·
`neon-postgres` · `vercel` · `railway` · `opentelemetry` · `pydantic` · `resend` ·
`telegram-bot`

## Links (fill at submit time)

- **Repo:** https://github.com/tomyuya/everlink (public, MIT)
- **Architecture Diagram:** `ARCHITECTURE.md` in the repo (also uploaded to Devpost's
  separate diagram field)
- **Live demo:** *(owner: Vercel board URL once deployed)*
- **Demo video:** *(owner: ≤ 5:00, from `DEMO_SCRIPT.md`)*
- **Blog:** *(owner: builder.aws.com URL once published, from `BLOG_DRAFT.md`)*
