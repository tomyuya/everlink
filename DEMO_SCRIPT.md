# EverLink — Demo Video Script (≤ 5:00, two-demo focus)

Read-aloud voiceover for the ≤5-minute demo video. Re-cut 2026-09-07 to put the weight on the
**two demo paths**: Act 1/2 (positioning, principle, how-to) are compressed to ~1:15 so Act 3
gets ~3:25 to walk **Path B** (first-party DB snapshot → full loop) and **Path A** (generic
read-only crawl) each through **how you operate it → how it processes → what it shows**.
The machine-readable read-aloud text (marks stripped) lives in `docs/video/vo_full.txt`.

**Three-act structure:** Act 1 intro 0:00–0:55 · Act 2 how-to + the two paths 0:55–1:15 ·
Act 3 the two demos 1:15–4:40 (Demo 1 Path B 1:15–3:35, Demo 2 Path A 3:35–4:40) ·
Close 4:40–5:00.

> **Recording is an owner action.** Re-confirm every cited number against the live/seeded
> environment before recording; mask DB hosts / tokens / `.env` on screen.

**Honesty labels** (keep visible on screen or in voiceover):
- **[REAL]** — deterministic detection code or a live Amazon Bedrock model call.
- **[SEEDED REPLAY]** — the injected demo dataset (`scripts/seed_demo.py`), labelled on screen.
- **[EST.]** — an estimate, not a measured figure.

**The two paths (official framing, manual §"Two ways to feed it"):**
- **Path A · generic read-only crawl** — `scan --site <any sitemap/page URL>`; public pages over
  read-only HTTP; ANY website, no code change, L1/L2 needs zero AWS credentials, **never writes
  back**; honours robots.txt, ≤1 request per link. Result = a terminal report.
- **Path B · first-party DB snapshot** — read-only connect to your own source DB
  (`export_slots.py` → CSV) for block-level slots, LLM Judge proposals, gated write-back, and
  the human approval board.

---

# Act 1 — Intro (0:00–0:55)

## Shot 1 — 0:00–0:08 · Positioning card
**On screen:** title card `#positioning` — "The autonomous link-rot steward." + open-source /
self-hosted / you-approve line.
**Voiceover:**
> "EverLink is an open-source, self-hosted link-rot steward. Checkers only *report* — EverLink
> **decides**, and you approve."

## Shot 2 — 0:08–0:16 · Scale card
**On screen:** title card `#stats` — 23,476 outbound slots across 3 sites; last manual check: never.
**Voiceover:**
> "These are my three content sites: twenty-three thousand outbound link slots. The last time
> every one was checked by hand? Never."

## Shot 3 — 0:16–0:24 · The real sites
**On screen:** www.aethelgem.com → hotdeals.today, ~4s each.
**Voiceover:**
> "They rot a little every day, and nobody sees it until a reader does. So an agent patrols them."

## Shot 4 — 0:24–0:34 · The three questions
**On screen:** title cards WHO · WHY AN AGENT; a "Professional Agents track" badge.
**Voiceover:**
> "Who it's for: independent publishers and small content teams — we're entering the
> Professional Agents track. Why an agent: decide-and-escalate is repetitive, judgment-heavy
> work — exactly what an agent should take on."

## Shot 5 — 0:34–0:47 · The principle
**On screen:** title card `#principle` — PATROL / DECIDE / ACT & PROVE + honesty label line.
**Voiceover:**
> "The principle in three lines. Patrol: every outbound link, every night. Decide: a real LLM
> Judge on Amazon Bedrock drafts the fix, constrained by four Steering policies. Act and prove:
> apply, re-verify, roll back on failure — every step in a public audit trail."

## Shot 6 — 0:47–0:55 · Where to find it
**On screen:** title card `#resources` — repo + live URL in display type.
**Voiceover:**
> "Open source under MIT: github dot tomyuya slash everlink. And a live example: everlink-seven
> dot vercel dot app."

