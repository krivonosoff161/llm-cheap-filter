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
import hashlib
import math
import re
from dataclasses import dataclass
from typing import Awaitable, Callable, Iterable, Optional, TypeVar

from .commitments import escalation_policy_sha256, prefilter_configuration_sha256
from .policy import CHIEF, DROP, EscalationPolicy
from .prefilter import PreFilter

# Injected LLM callables (any client or an offline fake):
#   cheap_call(text)            -> (judgment dict, usage dict)
#   chief_call(text, judgment)  -> (decision dict, usage dict)
CheapCall = Callable[[str], Awaitable["tuple[dict, dict]"]]
ChiefCall = Callable[[str, dict], Awaitable["tuple[dict, dict]"]]

MAX_USAGE_TOKENS = 9_007_199_254_740_991
MAX_USAGE_COST_USD = 1_000_000_000.0
_INPUT_DIGEST_DOMAIN = b"llm-cheap-filter/input/v1\0"
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_CallResult = TypeVar("_CallResult")


class PipelineOutputError(ValueError):
    """Raised when an injected callable returns an invalid bounded shape."""

    def __init__(self, reason_code: str = "pipeline.invalid_output") -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


class PipelineCallError(RuntimeError):
    """Sanitized stage-aware callable failure without exception payload retention."""

    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


class PipelineItemCancelled(RuntimeError):
    """One injected callable cancelled itself; the surrounding batch remains valid."""

    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


@dataclass
class ItemResult:
    item: str
    stage: str                  # "filtered" | "cheap" | "chief" | "error"
    score: float
    decision: dict | None = None
    reason: str | None = None
    tokens: int = 0
    cost: float = 0.0
    flagged: Optional[bool] = None

    def __post_init__(self) -> None:
        if not isinstance(self.item, str):
            raise TypeError("result item must be a string")
        if self.stage not in {"filtered", "cheap", "chief", "error", "cancelled"}:
            raise ValueError("result stage is unsupported")
        if isinstance(self.score, bool) or not isinstance(self.score, (int, float)):
            raise TypeError("result score must be numeric")
        self.score = float(self.score)
        if (
            not math.isfinite(self.score)
            or _is_negative_zero(self.score)
            or not 0.0 <= self.score <= 1.0
        ):
            raise ValueError("result score must be finite and in the 0..1 range")
        if self.decision is not None and not isinstance(self.decision, dict):
            raise TypeError("result decision must be a dict or null")
        if self.reason is not None and not isinstance(self.reason, str):
            raise TypeError("result reason must be a string or null")
        self.tokens, self.cost = _usage(
            {"total_tokens": self.tokens, "cost_usd": self.cost}
        )
        if self.flagged is not None and not isinstance(self.flagged, bool):
            raise TypeError("result flagged must be a bool or null")


@dataclass
class Report:
    results: list[ItemResult]
    input_sha256s: Optional[tuple[str, ...]] = None
    prefilter_configuration_sha256: Optional[str] = None
    escalation_policy_sha256: Optional[str] = None

    def __post_init__(self) -> None:
        if self.input_sha256s is not None:
            if len(self.input_sha256s) != len(self.results):
                raise ValueError("input commitments must match result count")
            if any(
                digest != _input_sha256(result.item)
                for digest, result in zip(self.input_sha256s, self.results)
            ):
                raise ValueError("input commitment does not bind its result item")
        commitments = (
            self.prefilter_configuration_sha256,
            self.escalation_policy_sha256,
        )
        if (commitments[0] is None) != (commitments[1] is None):
            raise ValueError("report configuration and policy commitments must be paired")
        if any(
            value is not None and not _SHA256_PATTERN.fullmatch(value)
            for value in commitments
        ):
            raise ValueError("report provenance commitments must be lowercase SHA-256")

    @property
    def summary(self) -> dict:
        n = len(self.results)
        by = {"filtered": 0, "cheap": 0, "chief": 0, "error": 0, "cancelled": 0}
        tokens = 0
        cost = 0.0
        for r in self.results:
            if r.stage not in by:
                raise ValueError("report contains an unsupported result stage")
            by[r.stage] += 1
            tokens += r.tokens
            cost += r.cost
        return {
            "items_in": n,
            "filtered_free": by["filtered"],   # dropped by rules, 0 tokens
            "ended_cheap": by["cheap"],        # judged by the cheap model only
            "escalated_chief": by["chief"],    # reached the expensive model
            "errors": by["error"],             # callable failures isolated to one item
            "cancelled": by["cancelled"],       # explicit per-item callable cancellation
            "total_tokens": tokens,
            "total_cost": round(cost, 6),
            "chief_rate": round(by["chief"] / n, 3) if n else 0.0,
        }


def _usage(u: Optional[dict]) -> tuple[int, float]:
    if not isinstance(u, dict):
        raise PipelineOutputError("usage must be a dict")
    tokens = u.get("total_tokens", 0)
    cost = u.get("cost_usd") if "cost_usd" in u else u.get("cost", 0)
    if isinstance(tokens, bool) or not isinstance(tokens, int):
        raise PipelineOutputError("total_tokens must be an integer")
    if not 0 <= tokens <= MAX_USAGE_TOKENS:
        raise PipelineOutputError("total_tokens is outside the supported range")
    if isinstance(cost, bool) or not isinstance(cost, (int, float)):
        raise PipelineOutputError("cost must be numeric")
    cost_value = float(cost)
    if (
        not math.isfinite(cost_value)
        or _is_negative_zero(cost_value)
        or not 0.0 <= cost_value <= MAX_USAGE_COST_USD
    ):
        raise PipelineOutputError("cost is outside the supported finite range")
    return tokens, cost_value


