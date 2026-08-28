# llm-cheap-filter

Ecosystem role and current integration status: [component roadmap](docs/component-roadmap.md).
The public cross-repository plan is owned by the
[Agentic Security Harness ecosystem roadmap](https://github.com/krivonosoff161/agentic-security-harness/blob/main/docs/ecosystem-roadmap.md).

[![Tests](https://github.com/krivonosoff161/llm-cheap-filter/actions/workflows/tests.yml/badge.svg)](https://github.com/krivonosoff161/llm-cheap-filter/actions/workflows/tests.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/)
![deps: none](https://img.shields.io/badge/runtime%20deps-0-brightgreen.svg)

**Don't send every item to your LLM.** Drop obvious noise for free with rules,
judge the rest with a *cheap* model, and escalate only the few that matter to an
*expensive* one. A small, **zero-dependency** triage pipeline for agentic systems.

> Generalized from a news-triage workflow. The pattern —
> *deterministic filter → cheap → chief* — is one of the biggest levers on agentic LLM
> cost, but only if you measure what it drops and escalates.

`llm-cheap-filter` is currently a standalone support adapter. Its source tree builds the
zero-runtime-dependency distribution candidate `llm-cheap-filter==0.2.0`. It is not yet
published or automatically activated by Harness.

---

## The idea

```
                 items in
                    │
        ┌───────────▼───────────┐
        │  PreFilter (0 tokens)  │  drop noise / dupes / too-short by rules
        └───────────┬───────────┘
              survivors │
        ┌───────────▼───────────┐
        │   cheap LLM judge      │  score + flags (high volume, low price)
        └───────────┬───────────┘
        EscalationPolicy (0 tokens)  drop · keep cheap · escalate
                    │ few
        ┌───────────▼───────────┐
        │   chief LLM decide     │  expensive, only for candidates
        └────────────────────────┘
```

The pipeline is **LLM-client-agnostic**: you inject two async callables, so it works with any provider (it pairs naturally with the sibling [`llm-router`](https://github.com/krivonosoff161/llm-router)) or a fake for offline tests.

---

## Demo (runs offline, no keys)

```bash
python examples/offline_demo.py
```

```text
  [chief   ] SEC approves spot ETF — inflows surge           score=0.90
  [filtered] Sponsored: trade with XYZ broker                score=0.00  noise_match
  [filtered] Weekly recap: what moved markets                score=0.00  noise_match
  [chief   ] Company files for bankruptcy, halts operations  score=0.90
  [filtered] Analyst opinion: why I think it goes up         score=0.00  noise_match
  [chief   ] Major data breach exposes 10M records           score=0.90
  [filtered] Top 5 coins to watch this week                  score=0.00  noise_match
  [filtered] SEC approves spot ETF — inflows surge           score=0.00  duplicate
  [cheap   ] Quiet trading day, nothing notable              score=0.40

summary: {'items_in': 9, 'filtered_free': 5, 'ended_cheap': 1, 'escalated_chief': 3,
          'errors': 0, 'cancelled': 0, 'total_tokens': 228, 'total_cost': 0.0188,
          'chief_rate': 0.333}
```

In this committed synthetic example, 5 of 9 items never touched an LLM and 3
reached the expensive model. This is example arithmetic, not evidence of a
production chief rate; real results depend on labels, thresholds, source quality,
and drift.

---

## Features

- **PreFilter** — pure rules (0 tokens): drop noise substrings, require keep-keywords, min length, near-duplicate dedup (stdlib `difflib`).
- **EscalationPolicy** — pure rules: `drop` / keep-`cheap` / escalate-`chief` from the cheap stage's score + flags.
- **Pipeline** — runs the stages, caps concurrency, and returns a per-item report + a cost/savings summary.
- **Savings report** — estimate actual tokens/cost against an all-chief counterfactual.
- **Threshold calibration** — sweep cheap-stage thresholds against labeled outcomes and
  measure false accepts / false escalates before tightening.
- **Bring your own LLM** — inject `cheap_call` / `chief_call`; nothing is hardcoded to a provider.
- **Zero runtime dependencies** — standard library only. Fully testable offline.

---

## Install

```bash
git clone https://github.com/krivonosoff161/llm-cheap-filter
cd llm-cheap-filter
python -m build
python -m pip install dist/llm_cheap_filter-0.2.0-py3-none-any.whl
```

For editable development use `python -m pip install -e .[dev]`. Requires **Python 3.9+**.
CI builds and installs the exact wheel on Ubuntu and Windows. Publication and inclusion in a
Harness optional-dependency group remain separate release gates. Installing the package never
calls a provider or activates caller-supplied model functions.

---

## Quickstart

```python
import asyncio
from llm_cheap_filter import PreFilter, EscalationPolicy, Pipeline

# your LLM, adapted to the expected shapes:
async def cheap_call(text):
    # -> (judgment with 'score' [+ optional 'flagged'], usage)
    return {"score": 0.8, "flagged": False}, {"total_tokens": 12, "cost_usd": 0.0002}

async def chief_call(text, judgment):
    # -> (decision, usage)
    return {"verdict": "ACT"}, {"total_tokens": 60, "cost_usd": 0.006}

pipe = Pipeline(
    PreFilter(drop_substrings=("sponsored", "opinion"), min_chars=12, dedup_threshold=90),
    EscalationPolicy(escalate_if_score_at_least=0.65, drop_if_score_below=0.2),
    cheap_call, chief_call,
)

report = asyncio.run(pipe.run(["SEC approves spot ETF", "Sponsored: buy now"]))
print(report.summary)
```

Pair it with [`llm-router`](https://github.com/krivonosoff161/llm-router) for the real calls — see [examples/with_llm_router.py](examples/with_llm_router.py).

### Measure savings

```python
from llm_cheap_filter import build_savings_report

savings = build_savings_report(report, chief_tokens_per_item=60, chief_cost_per_item=0.006)
print(savings.as_dict())
```

### Calibrate thresholds

```python
from llm_cheap_filter import calibrate_thresholds

points = calibrate_thresholds(
    scores=[0.95, 0.70, 0.45, 0.20],
    should_escalate=[True, False, True, False],
    thresholds=(0.4, 0.6, 0.8),
)
for point in points:
    print(point.as_dict())
```

Use calibration before tightening thresholds. A lower chief rate is not a win if false
accepts increase.

---

## How it works

**PreFilter** (`prefilter.py`) — per item, in order (so dedup sees prior survivors):
`drop_substrings` · `keep_keywords` · `min_chars` · `dedup_threshold` (1–100 fuzzy ratio). Returns `keep / score / reason`.

**EscalationPolicy** (`policy.py`) — given the cheap score + `flagged`:
`flagged` or `score ≥ escalate_if_score_at_least` → **chief**; `score < drop_if_score_below` → **drop**; otherwise keep the **cheap** result.

**Pipeline** (`pipeline.py`) — prefilter sequentially (free), then run survivors through the LLM stages concurrently (capped by `concurrency`). `report.summary` gives `items_in / filtered_free / ended_cheap / escalated_chief / errors / cancelled / total_tokens / total_cost / chief_rate`.

**Analysis helpers** (`analysis.py`) — offline helpers for already-recorded outputs:
`build_savings_report(report)` estimates actual spend against an all-chief counterfactual,
and `calibrate_thresholds(scores, should_escalate)` sweeps cheap-stage thresholds to show
chief rate, false accepts, false escalates, precision, and recall.

### Injected callables

```text
cheap_call(text)            -> (judgment: dict with 'score' [+ 'flagged'], usage: dict)
chief_call(text, judgment)  -> (decision: dict, usage: dict)
```
`usage` may carry `total_tokens` and `cost_usd` (or `cost`); both are tallied. Invalid usage values are reported as per-item `error` results instead of failing the whole batch.

---

## Tests

```bash
python -m pytest -q     # offline, fake LLM, no network
```

---

## Docs

- [Component roadmap](docs/component-roadmap.md) — source-owned ecosystem role,
  platform evidence, historical projections, and integration gates.
- [Project map](docs/project-map.md) — modules, what exists today vs not included, reviewer checklist.
- [Use cases](docs/use-cases.md) — triage, alert fatigue, support, scanning; what this is *not*.
- [Calibration and replay](docs/calibration-replay.md) — labeled samples, false accepts, false escalates, and report artifacts.
- [Triage Batch Receipt V1](docs/triage-batch-receipt.md) — canonical digest-only
  batch accounting, explicit loss stages, and authority boundaries.
- [Examples guide](examples/README.md) — what each example shows and does not prove.
- [Harness ecosystem roadmap](https://github.com/krivonosoff161/agentic-security-harness/blob/main/docs/ecosystem-roadmap.md)
  — the canonical public ordering for cross-repository integration work.

---

## Limitations / non-goals

- Text items in, structured judgments out — not a full agent framework.
- This is a library, not a CLI tool; the scripts in `examples/` are runnable demos.
- The cheap stage must return a `score`; you own the prompt/parsing (the example shows JSON-mode parsing).
- A miscalibrated cheap stage can filter out important items. Start with permissive thresholds, replay against labeled samples, and use the per-item reasons before tightening.
- Dedup uses `difflib` (good for headlines/short text); for very large streams swap in your own near-duplicate check.
- It controls *which* items reach the expensive model — it does not implement the models themselves.
- It is not the portfolio flagship, a correctness oracle, or a security control
  by itself. Larger systems own the final decision, validation, authorization,
  storage, and safety boundaries.

---

## License

MIT — see [LICENSE](LICENSE).
