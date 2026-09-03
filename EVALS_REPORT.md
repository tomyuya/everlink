# EverLink Evals Report (spec §8)

This is the persisted output of EverLink's evaluation harness — the evidence that the
agent **detects link rot accurately** and **obeys its steering rules**. It is generated
by [`scripts/run_evals.py`](scripts/run_evals.py) against an in-process fixture server
([`everlink/fixtures.py`](everlink/fixtures.py)) whose pages have known ground truth, so
the whole run is deterministic and needs **no AWS credentials**.

## Reproduce

```bash
python scripts/run_evals.py            # 30-case v1 subset  (Phase C baseline)
python scripts/run_evals.py --full     # FULL 50-case set   (Phase F, spec §8 line 252)
python scripts/run_evals.py --full --trace console   # + OpenTelemetry spans to stdout
python scripts/run_evals.py --judge bedrock --full   # score the REAL Judge (needs creds)
```

The same harness is also asserted in CI by [`tests/test_evals.py`](tests/test_evals.py)
(`test_evals_v1_passes_on_stub`, `test_evals_full_50_passes_on_stub`).

## Results (judge backend = `stub`, offline)

### FULL 50-case Phase F set

```text
EverLink Evals (full 50-case Phase F set, spec section 8)
  judge backend        : stub
  cases                : 50

  [1] detection accuracy
      50/50 = 100.0%   (threshold >= 90%)   PASS
  [2] steering violations
      0   (threshold == 0)   PASS
  [3] hard metrics (threshold == 100%)
      disclosure zero-deletion : 100%   PASS
      reference zero-REPLACE   : 100%   PASS
      duplicate merged to 1 card: yes   PASS
      decision cards built     : 41

  OVERALL: PASS
```

### 30-case v1 subset (Phase C baseline, for comparison)

```text
EverLink Evals (30-case v1 subset, spec section 8)
  judge backend        : stub
  cases                : 30

  [1] detection accuracy
      30/30 = 100.0%   (threshold >= 90%)   PASS
  [2] steering violations
      0   (threshold == 0)   PASS
  [3] hard metrics (threshold == 100%)
      disclosure zero-deletion : 100%   PASS
      reference zero-REPLACE   : 100%   PASS
      duplicate merged to 1 card: yes   PASS
      decision cards built     : 25

  OVERALL: PASS
```

`decision cards built` = problem slots judged, minus duplicate merges: the 50-set has 42
non-healthy slots and one duplicate pair that merges into a single card → **41**; the
30-set has 26 → **25**. Healthy links are never judged and never produce a card.

## Case distribution (spec §8)

| category | route | expected verdict | v1 | full |
|---|---|---|---:|---:|
| dead (HTTP 404) | `/dead-N` | `dead` | 6 | 10 |
| price_anomaly | `/price-anomaly-N` | `offer_changed` | 5 | 8 |
| unavailable (soft-404) | `/unavailable-N` | `offer_changed` | 4 | 6 |
| program_ended (affiliate 302) | `/affiliate/deal-N?tag=…` | `program_ended` | 4 | 6 |
| healthy | `/ok-N` | `healthy` | 4 | 8 |
| disclosure *(hard metric)* | `/dead-disclosure-N` | `dead` | 2 | 4 |
| reference *(hard metric)* | `/dead-ref-N` | `dead` | 2 | 4 |
| duplicate *(merge pair)* | `/dead-shared` | `dead` | 2 | 2 |
| multiregion | `/dead-mr-N` | `dead` | 1 | 2 |
| **total** | | | **30** | **50** |

`build_cases(full=False|True)` is the single source of these counts; the two sets differ
**only** in per-category counts, so a v1 pass and a full pass are directly comparable.

## The three evaluators

1. **detection_accuracy** — the L1+L2 verdict ([`everlink/detect.py`](everlink/detect.py))
   vs ground truth. Threshold **≥ 90%**. This is **fully real offline**: detection is
   deterministic code (HTTP probe + redirect-chain analysis + page parse), no LLM involved.
2. **steering_violations** — every Judge proposal scored against the policy oracle
   ([`everlink/policy.py`](everlink/policy.py)). Threshold **== 0**.
3. **hard metrics** — disclosure zero-deletion, reference zero-`REPLACE_URL`, and
   cross-article duplicate merged into exactly ONE card. Threshold **== 100%**.

The oracle is proven **non-vacuous** by `test_oracle_catches_a_violating_judge`, which
injects a Judge that blindly `REPLACE_URL`s everything and asserts the evaluators FLAG it
(steering > 0, both hard metrics < 100%, `passed == False`). They do not merely pass
because the stub always escalates.

## Honesty: what `stub` does and does not prove

> **`judge_backend=stub`**: detection accuracy is **REAL**; the steering / hard-metric
> evaluators validate the policy **ORACLE** + orchestration plumbing, **NOT real LLM
> judgment** (a stub always returns `ESCALATE_HUMAN`). Score the real Judge with
> `--judge bedrock` (Phase F, spec §8) — the SAME harness and thresholds apply.

A stub run is always labelled with its backend in the report so it can never be mistaken
for a Bedrock run. This report is a **stub** run: the 100% detection figure is real and
meaningful; the 0-violation / 100%-hard-metric figures confirm the guardrails and card
merge work, and must be re-earned against the live Judge on Bedrock.

## OpenTelemetry tracing (spec §9 Phase F, optional)

[`everlink/tracing.py`](everlink/tracing.py) wraps the pipeline in **strictly optional**
spans: with the SDK absent or tracing uninitialized, `span()` is a zero-cost no-op and no
pipeline code depends on it (see [`tests/test_tracing.py`](tests/test_tracing.py)).

`--trace console` was verified live to emit a proper span **tree** under one `trace_id`:

```text
everlink.evals.run                     (parent; cases=50, judge_backend, full)
├── everlink.evals.detect              (slots=50)
├── everlink.evals.judge               (problem_slots=50)
│   └── chat / gen_ai.* / execute_tool Proposal / execute_event_loop_cycle
│       (Strands Agents SDK auto-instrumentation, same trace_id — the Judge's own spans
│        nest under ours because the parent context propagates into the agent call)
└── everlink.evals.score               (cards=41)
```

`--trace otlp` exports the same tree to any OTLP collector (`--otlp-endpoint`, or
`OTEL_EXPORTER_OTLP_ENDPOINT`) for a judge to inspect in their backend of choice.
