# EverLink — Demo Video Script (Phase H, ≤ 5:00, three-act)

Read-aloud pre-script for the ≤5-minute demo video (spec §9 Phase H, §11 storyboard).
If recording runs long, the fallback is: OBS screen-capture + read this script verbatim,
keep it under 5:00 (spec §9).

**Three-act structure (re-cut 2026-09-05, fourth rehearsal):** Act 1 intro 0:00–1:07
(positioning / scale / real sites / three questions / principle / resources), Act 2 how to
use it 1:07–1:27 (`/how-it-works`), Act 3 the demo 1:27–5:00. Judges need the "what / who /
why / where" anchor inside the first 30 seconds; a cold open on a terminal loses them.

> **Recording is an owner action.** This file is the prepared script + shot list only.
> Before recording, re-confirm every cited number against the live/seeded environment
> (the real nightly scan count will differ from the seeded replay). Mask/blur any
> sensitive value on screen — DB hosts, URLs with tokens, `.env` (SUBMISSION_CHECKLIST §8).

**Honesty labels used below** (keep them visible on screen or in voiceover):
- **[REAL]** — deterministic detection code or a live Amazon Bedrock model call, no fakery.
- **[SEEDED REPLAY]** — the injected demo dataset (`scripts/seed_demo.py`, 41 problem
  slots + approve/reject samples + audit trail). Pre-computed, and labelled as replay
  on screen per spec §4.1 / §7.
- **[EST.]** — an estimate, not a measured figure.

