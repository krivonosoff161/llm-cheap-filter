# -*- coding: utf-8 -*-
"""Fully offline demo — no API keys, fake LLM callables. `python examples/offline_demo.py`."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))  # run from a clone, no install

from llm_cheap_filter import EscalationPolicy, Pipeline, PreFilter  # noqa: E402

HEADLINES = [
    "SEC approves spot ETF — inflows surge",
    "Sponsored: trade with XYZ broker",
    "Weekly recap: what moved markets",
    "Company files for bankruptcy, halts operations",
    "Analyst opinion: why I think it goes up",
    "Major data breach exposes 10M records",
    "Top 5 coins to watch this week",
    "SEC approves spot ETF — inflows surge",            # near-duplicate
    "Quiet trading day, nothing notable",
]


async def fake_cheap(text):
    low = text.lower()
    flagged = any(w in low for w in ("breach", "bankruptcy", "halts"))
    score = 0.9 if any(w in low for w in ("approves", "files", "breach", "bankruptcy")) else 0.4
    return {"score": score, "flagged": flagged}, {"total_tokens": 12, "cost_usd": 0.0002}


async def fake_chief(text, judgment):
    return {"verdict": "ACT", "why": "material & time-sensitive"}, {"total_tokens": 60, "cost_usd": 0.006}


async def main():
    pipe = Pipeline(
        PreFilter(drop_substrings=("sponsored", "weekly recap", "top 5", "opinion"),
                  min_chars=12, dedup_threshold=92),
        EscalationPolicy(escalate_if_score_at_least=0.65, drop_if_score_below=0.3),
        fake_cheap, fake_chief,
    )
    report = await pipe.run(HEADLINES)
    for r in report.results:
        print(f"  [{r.stage:8}] {r.item[:46]:46}  score={r.score:.2f}  {r.reason or ''}")
    print("\nsummary:", report.summary)


if __name__ == "__main__":
    asyncio.run(main())
