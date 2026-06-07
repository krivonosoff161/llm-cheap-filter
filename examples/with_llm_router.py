# -*- coding: utf-8 -*-
"""Wire the sibling `llm-router` as the cheap/chief callables (illustrative).

The pipeline has no LLM dependency — this just adapts one. Needs `llm-router`
installed and a provider configured; otherwise it prints a hint and exits.
"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))  # run from a clone, no install

from llm_cheap_filter import EscalationPolicy, Pipeline, PreFilter  # noqa: E402

try:
    from llm_router import call
except ImportError:
    call = None

CHEAP_SYS = ('You triage news items. Return ONLY JSON: {"score": 0.0-1.0, "flagged": true|false}. '
             "score = how material/actionable; flagged = a red flag worth a senior look.")
CHIEF_SYS = "You are the senior analyst. Decide. Return concise JSON with a verdict and a short why."


async def cheap_call(text):
    raw, usage = await call("cheap", CHEAP_SYS, text, json_mode=True)
    try:
        j = json.loads(raw or "{}")
    except Exception:
        j = {}
    return {"score": float(j.get("score", 0.0)), "flagged": bool(j.get("flagged", False))}, usage


async def chief_call(text, judgment):
    raw, usage = await call("chief", CHIEF_SYS,
                            f"Item: {text}\nCheap judgment: {judgment}", json_mode=True)
    try:
        verdict = json.loads(raw or "{}")
    except Exception:
        verdict = {"raw": raw}
    return verdict, usage


async def main():
    if call is None:
        print("Install the sibling `llm-router` (pip install llm-router) and configure a provider first.")
        return
    pipe = Pipeline(
        PreFilter(drop_substrings=("sponsored", "opinion"), min_chars=12, dedup_threshold=90),
        EscalationPolicy(),
        cheap_call, chief_call,
    )
    report = await pipe.run(["SEC approves spot ETF — inflows surge", "Sponsored: buy now"])
    print(report.summary)


if __name__ == "__main__":
    asyncio.run(main())