Cast: one operator (the author). Environment: terminal + Decision Board (Next.js) +
email/Telegram. Judge backend for the live shots: `--judge mantle` — a **real LLM on Amazon
Bedrock** (qwen through AWS's Bedrock Mantle gateway), rehearsed locally twice on
2026-09-05 at 39s and 56s for `--limit 6`; the seeded card shots are replay.

---

# Act 1 — Intro (0:00–1:07)

## Shot 1 — 0:00–0:10 · Positioning card · **Presentation**

**On screen:** title card `#positioning` — "The autonomous link-rot steward." plus
open-source / self-hosted / you-approve-one-line.

**Voiceover:**
> "EverLink is an **open-source, self-hosted link-rot steward**. Checkers only *report* —
> EverLink **decides**, and you approve."

---

## Shot 2 — 0:10–0:20 · Scale card · **Impact**

**On screen:** title card `#stats` — 23,476 outbound link slots across 3 production sites;
last full manual check: never.

**Voiceover:**
> "These are my three content sites: **23,476 outbound link slots** between them. The last
> time every one was checked by hand? **Never.**"

---

## Shot 3 — 0:20–0:30 · The real sites · **Impact**

**On screen:** www.aethelgem.com → hotdeals.today, five seconds each (third site
flashdeals.today is named but not navigated, to keep the pace).

**Voiceover:**
> "They rot a little every day — and nobody sees it until a reader does. So tonight, an
> agent patrols them."

---

## Shot 4 — 0:30–0:42 · The three questions · **Presentation**

**On screen:** title cards PROBLEM · WHO · WHY AN AGENT, four seconds each.

**Voiceover:**
> "The problem: links rot, and checkers only report. Who it's for: independent publishers
> and small content teams. Why an agent: decide-and-escalate is repetitive,
> judgment-heavy work — exactly what an agent should take on."

---

## Shot 5 — 0:42–0:57 · The principle · **Technological Implementation**

**On screen:** title card `#principle` — three cards on one screen: 1 · PATROL,
2 · DECIDE, 3 · ACT & PROVE, closing with the honesty label line
`[REAL] · [SEEDED REPLAY] · [EST.]`.

**Voiceover:**
> "The principle in three lines. **Patrol:** every outbound link, every night. **Decide:**
> a real LLM Judge on Amazon Bedrock drafts the fix, and four Steering policies constrain
> it. **Act and prove:** apply, re-verify, roll back on failure — every step lands in a
> public audit trail."

---

## Shot 6 — 0:57–1:07 · Where to find it · **Presentation**

**On screen:** title card `#resources` — `github.com/tomyuya/everlink` (MIT, self-host
runbook) and `everlink-seven.vercel.app` (read-only live example), both in display type.

**Voiceover:**
> "Open source under MIT: **github.com/tomyuya/everlink**. And a live, read-only example:
> **everlink-seven.vercel.app**."

---

# Act 2 — How to use it (1:07–1:27)

## Shot 7 — 1:07–1:27 · `/how-it-works`, two stops · **Design**

**On screen:** the public primer page. Stop 1 at the top: the positioning paragraph with
its three badges (Open source · MIT / Self-hosted / Not a SaaS) and the two-database
model (your database strictly read-only; EverLink writes only to its own). Stop 2: one
End-keypress to the bottom (page is ~2.1 viewports tall) — the deployer contract's five
items, the **Scanner → Judge → Writer pipeline diagram**, the automation panel, and the
honest note that the three sites shown are the maintainer's own dogfooding deployment.

**Voiceover:**
> "How you use it: clone it, point it at your databases, deploy it on your own
> infrastructure. Your site's database stays **strictly read-only**; EverLink writes only
> to its own. The pipeline is Scanner, Judge, Writer — a nightly cron at one end, and a
> human at the other."

---

# Act 3 — The demo (1:27–5:00)

## Shot 8 — 1:27–2:23 · The nightly run · **Technological Implementation**

**On screen:** terminal. `python -m everlink scan --site aethelgem --judge mantle --dry-run
--limit 6` (press enter at **1:27** — measured 39s and 56s on two runs, so the report lands
between 2:06 and 2:23; **2:12 is the cut decision point**), then, only if the report has
landed, `python -m everlink notify --brief --dry-run` (2–8s, the morning brief with 16
cards and its "nothing sent" honesty line). Cut to the Board's `/inbox` showing the
problem queue. Both `--dry-run` honesty lines stay in frame.

**Voiceover:**
> "Every night a cron kicks off the loop. A **Scanner** agent extracts each link slot and
> probes it — L1 HTTP status and redirect-chain analysis, then an L2 stealthy page parse
> only where L1 is inconclusive. A **Judge** agent — a real LLM on Amazon Bedrock — decides
> the fix and emits a structured `Proposal`. **[REAL]** The detection is deterministic code; the
> judgment is a live model call. Anything blocked or timed out is flagged
> `needs_human_recheck` — the agent knows its limits and never fabricates a result. By
> morning, **16 problem slots** are waiting **[live nightly proposals + seeded replay
> cards, each labelled]**, pushed to me as a morning brief. It surfaces as a
> notification, not an app."

---

## Shot 9 — 2:23–2:43 · The decision inbox · **Design**

**On screen:** the Decision Board `/inbox` — 16 pending cards, read-only notice line
visible (approve/reject is disabled on the public deployment by design).

**Voiceover:**
> "The only screen I open is a minimal approval inbox. Sixteen problem slots wait here —
> each with its evidence and its proposed fix."

---

## Shot 10 — 2:43–3:05 · Batched, rejected, remembered · **Design**

**On screen:** `/inbox?status=applied` (**37** applied and verified) →
`/inbox?status=rejected` (**69**, every one carrying a reason) → the rejection card
`dec-7158d74e33` with its typed why (price moved $199→$349, the "under $200" claim went
stale).

**Voiceover:**
> "Low-risk fixes are batched — **37** applied and verified so far. **[SEEDED REPLAY]** The
> risky ones I read individually: rejections like this carry a typed *why*, and the agent
> remembers that reason — it won't re-propose the same fix next week."

---

## Shot 11 — 3:05–3:27 · Safety curtain 1: the disclosure guard · **Creativity & Originality**

**On screen:** `/audit?event=steering_cancel` (filter chip, 3 rows) and the disclosure
slot's decision card `dec-2b91672858` carrying the human's typed acknowledgement: no write
may touch the protected block.

**Voiceover:**
> "Here's the guardrail I care about most. This block is a dead link — but it also carries
> my **affiliate disclosure**. Deleting it would be a legal and trust disaster. A
> `DisclosurePolicy` steering hook marks the slot `protected` and **cancels** the drop
> before it happens; the audit log records `steering_cancel`, and a human confirmed on the
> record: no write may touch it."

---

## Shot 12 — 3:27–3:57 · Safety curtain 2 + the closed loop · **Design / Impact**

**On screen:** (a) the approved card `dec-b21f3d82bc` (Applied · High · Replace URL; the
Evidence block renders the **post-apply new URL** with `Healthy HTTP 200`). (b) The audit
filters `/audit?event=write` and `/audit?event=verify` (38 rows each: snapshot → apply in
a single transaction → re-probe). (c) `/report`: **Links healed 37 / Slots fixed 37**.
(d) The one forced-fail on record: `/audit?event=rollback` + `/audit?event=dead_letter`
(1 row each).

**Voiceover:**
> "When I approve, the Writer **snapshots the block first**, applies the fix in a single
> transaction, then — this is the part that matters — `verify_fix` **re-probes the new
> link** to confirm it's genuinely alive. **[REAL]** Last night: **37 dead links verified
> back to zero.** **[SEEDED REPLAY]** And if verification ever fails, it rolls back to the
> snapshot and dead-letters the decision with a recommendation card. It closes the loop;
> it doesn't just claim success."

---

## Shot 13 — 3:57–4:22 · Evals: 50 cases, three hard metrics · **Technological Implementation**

**On screen:** terminal. `python scripts/run_evals.py --full --trace console` (press enter
at **3:57**; measured 19–22s, summary lands 4:16–4:19). The report prints: detection
50/50 = 100%, steering violations 0, and the three hard metrics at 100% (disclosure
zero-deletion, reference zero-`REPLACE_URL`, duplicate merged → 41 cards), plus the
honesty note naming `--judge mantle` as the route that scores the real Judge.

**Voiceover:**
> "I don't ask you to trust the agent — I test it. A 50-case evaluation suite runs against
> a fixture server with known ground truth, fully offline. Detection accuracy **100%**,
> steering violations **zero**, and three hard metrics at **100%**: a disclosure is never
> deleted, a reference link is never blindly replaced, and duplicates always merge to one
> card. The oracle is proven non-vacuous by a test that injects a rule-breaking Judge and
> asserts the evaluators catch it. **[REAL — stub backend: detection is real deterministic
> code; the live Judge (qwen on Amazon Bedrock via the Mantle gateway) is scored with the
> same harness via `--judge mantle`.]**"

---

## Shot 14 — 4:22–4:42 · The generic adapter · **Impact / Design**

**On screen:** point EverLink's `generic` read-only adapter at an arbitrary well-known blog
— rehearsed command: `python -m everlink scan --site https://blog.python.org
--include-internal --dry-run --limit 8` (press enter at **4:22**; measured 10s and 58s on two
runs — external network, so **4:38 is the cut decision point**: if the report has landed,
hold on 8/8 healthy, otherwise cut to the closing card while the real crawl keeps
scrolling).

**Voiceover:**
> "This isn't hard-coded to my sites. A `generic` adapter will scan **any** blog —
> read-only — and hand back a link-rot report. Here it is on a site EverLink has never
> seen. Read-only, everywhere."

---

## Shot 15 — 4:42–5:00 · Close · **Presentation**

**On screen:** final title card `#end`:

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
| Total ≤ 5:00 | 15 shots in three acts, last ends 5:00 | stopwatch at record time |
| Positioning stated | Shot 1 (card) + Shot 7 (page) | ✓ |
| Problem stated | Shots 2–4 | ✓ |
| Who it's for stated | Shot 4 | ✓ |
| Why (an agent) stated | Shot 4 | ✓ |
| Principle stated | Shot 5 (card) + Shot 7 (pipeline diagram) | ✓ |
| Resources stated | Shot 6 (card: repo + live URL) | ✓ |
| How to use stated | Shot 7 (deployer contract, read-only source DB) | ✓ |
| Real data primary, replay labelled | Shots 8/10/12 carry **[SEEDED REPLAY]**; detection/verify/evals **[REAL]** | ✓ |
| Strands features visible | multi-agent (3), steering (5,11,12), interrupt (10), hooks/audit (11), structured output (10), evals (13), Bedrock (5,8,15), OTel (13) | ✓ |
| Sensitive values masked | DB hosts / tokens / `.env` blurred | owner at record time |
