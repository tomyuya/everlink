# EverLink — Submission Checklist

Hackathon: **AWS "Agents for Humans"** (Devpost) · Track: **Professional Agents**
Deadline: **2026-09-15 08:00 GMT+8**

Every item below must be ✅ before submission. This file is the single source of
truth for "are we done" — mirror it on the wall from Day 1 (spec §10).

**Legend.** `[x]` = done and verifiable in the repo (commit evidence inline).
`[ ] (owner)` = a human-only action EverLink cannot perform for itself (register
an AWS account, flip the repo to public, record/upload a video, publish a blog,
click submit on Devpost). Those stay open by design and are the last mile.

## Required deliverables

- [ ] (owner) **1. Devpost text description** — covers problem / who it's for / how it works.
      Draft is written → [`DEVPOST.md`](DEVPOST.md); pasting it into the Devpost form is the
      owner step.
- [~] **2. Public repo + MIT LICENSE + README** — README includes setup instructions.
      - [x] `LICENSE` present (MIT, © 2026 tomyuya)
      - [x] `README.md` present with setup + architecture (pg2 · `6baf2dd`)
      - [ ] (owner) repo is public — flip the GitHub visibility switch before submitting
- [x] **3. Architecture Diagram** — [`ARCHITECTURE.md`](ARCHITECTURE.md), 6 Mermaid views
      rendered natively by GitHub (pg1 · `de01ec1`).
      - [ ] (owner) also upload it to Devpost's *separate* "Architecture Diagram" field.
- [ ] (owner) **4. Demo video ≤ 5:00** — pitch covers **problem / who / why** (spec §11
      storyboard). Script + shot list are drafted → [`DEMO_SCRIPT.md`](DEMO_SCRIPT.md);
      recording/voice-over is the owner step.
- [ ] (owner) **5. AWS Builder ID** — registered, and **$200 credits** claimed.
- [ ] (owner) **6. Live demo link** *(bonus)* — deploy scaffold is ready
      ([`DEPLOYMENT.md`](DEPLOYMENT.md): Vercel board + Neon + Railway/AgentCore cron,
      pf1 · `9f05e30`; seed dataset pf2 · `723668b` keeps the inbox non-empty). The actual
      deploy + URL is the owner step.
- [ ] (owner) **7. builder.aws.com blog post** *(bonus)* — title **must contain "Agents for
      Humans"**. Draft is written → [`BLOG_DRAFT.md`](BLOG_DRAFT.md) (title: *"You Approve
      Decisions, Not Links — Building EverLink for the 'Agents for Humans' Hackathon"*);
      publishing is the owner step.

## 8. Secrets zero-leak audit (blocking) — ✅ PASS

- [x] Repo contains **only** `.env.example` — no real `.env`. Verified: `git ls-files`
      lists no `.env` / `*.pem` / `*.key` / `*credentials*` / `*secrets*`, and none ever
      appeared in history (`git log --all -- .env "*.pem" "*.key"` is empty). The committed
      `data/slots_*.csv` hold only public url / anchor / slot_type / protected fields — no
      secrets, tokens, or PII — so they do not weaken this audit.
- [x] `gitleaks detect` (**or equivalent**) returns **zero** findings. The `gitleaks`
      binary is not installable offline here, so an equivalent ripgrep secret scan was run
      over the whole tracked surface: AWS keys (`AKIA`/`ASIA`), PEM private-key headers,
      GitHub/Slack/OpenAI/Anthropic/Resend tokens, Telegram bot tokens, Google API keys,
      JWTs, credential-bearing connection strings, and high-entropy `secret=`/`token=`
      assignments — **zero real hits**. The only matches are documented placeholders
      (`user:pass@host-pooler`), synthetic test fixtures (`u:p@ep-xyz-pooler…`), and
      function-name false positives. Re-run `gitleaks detect` on a networked machine to
      double-confirm before submitting.
- [x] README / code contain **no** production connection strings or credentials
      (placeholders only). The real production Blue-Neon host appears **nowhere** in the
      repo. `.env.example` ships empty secret fields + generic `user:pass@host-pooler` DSNs.
- [x] Raw `data/*.jsonl` dumps stay **gitignored**. The first-party Scanner's read-only
      `data/slots_*.csv` (public url / anchor / slot_type / protected flags — no secrets/PII)
      ARE committed and baked into the private image so the nightly cron finds its slots
      out-of-the-box (commit `4857cd3`); the aggregate `data/slots_summary.json` is committed too.
- [ ] (owner) Demo video: any sensitive value (URLs, tokens, DB hosts) is masked/blurred —
      applies once the video is recorded.

## Scoring coverage self-check (5 criteria)

| Criterion | Where we score it | Status |
|---|---|---|
| Technological Implementation | Strands multi-agent (Orchestrator→Scanner→Judge→Writer), Hooks (audit + write gate), Evals (50-case), Bedrock Claude, OpenTelemetry tracing; AgentCore documented as stretch | [x] |
| Design | Decision Board UX (Next.js), Structured-Output `Proposal` cards, two-track Interrupt approval flow | [x] |
| Potential Impact | `verify_fix` re-probe + snapshot rollback closes the loop on real production links (23,476-slot Phase A dataset) | [x] |
| Creativity & Originality | 4 Steering policies (Disclosure / Editorial / Scope / Write) | [x] |
| Presentation | ≤5min video, storyboard, live demo, blog | [ ] (owner) — artifacts drafted; recording/publish pending |

## Phase gate (spec §9)

- [x] **A** (9/2): 3-site LinkSlot CSV export (`scripts/export_slots.py` → `data/slots_summary.json`, **23,476** slots) · Strands quickstart (`scripts/verify_strands.py`) · repo init. *(Builder ID + $200 credits = owner, pending.)*
- [x] **B** (9/3–9/4): DB DDL · 3 adapters · L1 `http_probe` + redirect-chain analysis.
- [x] **C** (9/5–9/6): L2 stealth parse · fixture server · Judge + `Proposal` · generic adapter · Evals v1 (30).
- [x] **D** (9/7–9/8): 4 Steering policies (`81d1e59`) · Interrupt decision cards (`06ac5a9`) · Board (`4afc6e3`) · push Resend/Telegram (`40f293e`).
- [x] **E** (9/9): Writer write-back (`3d47371`) · **verify_fix** + snapshot rollback (`4cf9de6`) · hooks audit · weekly report (`b9a6f5a`).
- [x] **F** (9/10): deploy scaffold (`9f05e30`) · **seed dataset** (`723668b`/`e6fa4e9`) · Evals full 50 + OTel tracing (`4e100db`). *(Live deploy + URL = owner, pending.)*
- [x] **G** (9/11): Architecture Diagram (`de01ec1`) · README (`6baf2dd`) · license/submission cross-check + secrets audit (this file).
- [ ] (owner) **H** (9/12): Demo video recording — script/shot list drafted ([`DEMO_SCRIPT.md`](DEMO_SCRIPT.md)).
- [ ] (owner) **I** (9/13): builder.aws.com blog ([`BLOG_DRAFT.md`](BLOG_DRAFT.md)) · Devpost submission ([`DEVPOST.md`](DEVPOST.md)) — both texts drafted; publish/submit is the owner step.
- [ ] **Buffer** (9/14): bug fixes / community release.

---

**Bottom line.** Every engineering deliverable through Phase **G** is implemented,
tested (**254** passing tests), committed, and pushed. The secrets zero-leak audit
**passes**. What remains is the human last mile: AWS Builder ID, flipping the repo
public, recording the demo video, deploying the live board, publishing the blog, and
clicking submit on Devpost — each with its draft/artifact already prepared.
