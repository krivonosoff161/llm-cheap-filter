# -*- coding: utf-8 -*-
"""Pipeline — prefilter (0 tokens) -> cheap LLM -> policy -> chief LLM only for candidates.

LLM-client-agnostic: you inject two async callables, so it pairs with any client
(e.g. the sibling `llm-router`) or a fake for offline tests.

    cheap_call(text)            -> (judgment: dict with 'score' [+ optional 'flagged'], usage: dict)
    chief_call(text, judgment)  -> (decision: dict, usage: dict)

`usage` may carry 'total_tokens' and 'cost_usd' (or 'cost'); they are tallied.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Awaitable, Callable, Iterable

from .policy import CHIEF, DROP, EscalationPolicy
from .prefilter import PreFilter

# Injected LLM callables (any client or an offline fake):
#   cheap_call(text)            -> (judgment dict, usage dict)
#   chief_call(text, judgment)  -> (decision dict, usage dict)
CheapCall = Callable[[str], Awaitable["tuple[dict, dict]"]]
ChiefCall = Callable[[str, dict], Awaitable["tuple[dict, dict]"]]


@dataclass
class ItemResult:
    item: str
    stage: str                  # "filtered" | "cheap" | "chief" | "error"
    score: float
    decision: dict | None = None
    reason: str | None = None
    tokens: int = 0
    cost: float = 0.0


@dataclass
class Report:
    results: list[ItemResult]

    @property
    def summary(self) -> dict:
        n = len(self.results)
        by = {"filtered": 0, "cheap": 0, "chief": 0, "error": 0}
        tokens = 0
        cost = 0.0
        for r in self.results:
            by[r.stage] = by.get(r.stage, 0) + 1
            tokens += r.tokens
            cost += r.cost
        return {
            "items_in": n,
            "filtered_free": by["filtered"],   # dropped by rules, 0 tokens
            "ended_cheap": by["cheap"],        # judged by the cheap model only
            "escalated_chief": by["chief"],    # reached the expensive model
            "errors": by["error"],             # callable failures isolated to one item
            "total_tokens": tokens,
            "total_cost": round(cost, 6),
            "chief_rate": round(by["chief"] / n, 3) if n else 0.0,
        }


def _usage(u: dict | None) -> tuple[int, float]:
    u = u or {}
    tokens = u.get("total_tokens", 0)
    cost = u.get("cost_usd") if "cost_usd" in u else u.get("cost", 0)
    return int(tokens), float(cost)


class Pipeline:
    """Triage a stream of text items, spending the expensive model only on candidates."""

    def __init__(self, prefilter: PreFilter, policy: EscalationPolicy,
                 cheap_call: CheapCall, chief_call: ChiefCall, *, concurrency: int = 8):
        self.prefilter = prefilter
        self.policy = policy
        self.cheap_call = cheap_call
        self.chief_call = chief_call
        self._concurrency = max(1, concurrency)

    async def _llm_stages(self, text: str, base_score: float, sem: asyncio.Semaphore) -> ItemResult:
        async with sem:
            judgment, u1 = await self.cheap_call(text)
        tok, cost = _usage(u1)
        score = float(judgment.get("score", base_score))
        flagged = bool(judgment.get("flagged", False))
        decision = self.policy.decide(score, flagged)
        if decision == DROP:
            return ItemResult(text, "cheap", score, judgment, "below_threshold", tok, cost)
        if decision != CHIEF:
            return ItemResult(text, "cheap", score, judgment, None, tok, cost)
        async with sem:
            verdict, u2 = await self.chief_call(text, judgment)
        tok2, cost2 = _usage(u2)
        return ItemResult(text, "chief", score, verdict, None, tok + tok2, cost + cost2)

    async def run(self, items: Iterable[str]) -> Report:
        sem = asyncio.Semaphore(self._concurrency)   # create inside the running loop (3.9-safe)
        # Pass 1: prefilter sequentially (0 tokens) so dedup 'seen' grows in order.
        seen: list[str] = []
        plan: list[tuple[str, bool, float, str | None]] = []
        for text in items:
            pv = self.prefilter.score(text, seen)
            plan.append((text, pv.keep, pv.score, pv.reason))
            if pv.keep:
                seen.append((text or "").lower().strip())

        # Pass 2: LLM stages only for survivors, concurrently (capped by semaphore).
        async def handle(text, keep, base_score, reason):
            if not keep:
                return ItemResult(text, "filtered", 0.0, reason=reason)
            try:
                return await self._llm_stages(text, base_score, sem)
            except Exception as exc:  # keep batch-level triage resilient to one bad callable result
                return ItemResult(text, "error", base_score, reason=f"{type(exc).__name__}: {exc}")

        results = await asyncio.gather(*(handle(*p) for p in plan))
        return Report(list(results))
