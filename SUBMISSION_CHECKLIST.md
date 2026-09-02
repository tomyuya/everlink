# EverLink — Submission Checklist

Hackathon: **AWS "Agents for Humans"** (Devpost) · Track: **Professional Agents**
Deadline: **2026-09-15 08:00 GMT+8**

Every item below must be ✅ before submission. This file is the single source of
truth for "are we done" — mirror it on the wall from Day 1 (spec §10).

## Required deliverables

- [ ] **1. Devpost text description** — covers problem / who it's for / how it works.
- [ ] **2. Public repo + MIT LICENSE + README** — README includes setup instructions.
      - [ ] `LICENSE` present (MIT)
      - [ ] `README.md` present with setup + architecture
      - [ ] repo is public
- [ ] **3. Architecture Diagram** — *separate submission field*, not just a README image.
- [ ] **4. Demo video ≤ 5:00** — pitch explicitly covers **problem / who / why** (spec §11 storyboard).
- [ ] **5. AWS Builder ID** — registered (owner action, see Phase A reminder).
- [ ] **6. Live demo link** *(bonus)* — Vercel + Neon, seeded dataset so the inbox is never empty.
- [ ] **7. builder.aws.com blog post** *(bonus)* — title **must contain "Agents for Humans"**.

## 8. Secrets zero-leak audit (blocking)

- [ ] Repo contains **only** `.env.example` — no real `.env`.
- [ ] `gitleaks detect` (or equivalent) returns **zero** findings.
- [ ] README / code contain **no** production connection strings or credentials (placeholders only).
- [ ] Exported data snapshots (`data/*.csv`) are **gitignored** — they carry production content.
- [ ] Demo video: any sensitive value (URLs, tokens, DB hosts) is masked/blurred.

## Scoring coverage self-check (5 criteria)

| Criterion | Where we score it | Status |
|---|---|---|
| Technological Implementation | Strands multi-agent, Hooks, Evals, Bedrock, AgentCore (stretch) | [ ] |
| Design | Decision Board UX, Structured Output cards, Interrupt approval flow | [ ] |
| Potential Impact | `verify_fix` re-probe closes the loop on real production links | [ ] |
| Creativity & Originality | 4 Steering policies (Disclosure/Editorial/Scope/Write) | [ ] |
| Presentation | ≤5min video, storyboard, live demo, blog | [ ] |

## Phase gate (spec §9)

- [ ] **A** (9/2): 3-site LinkSlot CSV export · Builder ID + $200 credits · Strands quickstart · repo init
- [ ] **B** (9/3–9/4): DB DDL · 3 adapters · L1 http_probe + redirect-chain analysis
- [ ] **C** (9/5–9/6): L2 Scrapling · fixture server · Judge + Proposal · generic adapter · Evals v1 (30)
- [ ] **D** (9/7–9/8): 4 Steering policies · Interrupt decision cards · Board · push (Resend/Telegram)
- [ ] **E** (9/9): Writer write-back + **verify_fix** + snapshot rollback · hooks audit · weekly report
- [ ] **F** (9/10): live deploy · **seed dataset** · Evals full 50 · OTel tracing (stretch)
- [ ] **G** (9/11): Architecture Diagram · README · license/submission cross-check
- [ ] **H** (9/12): Demo video recording
- [ ] **I** (9/13): builder.aws.com blog · Devpost submission
- [ ] **Buffer** (9/14): bug fixes / community release