---

# Act 2 — How to use it + the two paths (0:55–1:15)

## Shot 7 — 0:55–1:15 · `/` primer, two stops
**On screen:** the product page: top = positioning + three badges + two-database model; one
End-keypress to the bottom = pipeline diagram + automation panel + the two feed paths.
**Voiceover:**
> "How you use it: clone it, deploy it on your own infrastructure. Links get in two ways. Path A:
> a generic read-only crawl of any website — no database, no credentials, never writes back.
> Path B: a read-only snapshot of your own database, unlocking block-level fixes and gated
> write-back. Your source database stays strictly read-only either way."

---

# Act 3 — The two demos (1:15–4:40)

## Demo 1 — Path B, the full loop on my own site (1:15–3:35)

### Shot 8 — 1:15–2:05 · Operate + process · **Technological Implementation**
**On screen:** terminal. Press enter at **1:15** on
`python -m everlink scan --site aethelgem --judge mantle --dry-run --limit 6` (measured 39s/56s,
report lands 1:54–2:11; **2:05 is the cut decision point**). Real qwen proposals scroll; the
`--dry-run` honesty line stays in frame.
**Voiceover:**
> "Demo one: Path B, the full loop on my own site — the nightly cron's loop, run by hand,
> dry-run, so nothing is written. **[operate]** I type:
> everlink scan, site aethelgem, judge mantle, dry-run, limit six. **[process]** A Scanner agent
> pulls each link slot from my database snapshot and probes it — L1 HTTP status and
> redirect-chain analysis first, then an L2 stealthy page parse only where L1 is inconclusive. A
> Judge agent — a real LLM on Amazon Bedrock — reads that evidence and drafts a structured
> Proposal: replace this URL, rewrite that anchor, or escalate. Anything blocked or timed out is
> flagged needs-human-recheck: the agent knows its limits and never fabricates. **[REAL]**"

### Shot 9 — 2:05–2:20 · Show: report + morning brief · **Design**
**On screen:** the scan report frozen (evidence + proposals); then, only if landed,
`python -m everlink notify --brief --dry-run` (2–8s) — the brief and its "nothing sent" line.
**Voiceover:**
> "**[show]** The scan report lands: real proposals scrolling, each with its evidence chain.
> Then the morning brief: sixteen problem slots, pushed to me as a notification, not an app."

### Shot 10 — 2:20–2:45 · Show: the approval inbox · **Design**
**On screen:** Board `/inbox` — 16 pending cards, live checkboxes, batch approve/reject bar;
`?status=applied` (37) → `?status=rejected` (69) → rejection card `dec-7158d74e33` with typed why.
**Voiceover:**
> "The only screen I open: the decision inbox. Sixteen cards wait, each with its evidence
> and its proposed fix. I approve the safe ones in a batch; I read the risky ones individually.
> Rejections carry a typed *why* — and the agent remembers it, so it won't re-propose the same
> fix next week. **[SEEDED REPLAY]**"

### Shot 11 — 2:45–3:10 · Show: the two guards + closed loop · **Creativity / Design**
**On screen:** `/audit?event=steering_cancel` (3 rows) + `dec-2b91672858`; then `dec-b21f3d82bc`
(Evidence = post-apply URL, `Healthy HTTP 200`); `/audit?event=write` + `?event=verify` (38 each);
`/report` (healed 37); `?event=rollback` + `?event=dead_letter` (1 each).
**Voiceover:**
> "Two guards matter most. This disclosure block is dead — but deleting it is a legal disaster,
> so a Steering policy cancels the drop and the audit logs steering-cancel. And
> when I approve a fix, the Writer snapshots the block, applies in one transaction, then re-probes
> the new link to prove it's alive. **[REAL]** If verification fails, it rolls back and
> dead-letters the decision. Last night: thirty-seven links healed, verified back to zero.
> **[SEEDED REPLAY]**"

