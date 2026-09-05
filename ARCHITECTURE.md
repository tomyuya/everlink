# EverLink Architecture

EverLink is an autonomous **link-rot steward**: a nightly agent patrols every outbound
link slot of a content/affiliate site, *detects* rot with deterministic probes, *decides*
a fix with an LLM Judge bounded by steering policies, *surfaces* a decision card only when
a human is needed, and — once approved — *writes back + verifies* the fix in one
transaction. This document is the map; [`README.md`](README.md) is the pitch,
[`DEPLOYMENT.md`](DEPLOYMENT.md) is the runbook, [`EVALS_REPORT.md`](EVALS_REPORT.md) is
the evidence.

> Diagrams are Mermaid (rendered natively by GitHub). Every box below corresponds to a
> real module in [`everlink/`](everlink) — nothing is aspirational.

---

## 1. System context

```mermaid
flowchart LR
    subgraph SRC["Read-only source sites (production)"]
        AG["AethelGem<br/>(Django blocks)"]
        HD["hotdeals<br/>(products jsonb)"]
        SC["sandcart<br/>(section links)"]
    end

    subgraph EL["EverLink agent backend"]
        CORE["scan -> detect -> judge -> card<br/>-> interrupt -> write -> verify -> report"]
    end

    subgraph EXT["External services"]
        BR["Amazon Bedrock<br/>(Claude via Strands)"]
        RS["Resend<br/>(email)"]
        TG["Telegram Bot API"]
        OT["OTLP collector<br/>(optional tracing)"]
    end

    DB[("EverLink Neon DB<br/>link_slots / slot_checks /<br/>decisions / write_snapshots /<br/>audit_log")]
    BOARD["Decision Board<br/>(Next.js on Vercel)"]
    OP{{"Operator / human"}}

    AG & HD & SC -- "SELECT only" --> CORE
    DB -- "read" --> CORE
    CORE -- "gated write" --> DB
    CORE -- "Judge calls" --> BR
    CORE -- "morning brief + cards" --> RS & TG
    CORE -. "spans via --trace otlp" .-> OT
    DB -- "read pending / approved" --> BOARD
    BOARD -- "approve / reject" --> DB
    OP -- "reviews" --> BOARD
    RS & TG -- "notification" --> OP
    CORE -- "write-back: AethelGem only" --> AG
```

The three source databases are opened **read-only** (`SET default_transaction_read_only =
on`); the only write path is the gated Writer against AethelGem block content, and the
production Blue-Neon instance is on a hard deny-list (see §6).

The three source sites (`aethelgem` / `hotdeals` / `sandcart`) are the maintainer's
dogfooding EXAMPLE keys — `sandcart` is the internal codename for the FlashDeals
storefront. A deployer substitutes their own site keys, databases and origins; no site
identity or domain is hardcoded in the agent.

---

## 2. The nightly pipeline (end to end)

```mermaid
flowchart TD
    CRON["cron / AgentCore schedule<br/>scripts/nightly.py"] --> SCAN

    subgraph SCAN["1 - SCAN + DETECT (deterministic, no LLM)"]
        EX["extract_slots(adapter)"] --> L1["L1 http_probe<br/>status + redirect chain"]
        L1 --> ESC{"L1 conclusive?<br/>dead / program_ended"}
        ESC -- "no: healthy or blocked" --> L2["L2 page_parse<br/>offer live? price? stock?"]
        ESC -- "yes" --> FOLD
        L2 --> FOLD["detect.combine_verdict<br/>=> final_verdict"]
    end

    FOLD --> PROB{"final_verdict<br/>is healthy?"}
    PROB -- "yes" --> DONE["left alone (no card)"]
    PROB -- "no" --> JUDGE

    subgraph JUDGE["2 - JUDGE (Strands agent + steering hooks)"]
        JA["Judge agent<br/>tool: find_alternatives"] --> PROP["Proposal (Pydantic)<br/>action / new_url / rationale / risk"]
        PROP --> HOOKS["steering hooks gate the call:<br/>Disclosure / Editorial / Scope / Write"]
    end

    HOOKS --> CARD["build_decision_cards<br/>(merge same link across articles)"]
    CARD --> PUSH["notify: Resend email + Telegram<br/>morning brief, risk-routed cards"]
    CARD --> QUEUE[("durable decision queue<br/>decisions table")]

    QUEUE --> TRK{{"Interrupt: two tracks"}}
    TRK -- "Track 1: live demo" --> SYNC["sync approval gate<br/>hitl.run_judge_sync"]
    TRK -- "Track 2: production" --> BOARD["Decision Board (Vercel)<br/>human approve / reject"]

    SYNC --> APPROVED{"approved?"}
    BOARD --> APPROVED
    APPROVED -- "reject: reason remembered" --> REJECTED["terminal + audit"]
    APPROVED -- "approve" --> WORKER["DecisionWorker.poll_once"]

    WORKER --> WRITE["3 - WRITE (one transaction)<br/>snapshot then apply_fix"]
    WRITE --> VERIFY["verify_fix (re-probe L1+L2)"]
    VERIFY --> OK{"alive again?"}
    OK -- "yes" --> HEALED["healed + audit_log"]
    OK -- "no" --> ROLL["rollback + dead-letter<br/>+ rollback-recommendation card"]

    HEALED --> REPORT["weekly report<br/>(report.py mirrors board stats)"]
    ROLL --> REPORT
```

