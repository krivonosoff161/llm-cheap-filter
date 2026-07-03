# Project map — for reviewers and maintainers

## What it does

`llm-cheap-filter` is a three-stage triage pipeline for text streams:
deterministic rules drop obvious noise for free, a *cheap* LLM scores the
survivors, and an explicit policy escalates only the few high-signal items to
an *expensive* LLM. The goal is one number: a low `chief_rate` without losing
the items that mattered.

## Mental model

```
items ─► PreFilter (pure rules, 0 tokens) ─► cheap_call (injected) ─►
        EscalationPolicy (pure rules)     ─► chief_call (injected, few items)
                                          └► Report (per-item + cost summary)
```

Two design commitments hold everything together:

1. **Determinism where possible** — the first and third stages are pure code,
   so the only non-determinism is the two callables *you* inject.
2. **Zero dependencies** — stdlib only (`asyncio`, `dataclasses`, `difflib`).

## Key modules

| File | Role | Size |
|---|---|---|
| `src/llm_cheap_filter/prefilter.py` | rule gate: noise substrings, keep-keywords, min length, fuzzy dedup | ~50 lines |
| `src/llm_cheap_filter/policy.py` | `drop / cheap / chief` decision from score + flag; validates its own thresholds | ~45 lines |
| `src/llm_cheap_filter/pipeline.py` | orchestration: sequential prefilter, concurrent LLM stages (semaphore-capped), tallying | ~115 lines |
| `src/llm_cheap_filter/analysis.py` | offline savings report and threshold calibration helpers | ~170 lines |
| `tests/test_pipeline.py` | offline tests incl. policy bounds, dedup normalization, callable errors, and concurrency cap | ~190 lines |
| `examples/` | offline demo (no keys) + llm-router wiring — see [examples/README.md](../examples/README.md) | small |
| `docs/calibration-replay.md` | how to replay labeled samples, read false accepts/escalates, and publish savings/risk artifacts | small |

## What exists today

- The full drop → cheap → chief pipeline with per-item results and a summary
  (`items_in / filtered_free / ended_cheap / escalated_chief / total_tokens /
  errors / total_cost / chief_rate`).
- Concurrency cap via `asyncio.Semaphore` (tested: peak in-flight never exceeds it).
- `EscalationPolicy` fails fast on inconsistent thresholds
  (`drop_if_score_below` must be `< escalate_if_score_at_least`, both in 0..1).
- Typed injection points: `CheapCall = (text) -> (judgment, usage)`,
  `ChiefCall = (text, judgment) -> (decision, usage)`.
- Offline analysis helpers:
  - `build_savings_report(report)` estimates actual spend vs an all-chief baseline;
  - `calibrate_thresholds(scores, should_escalate)` measures chief rate, false accepts,
    false escalates, precision, and recall for candidate thresholds.

## What is NOT included (by design)

- No LLM client, prompts, or parsing — you own both callables (pair with
  [llm-router](https://github.com/krivonosoff161/llm-router) or anything else).
- No persistence, queues, retries of the callables, or streaming input —
  `run()` takes an iterable and returns a report.
- Callable exceptions are isolated per item as `stage="error"` results; the
  pipeline does not retry provider/client failures.
- No domain scoring model: the "score" is whatever your cheap stage returns.

## How to inspect without reading every line

1. Run `python examples/offline_demo.py` — the printed table *is* the behavior.
2. Read `policy.py` (the decision is 8 lines).
3. Skim `pipeline.py::run()` — two passes, one semaphore, no hidden state.
4. Skim `analysis.py` — no LLM calls, only report arithmetic and threshold sweeps.
5. Read `docs/calibration-replay.md` before tightening thresholds on a real stream.

## How to run checks

```bash
python -m pytest -q               # offline tests, no network
python -m ruff check .
python examples/offline_demo.py   # deterministic, no keys
```

CI runs pytest and ruff on Python 3.9 / 3.11 / 3.12 across Ubuntu and Windows.

## How to extend safely

- New rule: add it inside `PreFilter.score()` with a distinct `reason` string
  and a test; keep it pure (no I/O).
- New policy input: extend `decide(score, flagged)` conservatively — every new
  branch needs a test in `test_policy_decisions` style.
- New calibration metric: keep it offline and derived from already-recorded labels /
  scores; it must not call models or decide truth by itself.
- Replacing `difflib` dedup for big streams: keep the
  `score(text, seen) -> PreVerdict` contract and swap the internals.
- Do **not** make the pipeline call providers directly — the injected-callable
  boundary is the whole point.

## Reviewer checklist (for future changes, incl. agent-generated)

- [ ] Still zero runtime dependencies (`pyproject.toml` `dependencies = []`).
- [ ] `PreVerdict` / `ItemResult` / `Report.summary` keys unchanged (public surface).
- [ ] Every dropped item carries a `reason` — no silent drops.
- [ ] Policy thresholds still validated in `__post_init__`.
- [ ] Concurrency test still proves the cap (peak ≤ limit).
- [ ] README demo output still matches `examples/offline_demo.py` actual output.
- [ ] Calibration docs still say lower chief-rate is not automatically better.
