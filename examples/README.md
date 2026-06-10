# Examples

| Example | Needs keys? | Shows |
|---|---|---|
| `offline_demo.py` | **no** | the whole pipeline on 9 canned headlines with fake LLM callables |
| `with_llm_router.py` | yes (provider key) | wiring real `cheap_call` / `chief_call` via the sibling [llm-router](https://github.com/krivonosoff161/llm-router) |

## offline_demo.py

```bash
python examples/offline_demo.py
```

Expected output: a per-item table (`[filtered] / [cheap] / [chief]` + score +
drop reason) and a summary dict — 5 of 9 items never touch an LLM, 3 reach the
chief stage. The output is deterministic; the README quotes it verbatim.

**The lesson:** most of the savings come from the free rule stage, and the
report shows *why* every item went where it went — no silent drops.

**What it does NOT prove:** that the fake scores resemble your model's scores.
The demo demonstrates *routing mechanics*, not judgment quality.

## with_llm_router.py

```bash
pip install -e .                 # this repo
export OPENAI_API_KEY=sk-...     # or any provider llm-router supports
python examples/with_llm_router.py
```

Shows the adapter pattern: `llm_router.call("cheap", ...)` wrapped into
`cheap_call`, `call("chief", ...)` into `chief_call`, including JSON-mode
parsing of the cheap judgment. If `llm-router` is not installed, the script
explains and exits cleanly instead of crashing.

**What it does NOT prove:** anything about cost on *your* stream — chief rate
depends entirely on your thresholds and your data.