---

## 3. Agent topology (Agent-as-Tool, not a Swarm)

The task is a **sequential dependency chain**, so EverLink composes agents as tools rather
than a peer Swarm. All agents are `strands.Agent`s over a `BedrockModel`
(`StubModel` offline), built in [`everlink/agents.py`](everlink/agents.py).

```mermaid
flowchart TD
    ORCH["Orchestrator (cli / nightly)"] --> S
    ORCH --> J
    ORCH --> W

    subgraph S["Scanner agent"]
        ST["tools: extract_slots, http_probe (L1), page_parse (L2)"]
        ST --> SO["out: LinkSlot[] + CheckResult[]"]
    end

    subgraph J["Judge agent"]
        JT["tool: find_alternatives"]
        JT --> JO["out: Proposal (Structured Output / Pydantic)"]
        JH["hooks: Disclosure / Editorial / Scope"] -. "gate every tool call" .-> JT
    end

    subgraph W["Writer agent"]
        WT["tools: snapshot_block, apply_fix, verify_fix, rollback"]
        WT --> WO["out: healed or rolled-back"]
        WH["hook: WritePolicy (needs approved decision_id)"] -. "gate" .-> WT
        WM["SlidingWindowConversationManager(20)"] -. "long nightly runs" .-> WT
    end

    SO --> JT
    JO --> WT
```

| Strands feature | Where it is used |
|---|---|
| `@tool` | `extract_slots` / `http_probe` / `page_parse` / `find_alternatives`; Writer's `snapshot_block` / `apply_fix` / `verify_fix` / `rollback` |
| Multi-agent (Agent-as-Tool) | Orchestrator → Scanner → Judge → Writer |
| Steering | `DisclosurePolicy` / `EditorialPolicy` / `ScopePolicy` ([`steering.py`](everlink/steering.py)) |
| Hooks (Before/AfterToolCall) | write gate + `audit_log` ([`steering.py`](everlink/steering.py)) |
| Interrupt | sync gate + durable queue ([`hitl.py`](everlink/hitl.py)) |
| Structured Output (Pydantic) | `Proposal` ([`model.py`](everlink/model.py)) |
| ConversationManager (SlidingWindow) | Writer, long nightly runs |
| Strands Evals | 50-case suite ([`evals.py`](everlink/evals.py), [`EVALS_REPORT.md`](EVALS_REPORT.md)) |
| `BedrockModel` | Claude via Amazon Bedrock ([`llm.py`](everlink/llm.py)) |
| OpenTelemetry | optional tracing ([`tracing.py`](everlink/tracing.py)) |

---

## 4. Detection pyramid (the deterministic heart)

Detection is **pure code — no LLM** ([`detect.py`](everlink/detect.py)), so it is fully
testable offline and is the metric the Evals harness scores for real. L2 is spent only
where L1 is inconclusive (`_L2_ESCALATE = healthy | needs_human_recheck`).