### Shot 12 — 3:10–3:35 · Show: I test it, not trust it · **Technological Implementation**
**On screen:** terminal. Press enter at **3:10** on `python scripts/run_evals.py --full --trace
console` (19–22s; summary ~3:30): detection 50/50=100%, steering 0, three hard metrics 100%.
**Voiceover:**
> "And I don't ask you to trust the agent — I test it. A fifty-case eval suite runs offline
> against known ground truth: detection one hundred percent, steering violations zero, three hard
> metrics at one hundred percent. And the oracle is proven non-vacuous. **[REAL]**"

## Demo 2 — Path A, the generic read-only crawl (3:35–4:40)

### Shot 13 — 3:35–3:45 · Operate · **Design**
**On screen:** terminal. Press enter at **3:35** on
`python -m everlink scan --site https://blog.python.org --include-internal --dry-run --limit 8`
(measured 10s/58s; **4:15 is the cut decision point**).
**Voiceover:**
> "Demo two: Path A, the generic read-only crawl. No database, no code change, no credentials.
> **[operate]** I point it at a site EverLink has never seen: everlink scan, site blog dot python
> dot org, include-internal, dry-run, limit eight."

### Shot 14 — 3:45–4:15 · Process · **Technological Implementation**
**On screen:** the crawl scrolling: robots.txt → sitemap (index banner if applicable) → page
fetches → outbound-slot table → per-link probes.
**Voiceover:**
> "**[process]** Watch it work. It honours robots.txt, fetches the sitemap — and if that's an
> index, it says so and expands one — crawls a few pages, extracts every
> outbound link, skips social-share and same-site links as noise, then probes each survivor over
> read-only HTTP: at most one request per link, politely rate-limited. No LLM, no credentials,
> and it never writes back — not here, not anywhere."

### Shot 15 — 4:15–4:40 · Show: the report + A vs B · **Impact / Design**
**On screen:** the frozen terminal report: per-slot HTTP verdicts, a healthy count (8/8), and the
honesty line `--dry-run: nothing written to any database`.
**Voiceover:**
> "**[show]** The payoff: a plain link-rot report in the terminal — every outbound
> slot with its HTTP verdict, a healthy count, and the honesty line: read-only, nothing written.
> That is the whole point of Path A: any website, a real report in under a minute, zero setup.
> Path B goes deeper — block-level fixes and write-back on your own site. Path A is the door;
> Path B is the house."

---

# Close (4:40–5:00)

## Shot 16 — 4:40–5:00 · Close card
**On screen:** final title card `#end`: "You approve decisions, not links."
**Voiceover:**
> "EverLink patrols twenty-three thousand links so I don't have to. It's honest about its limits,
> never touches my disclosures, verifies its own fixes, and hands me back about six hours a
> week. Built with the Strands Agents SDK and Amazon Bedrock for Agents for Humans. You approve
> decisions, not links."

---

## Timing & coverage check

| Requirement | Where | ✓ |
|---|---|---|
| Total ≤ 5:00 | 16 shots, last ends 5:00; vo_full 实测 **4:57.1**（edge-tts AndrewNeural） | stopwatch at record time |
| Positioning / problem / who / why | Shots 1–4 | ✓ |
| Principle | Shot 5 + Shot 7 pipeline | ✓ |
| Resources | Shot 6 | ✓ |
| How-to + two paths framed | Shot 7 | ✓ |
| **Demo 1 Path B: operate / process / show** | Shot 8 (operate+process), 9–12 (show) | ✓ |
| **Demo 2 Path A: operate / process / show** | Shot 13 (operate), 14 (process), 15 (show) | ✓ |
| Real primary, replay labelled | Shots 8/10/11/12 carry [REAL]/[SEEDED REPLAY] | ✓ |
| Strands features visible | multi-agent (8), steering (11), hooks/audit (11), structured output (8), evals (12), Bedrock (5/8/16), OTel (12) | ✓ |
| Sensitive values masked | owner at record time | ✓ |
