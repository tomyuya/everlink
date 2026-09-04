# Contributing to EverLink

Thanks for spending time on this. EverLink is a hackathon-born project (AWS *Agents for
Humans*, Professional track) that is deliberately small, honest, and safe-by-construction.
This page is the short path from "cloned the repo" to "merged a change that keeps it that
way."

## Dev setup

```bash
# agent (Python 3.14 recommended)
python -m venv .venv && .venv\Scripts\activate     # Windows; source .venv/bin/activate elsewhere
pip install -r requirements.txt
copy .env.example .env                             # optional: only needed for live-DB paths

# board (Next.js)
cd board && npm install
copy .env.example .env.local                       # optional: pages render honest empty states without it
```

No AWS credentials and no database are needed for the entire offline gate below — the test
suite runs on the injected `StubModel` and an in-process fixture server.

## Gates (what CI runs)

`.github/workflows/ci.yml` runs these on every push and PR; run them locally before pushing:

```bash
python scripts/verify_strands.py        # offline Strands SDK surface gate
python -m pytest -q                     # full offline suite
python scripts/run_evals.py --full      # 50-case eval harness (spec §8)
cd board && npm run typecheck && npm run build
```

If a gate cannot run in your environment (e.g. no network for the board build), say so
explicitly in the PR description instead of letting it fail silently.

## House rules

1. **Honesty is a feature.** Never fake a delivery, metric, probe result, or LLM judgment.
   Channels report `skipped` when unconfigured; blocked/timeout probes become
   `needs_human_recheck`; offline (stub) eval numbers are labelled as what they prove and
   what they do not. Keep it that way.
2. **Do not weaken the safety curtain.** The write gate (`db._assert_writable` /
   `assertBoardWritable`), the disclosure immunity (`DisclosurePolicy`), the SSRF guard
   (`everlink/ssrf.py`), and the read-only source-DB transactions are load-bearing. Changes
   that relax them need an explicit, reviewed reason.
3. **Strands Agents SDK only.** The hackathon requires the agent logic to be built on the
   Strands SDK (`@tool`, steering hooks, interrupt, structured output). New agent
   capabilities should use Strands primitives, not a parallel framework.
4. **Secrets never enter the repo.** Only `.env.example` / `board/.env.example` ship. CI,
   docs, and tests use placeholders or monkeypatched fake DSNs.
5. **The board never fabricates.** It renders exactly what is in the decision queue; empty
   states are correct behaviour for an empty database.

## Commit & PR style

- Imperative subject with a scope: `feat(board): …`, `fix(agent): …`, `docs: …`.
- Body explains *why*, and ends with a `Verification:` line listing the gates you ran
  (e.g. `pytest green; next build clean; served /audit and checked the clamp`).
- One logical change per commit; PRs stay reviewable (< ~400 lines when possible).
- Docs are part of the change: if a route, env var, or command moves, update
  `README.md` / `board/README.md` / `DEPLOYMENT.md` in the same commit.

## Where things live

| Path | What |
|---|---|
| `everlink/` | the agent package: agents, steering policies, hooks, decision queue, writer, probes, SSRF guard, CLI |
| `scripts/` | operator entrypoints: `nightly.py` (the cron chain), `run_evals.py`, `seed_demo.py`, `verify_*.py` |
| `board/` | Next.js decision board (home / inbox / audit / report) |
| `tests/` | offline pytest suite (StubModel + fixtures) |
| `schema.sql` | EverLink's own store DDL (applied idempotently by `db.ensure_schema`) |
| `ARCHITECTURE.md` · `DEPLOYMENT.md` · `EVALS_REPORT.md` | diagrams · runbook · eval evidence |

## Issues & security

- Bug reports: include the command, the flags, and the exact output line that looks wrong.
- Security: do **not** file public issues with live DSNs, tokens, or production URLs.
  Describe the class of problem without secrets, or contact the maintainer privately.