```mermaid
flowchart TD
    IN["LinkSlot.url"] --> L1["L1 probe_url<br/>HTTP status + redirect chain"]
    L1 --> C1{"L1 verdict"}
    C1 -- "404 / gone" --> DEAD["dead"]
    C1 -- "affiliate hop drops the tag" --> PROG["program_ended"]
    C1 -- "200 OK" --> RUN2["run L2 (catch the soft-404)"]
    C1 -- "403 / timeout / bot-wall" --> RUN2

    RUN2 --> L2["L2 probe_l2<br/>parse: offer live? price? stock?"]
    L2 --> C2{"L2 verdict"}
    C2 -- "dead" --> DEAD
    C2 -- "unavailable / price_anomaly" --> OFFER["offer_changed<br/>(page lives, offer died)"]
    C2 -- "blocked" --> RECHK["needs_human_recheck"]
    C2 -- "ok" --> HEALTHY["healthy"]

    DEAD & PROG --> SKIP["L1 conclusive -> skip L2 (save a request)"]
```

`combine_verdict(l1, l2)` is the single folding rule shared by the Scanner tool, the
`everlink scan` CLI, and the Evals oracle — so a demo replay can never drift from
production detection.

---

## 5. Write-back safety (one transaction, snapshot-first, verified)

```mermaid
sequenceDiagram
    participant W as DecisionWorker
    participant G as db._assert_writable guard
    participant DB as EverLink Neon DB
    participant P as probes L1+L2

    W->>G: open write path (DSN)
    G-->>W: ok (not on deny-list) or ProductionWriteRefused
    W->>DB: BEGIN
    W->>DB: write_snapshot(before) - the undo image
    W->>DB: update_slot_content(after)
    W->>DB: COMMIT (single transaction)
    W->>P: verify_fix re-probes the new URL
    alt link alive again
        P-->>W: healthy
        W->>DB: audit_log(healed)
    else still broken or unverifiable
        P-->>W: not healed
        W->>DB: rollback(from snapshot) + dead-letter the decision
        W->>DB: enqueue rollback-recommendation card (ESCALATE_HUMAN)
    end
```

Guardrails ([`db.py`](everlink/db.py)): every write/DDL first calls `_assert_writable`,
which refuses any DSN whose host matches a source-site connection var or the
`EVERLINK_FORBIDDEN_HOSTS` deny-list. The production Blue-Neon instance can never be
written, even by accident.

---

## 6. Data & deployment

```mermaid
flowchart LR
    subgraph VERCEL["Vercel (iad1)"]
        B["board/ - Next.js approval inbox<br/>public read-only view + approve/reject"]
    end
    subgraph RAILWAY["Railway / Bedrock AgentCore (Docker)"]
        N["scripts/nightly.py cron<br/>scan -> notify -> worker -> report"]
    end
    subgraph NEON["Neon Postgres"]
        E[("EverLink DB<br/>link_slots, slot_checks,<br/>decisions, write_snapshots, audit_log")]
        S1[("AethelGem (read-only)")]
        S2[("hotdeals (read-only)")]
        S3[("sandcart (read-only)")]
    end
    E -- "read" --> N
    N -- "gated write" --> E
    N -- "SELECT only" --> S1 & S2 & S3
    E -- "read" --> B
    B -- "approve / reject" --> E
    N -. "Bedrock / Resend / Telegram" .-> X["AWS + push providers"]
```

---

## 7. Module map

| Layer | Modules | Responsibility |
|---|---|---|
| Ingest | `adapters.py`, `generic.py`, `model.py` | site → `LinkSlot` (read-only); generic crawl/sitemap adapter; shared schemas |
| Detection | `probes.py`, `l2.py`, `detect.py` | L1 HTTP + redirect chain; L2 page parse; `combine_verdict` oracle |
| Agents | `agents.py`, `llm.py` | Scanner / Judge / Writer (`@tool`s); `BedrockModel` + `StubModel` |
| Steering | `policy.py`, `steering.py` | disclosure / editorial / scope / write policies as hooks + a pure oracle |
| Surfacing | `cards.py`, `queue.py`, `hitl.py`, `notify.py`, `board/` | decision-card merge; durable queue; two-track interrupt; Resend + Telegram; approval inbox |
| Write-back | `writer.py`, `db.py` | snapshot → apply → verify → rollback in one transaction; guarded write primitives + `audit_log` |
| Reporting | `report.py` | weekly report (mirrors the board's `weeklyStats`) |
| Evals / demo | `evals.py`, `fixtures.py`, `tracing.py`, `seed.py` | 50-case harness; fixture server; optional OTel; deterministic demo replay |
| Entrypoints | `cli.py`, `scripts/nightly.py`, `scripts/run_evals.py`, `scripts/seed_demo.py`, `scripts/export_slots.py` | `everlink scan/notify/worker/report`; cron; evals; seed; read-only export |
