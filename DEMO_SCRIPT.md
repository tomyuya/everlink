# EverLink — Demo Video Script (Phase H, ≤ 5:00)

Read-aloud pre-script for the ≤5-minute demo video (spec §9 Phase H, §11 storyboard).
If recording runs long, the fallback is: OBS screen-capture + read this script verbatim,
keep it under 5:00 (spec §9).

> **Recording is an owner action.** This file is the prepared script + shot list only.
> Before recording, re-confirm every cited number against the live/seeded environment
> (the real nightly scan count will differ from the seeded replay). Mask/blur any
> sensitive value on screen — DB hosts, URLs with tokens, `.env` (SUBMISSION_CHECKLIST §8).

**Honesty labels used below** (keep them visible on screen or in voiceover):
- **[REAL]** — deterministic detection code or a live Bedrock Claude call, no fakery.
- **[SEEDED REPLAY]** — the injected demo dataset (`scripts/seed_demo.py`, 41 problem
  slots + approve/reject samples + audit trail). Pre-computed, and labelled as replay
  on screen per spec §4.1 / §7.
- **[EST.]** — an estimate, not a measured figure.

Cast: one operator (the author). Environment: terminal + Decision Board (Next.js) +
email/Telegram. Judge backend for the live shots: `--judge bedrock` (real Claude);
the seeded card shots are replay.

---

## Shot 1 — 0:00–0:30 · Cold open on the real problem · **Impact**

**On screen:** the three production site backends / article lists, then a single
line of text built from `data/slots_summary.json`:

```
23,476 outbound link slots across 3 production sites
last full manual check: never
```

**Voiceover:**
> "These are my three content sites. Between them they carry **23,476 outbound link
> slots** — product cards, affiliate links, references. The last time every one of them
> was checked by hand? **Never.** They rot a little every day, and nobody sees it until
> a reader does."

---

## Shot 2 — 0:30–1:00 · The pitch: problem / who / why · **Presentation**

**On screen:** three title cards — PROBLEM · WHO · WHY — or the operator to camera.

**Voiceover (the three questions, explicitly):**
> "**The problem:** links rot — products 404, affiliate programs end, a price drifts
> from the sentence that cites it. Broken-link checkers only *report*. They never decide
> *what to do*.
> **Who it's for:** independent publishers, affiliate creators, and small content teams —
> one to three people running several sites. The first user is me; EverLink patrols my
> own production sites.
> **Why an agent:** 'replace, rewrite the anchor, rewrite the sentence, drop the block,
> or escalate to a human' is a repetitive, judgment-heavy task. That's exactly the work
> an agent should take on — running in the background, and surfacing **only** when there's
> a real decision to make."

---

## Shot 3 — 1:00–1:35 · The nightly run · **Technological Implementation**

**On screen:** terminal. `python scripts/nightly.py` (or `python -m everlink scan --site
aethelgem --judge bedrock`). Three agent logs interleave — Scanner → Judge → Writer —
under one Orchestrator. Then the morning brief lands in email / Telegram. Cut to the
Board showing the seeded problem queue.

**Voiceover:**
> "Every night a cron kicks off the loop. A **Scanner** agent extracts each link slot and
> probes it — L1 HTTP status and redirect-chain analysis, then an L2 stealthy page parse
> only where L1 is inconclusive. A **Judge** agent — Claude on Bedrock — decides the fix
> and emits a structured `Proposal`. **[REAL]** The detection is deterministic code; the
> judgment is a live model call. Anything blocked or timed out is flagged
> `needs_human_recheck` — the agent knows its limits and never fabricates a result. By
> morning, **41 problem slots** are waiting **[SEEDED REPLAY for the demo queue]**, pushed
> to me as a morning brief. It surfaces as a notification, not an app."

---

## Shot 4 — 1:35–2:15 · The decision inbox · **Design**

**On screen:** the Decision Board. A batch of low-risk cards → **approve 38**. Three
medium/high cards reviewed one by one → **reject 3**, typing a reason. Zoom a
**cross-article merged card** (the same dead product cited in two articles → one decision).
Show the reject reason being stored.

**Voiceover:**
> "The only screen I open is a minimal approval inbox. Low-risk fixes are batched — I
> approve **38** in one click. **[SEEDED REPLAY]** The risky ones I read individually: here
> I reject three, and I type *why* — the agent remembers that reason and won't re-propose
> the same thing next week. And because the same dead product appears in two articles,
> EverLink merges them into **one** decision card, so I decide once, not twice. You approve
> **decisions**, not links."

---

## Shot 5 — 2:15–2:50 · Safety curtain 1: the disclosure guard · **Creativity & Originality**

**On screen:** a block whose sentence contains an affiliate-disclosure keyword
("affiliate", "commission", "we may earn"). It's also a dead link. The Judge proposes
`DROP_BLOCK` — and the Steering hook **cancels** the tool call. Show the `audit_log` line
`steering_cancel` and the card downgrading to `ESCALATE_HUMAN`.