def _input_sha256(text: str) -> str:
    if not isinstance(text, str):
        raise TypeError("pipeline items must be strings")
    return hashlib.sha256(_INPUT_DIGEST_DOMAIN + text.encode("utf-8")).hexdigest()


def _judgment_values(judgment: object) -> tuple[dict, float, bool]:
    if not isinstance(judgment, dict):
        raise PipelineOutputError("cheap judgment must be a dict")
    if "score" not in judgment:
        raise PipelineOutputError("cheap judgment must include score")
    raw_score = judgment["score"]
    if isinstance(raw_score, bool) or not isinstance(raw_score, (int, float)):
        raise PipelineOutputError("cheap score must be numeric")
    score = float(raw_score)
    if not math.isfinite(score) or _is_negative_zero(score) or not 0.0 <= score <= 1.0:
        raise PipelineOutputError("cheap score must be finite and in the 0..1 range")
    flagged = judgment.get("flagged", False)
    if not isinstance(flagged, bool):
        raise PipelineOutputError("cheap flagged must be a bool")
    return judgment, score, flagged


def _decision_mapping(decision: object) -> dict:
    if not isinstance(decision, dict):
        raise PipelineOutputError("chief decision must be a dict")
    return decision


def _is_negative_zero(value: float) -> bool:
    return value == 0.0 and math.copysign(1.0, value) < 0.0


async def _invoke_isolated(awaitable: Awaitable[_CallResult]) -> tuple[bool, Optional[_CallResult]]:
    """Distinguish callable self-cancellation from cancellation of the batch task."""

    async def capture() -> tuple[bool, Optional[_CallResult]]:
        try:
            return False, await awaitable
        except asyncio.CancelledError:
            return True, None

    task = asyncio.create_task(capture())
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        raise


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
        try:
            async with sem:
                cancelled, cheap_result = await _invoke_isolated(self.cheap_call(text))
        except asyncio.CancelledError:
            raise
        except Exception:
            raise PipelineCallError("pipeline.cheap_callable_error") from None
        if cancelled:
            raise PipelineItemCancelled("pipeline.cheap_callable_cancelled")
        if not isinstance(cheap_result, tuple) or len(cheap_result) != 2:
            raise PipelineOutputError("pipeline.cheap_invalid_output")
        judgment, u1 = cheap_result
        try:
            judgment, score, flagged = _judgment_values(judgment)
            tok, cost = _usage(u1)
        except PipelineOutputError:
            raise PipelineOutputError("pipeline.cheap_invalid_output") from None
        decision = self.policy.decide(score, flagged)
        if decision == DROP:
            return ItemResult(text, "cheap", score, judgment, "below_threshold", tok, cost, flagged)
        if decision != CHIEF:
            return ItemResult(text, "cheap", score, judgment, None, tok, cost, flagged)
        try:
            async with sem:
                cancelled, chief_result = await _invoke_isolated(
                    self.chief_call(text, judgment)
                )
        except asyncio.CancelledError:
            raise
        except Exception:
            raise PipelineCallError("pipeline.chief_callable_error") from None
        if cancelled:
            raise PipelineItemCancelled("pipeline.chief_callable_cancelled")
        if not isinstance(chief_result, tuple) or len(chief_result) != 2:
            raise PipelineOutputError("pipeline.chief_invalid_output")
        verdict, u2 = chief_result
        try:
            verdict = _decision_mapping(verdict)
            tok2, cost2 = _usage(u2)
        except PipelineOutputError:
            raise PipelineOutputError("pipeline.chief_invalid_output") from None
        return ItemResult(text, "chief", score, verdict, None, tok + tok2, cost + cost2, flagged)

    async def run(self, items: Iterable[str]) -> Report:
        sem = asyncio.Semaphore(self._concurrency)   # create inside the running loop (3.9-safe)
        # Pass 1: prefilter sequentially (0 tokens) so dedup 'seen' grows in order.
        seen: list[str] = []
        plan: list[tuple[str, bool, float, str | None]] = []
        for text in items:
            pv = self.prefilter.score(text, seen)
            plan.append((text, pv.keep, pv.score, pv.reason))
            if pv.keep:
                seen.append(text.lower().strip())

        # Pass 2: LLM stages only for survivors, concurrently (capped by semaphore).
        async def handle(text, keep, base_score, reason):
            if not keep:
                return ItemResult(text, "filtered", 0.0, reason=reason)
            try:
                return await self._llm_stages(text, base_score, sem)
            except asyncio.CancelledError:
                raise
            except PipelineItemCancelled as exc:
                return ItemResult(text, "cancelled", base_score, reason=exc.reason_code)
            except PipelineOutputError as exc:
                return ItemResult(text, "error", base_score, reason=exc.reason_code)
            except PipelineCallError as exc:
                return ItemResult(text, "error", base_score, reason=exc.reason_code)

        results = await asyncio.gather(*(handle(*p) for p in plan))
        return Report(
            list(results),
            input_sha256s=tuple(_input_sha256(item[0]) for item in plan),
            prefilter_configuration_sha256=prefilter_configuration_sha256(self.prefilter),
            escalation_policy_sha256=escalation_policy_sha256(self.policy),
        )
