# -*- coding: utf-8 -*-
"""Offline tests for llm-cheap-filter (no network, fake LLM callables)."""
import asyncio
import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from llm_cheap_filter import (  # noqa: E402
    CHIEF, DROP, EscalationPolicy, Pipeline, PreFilter,
)


# ── prefilter ────────────────────────────────────────────────────────────────
def test_prefilter_drops_noise_substring():
    pf = PreFilter(drop_substrings=("sponsored",))
    assert pf.score("Sponsored: buy now", []).keep is False


def test_prefilter_min_chars():
    pf = PreFilter(min_chars=10)
    assert pf.score("short", []).keep is False
    assert pf.score("this is long enough", []).keep is True


def test_prefilter_keep_keywords():
    pf = PreFilter(keep_keywords=("merger", "earnings"))
    assert pf.score("random chatter", []).keep is False
    assert pf.score("Q1 earnings beat", []).keep is True


def test_prefilter_dedup():
    pf = PreFilter(dedup_threshold=90)
    seen = ["Bitcoin surges to new high"]
    assert pf.score("Bitcoin surges to new high", seen).reason == "duplicate"
    assert pf.score("Completely different headline about oil", seen).keep is True


# ── policy ───────────────────────────────────────────────────────────────────
def test_policy_decisions():
    p = EscalationPolicy(escalate_if_score_at_least=0.65, drop_if_score_below=0.2)
    assert p.decide(0.9) == CHIEF
    assert p.decide(0.1) == DROP
    assert p.decide(0.4) == "cheap"
    assert p.decide(0.1, flagged=True) == CHIEF   # flag overrides low score


# ── pipeline (fake LLM) ──────────────────────────────────────────────────────
async def _fake_cheap(text):
    low = text.lower()
    score = 0.9 if "important" in low else 0.5 if "maybe" in low else 0.1
    return {"score": score, "flagged": "urgent" in low}, {"total_tokens": 10, "cost_usd": 0.001}


async def _fake_chief(text, judgment):
    return {"verdict": "ACT"}, {"total_tokens": 50, "cost_usd": 0.01}


def test_pipeline_routes_and_tallies():
    pf = PreFilter(drop_substrings=("sponsored",), min_chars=3, dedup_threshold=95)
    pol = EscalationPolicy(escalate_if_score_at_least=0.65, drop_if_score_below=0.2)
    pipe = Pipeline(pf, pol, _fake_cheap, _fake_chief)

    items = [
        "important breaking event",   # cheap 0.9 -> chief
        "urgent but vague",           # flagged -> chief
        "maybe something here",       # cheap 0.5 -> keep cheap
        "boring filler text",         # cheap 0.1 -> drop at cheap
        "Sponsored content ad",       # prefilter -> filtered (free)
        "important breaking event",   # duplicate -> filtered (free)
    ]
    report = asyncio.run(pipe.run(items))
    s = report.summary
    assert s["items_in"] == 6
    assert s["filtered_free"] == 2           # sponsored + duplicate, 0 tokens
    assert s["escalated_chief"] == 2         # the two important/urgent ones
    assert s["ended_cheap"] == 2             # maybe-kept + boring-dropped (judged by cheap only)
    assert s["total_tokens"] == 4 * 10 + 2 * 50   # 4 cheap calls + 2 chief calls
    assert 0.0 < s["chief_rate"] < 1.0


def test_pipeline_empty():
    pipe = Pipeline(PreFilter(), EscalationPolicy(), _fake_cheap, _fake_chief)
    report = asyncio.run(pipe.run([]))
    assert report.summary["items_in"] == 0 and report.summary["chief_rate"] == 0.0