**Voiceover:**
> "Here's the guardrail I care about most. This block is a dead link — but it also carries
> my **affiliate disclosure**. Deleting it would be a legal and trust disaster. A
> `DisclosurePolicy` steering hook marks the slot `protected` and **cancels** the drop
> before it happens; the agent downgrades to 'escalate to a human'. Disclosure text is
> structurally immune — no write action can touch it."

---

## Shot 6 — 2:50–3:40 · Safety curtain 2 + the closed loop · **Design / Impact**

**On screen:** (a) An approved `REWRITE_SENTENCE` — show the before/after: the price claim
in the old sentence is removed or explicitly downgraded, not silently carried onto a new
link (`EditorialPolicy`). (b) The approved write executes: `snapshot_block` → `apply_fix`
in a **single transaction** → `verify_fix` re-probes the new URL. Show the dead-count drop
**37 → 0**, all green. (c) Then force one `verify_fix` to fail and show the **rollback**
restore the original block + emit a rollback-recommendation card.

**Voiceover:**
> "An editorial policy makes sure a rewritten sentence never keeps a stale price or
> superlative claim. When I approve, the Writer **snapshots the block first**, applies the
> fix in a single transaction, then — this is the part that matters — `verify_fix`
> **re-probes the new link** to confirm it's genuinely alive. **[REAL]** Tonight: **37 dead
> links verified back to zero.** **[SEEDED REPLAY]** And if verification ever fails, the
> writer rolls back to the snapshot and dead-letters the decision with a recommendation
> card. It closes the loop; it doesn't just claim success."

---

## Shot 7 — 3:40–4:10 · Evals: 50 cases, three hard metrics · **Technological Implementation**

**On screen:** terminal. `python scripts/run_evals.py --full`. The report prints:
detection 50/50 = 100%, steering violations 0, and the three hard metrics at 100%
(disclosure zero-deletion, reference zero-`REPLACE_URL`, duplicate merged → 41 cards).
Optionally `--trace console` to flash the OpenTelemetry span tree.

**Voiceover:**
> "I don't ask you to trust the agent — I test it. A 50-case evaluation suite runs against
> a fixture server with known ground truth, fully offline. Detection accuracy **100%**,
> steering violations **zero**, and three hard metrics at **100%**: a disclosure is never
> deleted, a reference link is never blindly replaced, and duplicates always merge to one
> card. The oracle is proven non-vacuous by a test that injects a rule-breaking Judge and
> asserts the evaluators catch it. **[REAL — stub backend: detection is real deterministic
> code; the live Claude Judge is scored with the same harness via `--judge bedrock`.]**"

---

## Shot 8 — 4:10–4:40 · The generic adapter + live demo · **Impact / Design**

**On screen:** point EverLink's `generic` read-only adapter at an arbitrary well-known
blog (`--site generic --include-internal`), produce a dead-link report for a site EverLink
has never seen. Then click the **live demo link** (Vercel board, seeded so the inbox is
never empty).

**Voiceover:**
> "This isn't hard-coded to my sites. A `generic` adapter will scan **any** blog — read-only
> — and hand back a link-rot report. Here it is on a site EverLink has never seen. And
> here's the live board, seeded so there's always something real to look at. **[live URL if
> deployed; otherwise show the local board and say so honestly.]**"

---

## Shot 9 — 4:40–5:00 · Close · **Presentation**

**On screen:** the operator to camera, or the weekly report page. Final line card:

```
You approve decisions, not links.
```

**Voiceover:**
> "EverLink patrols 23,476 links so I don't have to. It's honest about what it can't do,
> it never touches my disclosures, it verifies its own fixes, and it rolls back when it's
> wrong. By my estimate it removes about **6.2 hours a week [EST.]** of link maintenance —
> and it only ever interrupts me when a human judgment actually matters. Built with the
> **Strands Agents SDK** and **Amazon Bedrock** for **Agents for Humans**. You approve
> decisions, not links."

---

## Timing & coverage check (spec §12-6)

| Requirement | Where | ✓ |
|---|---|---|
| Total ≤ 5:00 | 9 shots, last ends 5:00 | stopwatch at record time |
| Problem stated | Shot 2 | ✓ |
| Who it's for stated | Shot 2 | ✓ |
| Why (an agent) stated | Shot 2 | ✓ |
| Real data primary, replay labelled | Shots 3/4/6 carry **[SEEDED REPLAY]**; detection/verify/evals **[REAL]** | ✓ |
| Strands features visible | multi-agent (3), steering (5,6), interrupt (4), hooks/audit (5), structured output (4), evals (7), Bedrock (3,9), OTel (7) | ✓ |
| Sensitive values masked | DB hosts / tokens / `.env` blurred | owner at record time |
