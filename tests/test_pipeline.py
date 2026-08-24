# -*- coding: utf-8 -*-
"""Offline tests for llm-cheap-filter (no network, fake LLM callables)."""

import asyncio
import math

import pytest

from llm_cheap_filter import (
    CHIEF,
    DROP,
    CheapCall,
    ChiefCall,
    EscalationPolicy,
    Pipeline,
    PreFilter,
)


async def _fake_cheap(text):
    low = text.lower()
    score = 0.9 if "important" in low else 0.5 if "maybe" in low else 0.1
    return {"score": score, "flagged": "urgent" in low}, {"total_tokens": 10, "cost_usd": 0.001}


async def _fake_chief(text, judgment):
    return {"verdict": "ACT"}, {"total_tokens": 50, "cost_usd": 0.01}


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


def test_prefilter_noise_wins_over_keep_keyword():
    pf = PreFilter(drop_substrings=("sponsored",), keep_keywords=("earnings",))
    verdict = pf.score("Sponsored earnings webinar", [])

    assert verdict.keep is False
    assert verdict.reason == "noise_match"


def test_prefilter_dedup():
    pf = PreFilter(dedup_threshold=90)
    seen = ["bitcoin surges to new high"]
    assert pf.score("Bitcoin surges to new high", seen).reason == "duplicate"
    assert pf.score("Completely different headline about oil", seen).keep is True


def test_pipeline_dedup_normalizes_whitespace_variants():
    pipe = Pipeline(
        PreFilter(min_chars=1, dedup_threshold=100),
        EscalationPolicy(escalate_if_score_at_least=0.95, drop_if_score_below=0.2),
        _fake_cheap,
        _fake_chief,
    )

    report = asyncio.run(pipe.run(["  maybe duplicate headline  ", "maybe duplicate headline"]))

    assert report.results[1].stage == "filtered"
    assert report.results[1].reason == "duplicate"


def test_policy_decisions():
    p = EscalationPolicy(escalate_if_score_at_least=0.65, drop_if_score_below=0.2)
    assert p.decide(0.9) == CHIEF
    assert p.decide(0.1) == DROP
    assert p.decide(0.4) == "cheap"
    assert p.decide(0.1, flagged=True) == CHIEF


def test_policy_can_disable_flag_escalation():
    p = EscalationPolicy(
        escalate_if_score_at_least=0.65,
        drop_if_score_below=0.2,
        escalate_if_flagged=False,
    )

    assert p.decide(0.4, flagged=True) == "cheap"


def test_pipeline_routes_and_tallies():
    pf = PreFilter(drop_substrings=("sponsored",), min_chars=3, dedup_threshold=95)
    pol = EscalationPolicy(escalate_if_score_at_least=0.65, drop_if_score_below=0.2)
    pipe = Pipeline(pf, pol, _fake_cheap, _fake_chief)

    items = [
        "important breaking event",
        "urgent but vague",
        "maybe something here",
        "boring filler text",
        "Sponsored content ad",
        "important breaking event",
    ]
    report = asyncio.run(pipe.run(items))
    s = report.summary
    assert s["items_in"] == 6
    assert s["filtered_free"] == 2
    assert s["escalated_chief"] == 2
    assert s["ended_cheap"] == 2
    assert s["errors"] == 0
    assert s["total_tokens"] == 4 * 10 + 2 * 50
    assert 0.0 < s["chief_rate"] < 1.0


def test_pipeline_empty():
    pipe = Pipeline(PreFilter(), EscalationPolicy(), _fake_cheap, _fake_chief)
    report = asyncio.run(pipe.run([]))
    assert report.summary["items_in"] == 0 and report.summary["chief_rate"] == 0.0


def test_pipeline_accepts_generator_input():
    pipe = Pipeline(
        PreFilter(min_chars=1),
        EscalationPolicy(escalate_if_score_at_least=0.95, drop_if_score_below=0.2),
        _fake_cheap,
        _fake_chief,
    )

    report = asyncio.run(pipe.run(item for item in ["maybe one", "maybe two"]))

    assert report.summary["items_in"] == 2
    assert report.summary["ended_cheap"] == 2


def test_pipeline_isolates_callable_errors():
    async def flaky_cheap(text):
        if "bad" in text:
            raise RuntimeError("cheap exploded")
        return {"score": 0.5}, {"total_tokens": 2, "cost_usd": 0.001}

    pipe = Pipeline(
        PreFilter(min_chars=1),
        EscalationPolicy(escalate_if_score_at_least=0.95, drop_if_score_below=0.2),
        flaky_cheap,
        _fake_chief,
    )

    report = asyncio.run(pipe.run(["good item", "bad item", "another good item"]))

    assert report.summary["errors"] == 1
    assert report.summary["ended_cheap"] == 2
    assert report.summary["escalated_chief"] == 0
    assert [r.stage for r in report.results] == ["cheap", "error", "cheap"]
    assert report.results[1].reason == "pipeline.cheap_callable_error"
    assert "cheap exploded" not in (report.results[1].reason or "")


def test_pipeline_marks_invalid_usage_as_error():
    async def bad_usage(text):
        return {"score": 0.5}, {"total_tokens": 1, "cost_usd": None}

    pipe = Pipeline(
        PreFilter(min_chars=1),
        EscalationPolicy(escalate_if_score_at_least=0.95, drop_if_score_below=0.2),
        bad_usage,
        _fake_chief,
    )

    report = asyncio.run(pipe.run(["usage bug"]))

    assert report.summary["errors"] == 1
    assert report.results[0].stage == "error"
    assert report.results[0].reason == "pipeline.cheap_invalid_output"


def test_pipeline_accepts_cost_fallback_key():
    async def cheap_with_cost_key(text):
        return {"score": 0.5}, {"total_tokens": 3, "cost": 0.05}

    pipe = Pipeline(
        PreFilter(min_chars=1),
        EscalationPolicy(escalate_if_score_at_least=0.95, drop_if_score_below=0.2),
        cheap_with_cost_key,
        _fake_chief,
    )

    report = asyncio.run(pipe.run(["maybe cost fallback"]))

    assert report.summary["total_tokens"] == 3
    assert report.summary["total_cost"] == 0.05


def test_public_callable_aliases_are_exported():
    assert CheapCall is not None
    assert ChiefCall is not None


def test_policy_validates_threshold_bounds():
    with pytest.raises(ValueError):
        EscalationPolicy(escalate_if_score_at_least=0.5, drop_if_score_below=0.8)
    with pytest.raises(ValueError):
        EscalationPolicy(drop_if_score_below=-0.1)
    with pytest.raises(ValueError):
        EscalationPolicy(escalate_if_score_at_least=1.5)
    EscalationPolicy()


def test_pipeline_respects_concurrency_cap():
    in_flight = 0
    peak = 0

    async def slow_cheap(text):
        nonlocal in_flight, peak
        in_flight += 1
        peak = max(peak, in_flight)
        await asyncio.sleep(0.002)
        in_flight -= 1
        return {"score": 0.9}, {"total_tokens": 1}

    async def fast_chief(text, judgment):
        return {"verdict": "ACT"}, {"total_tokens": 1}

    pipe = Pipeline(
        PreFilter(min_chars=1, dedup_threshold=100),
        EscalationPolicy(),
        slow_cheap,
        fast_chief,
        concurrency=3,
    )
    items = [f"important distinct item number {i}" for i in range(20)]
    report = asyncio.run(pipe.run(items))

    assert report.summary["escalated_chief"] == 20
    assert peak <= 3
    assert peak >= 2


def test_pipeline_concurrency_one_is_sequential():
    in_flight = 0
    peak = 0

    async def slow_cheap(text):
        nonlocal in_flight, peak
        in_flight += 1
        peak = max(peak, in_flight)
        await asyncio.sleep(0.001)
        in_flight -= 1
        return {"score": 0.5}, {"total_tokens": 1}

    pipe = Pipeline(
        PreFilter(min_chars=1),
        EscalationPolicy(escalate_if_score_at_least=0.95, drop_if_score_below=0.2),
        slow_cheap,
        _fake_chief,
        concurrency=1,
    )

    report = asyncio.run(pipe.run([f"maybe item {i}" for i in range(8)]))

    assert report.summary["ended_cheap"] == 8
    assert peak == 1


def test_pipeline_non_positive_concurrency_is_clamped_to_one():
    pipe = Pipeline(
        PreFilter(min_chars=1),
        EscalationPolicy(escalate_if_score_at_least=0.95, drop_if_score_below=0.2),
        _fake_cheap,
        _fake_chief,
        concurrency=0,
    )

    report = asyncio.run(pipe.run(["maybe item"]))

    assert report.summary["ended_cheap"] == 1


def test_pipeline_instance_supports_parallel_run_calls():
    pipe = Pipeline(
        PreFilter(min_chars=1, dedup_threshold=100),
        EscalationPolicy(escalate_if_score_at_least=0.95, drop_if_score_below=0.2),
        _fake_cheap,
        _fake_chief,
        concurrency=2,
    )

    async def run_two_batches():
        return await asyncio.gather(
            pipe.run(["maybe batch a one", "maybe batch a two"]),
            pipe.run(["maybe batch b one", "maybe batch b two"]),
        )

    left, right = asyncio.run(run_two_batches())

    assert left.summary["items_in"] == 2
    assert right.summary["items_in"] == 2
    assert left.summary["ended_cheap"] == 2
    assert right.summary["ended_cheap"] == 2


@pytest.mark.parametrize(
    "judgment",
    [
        {"score": float("nan")},
        {"score": float("inf")},
        {"score": -0.0},
        {"score": -0.1},
        {"score": 1.1},
        {"score": True},
        {"score": 0.5, "flagged": "false"},
        {},
    ],
)
def test_pipeline_rejects_invalid_score_and_flag_shapes(judgment):
    async def invalid_cheap(text):
        return judgment, {"total_tokens": 1, "cost_usd": 0.0}

    pipe = Pipeline(PreFilter(min_chars=1), EscalationPolicy(), invalid_cheap, _fake_chief)
    report = asyncio.run(pipe.run(["bounded item"]))

    assert report.results[0].stage == "error"
    assert report.results[0].reason == "pipeline.cheap_invalid_output"


@pytest.mark.parametrize(
    "usage",
    [
        {"total_tokens": True, "cost_usd": 0.0},
        {"total_tokens": -1, "cost_usd": 0.0},
        {"total_tokens": 1.5, "cost_usd": 0.0},
        {"total_tokens": 1, "cost_usd": float("nan")},
        {"total_tokens": 1, "cost_usd": float("inf")},
        {"total_tokens": 1, "cost_usd": -0.0},
        {"total_tokens": 1, "cost_usd": -0.1},
    ],
)
def test_pipeline_rejects_non_finite_or_ambiguous_usage(usage):
    async def invalid_usage(text):
        return {"score": 0.4, "flagged": False}, usage

    pipe = Pipeline(PreFilter(min_chars=1), EscalationPolicy(), invalid_usage, _fake_chief)
    report = asyncio.run(pipe.run(["bounded item"]))

    assert report.results[0].stage == "error"
    assert report.results[0].reason == "pipeline.cheap_invalid_output"


def test_pipeline_distinguishes_sanitized_chief_failure_classes():
    async def chief_candidate(text):
        return {"score": 0.9, "flagged": False}, {"total_tokens": 1, "cost_usd": 0.0}

    async def invalid_chief(text, judgment):
        return "not a decision dict", {"total_tokens": 1, "cost_usd": 0.0}

    invalid_report = asyncio.run(
        Pipeline(PreFilter(min_chars=1), EscalationPolicy(), chief_candidate, invalid_chief).run(
            ["chief invalid"]
        )
    )
    assert invalid_report.results[0].reason == "pipeline.chief_invalid_output"

    async def failing_chief(text, judgment):
        raise RuntimeError("PRIVATE_CHIEF_EXCEPTION")

    failed_report = asyncio.run(
        Pipeline(PreFilter(min_chars=1), EscalationPolicy(), chief_candidate, failing_chief).run(
            ["chief failure"]
        )
    )
    assert failed_report.results[0].reason == "pipeline.chief_callable_error"
    assert "PRIVATE_CHIEF_EXCEPTION" not in failed_report.results[0].reason


def test_pipeline_classifies_malformed_tuple_arity_as_invalid_output():
    async def malformed_cheap(text):
        return ({"score": 0.4},)

    cheap_report = asyncio.run(
        Pipeline(PreFilter(min_chars=1), EscalationPolicy(), malformed_cheap, _fake_chief).run(
            ["cheap malformed"]
        )
    )
    assert cheap_report.results[0].reason == "pipeline.cheap_invalid_output"

    async def chief_candidate(text):
        return {"score": 0.9, "flagged": False}, {"total_tokens": 1, "cost_usd": 0.0}

    async def malformed_chief(text, judgment):
        return ({"verdict": "REVIEW"},)

    chief_report = asyncio.run(
        Pipeline(PreFilter(min_chars=1), EscalationPolicy(), chief_candidate, malformed_chief).run(
            ["chief malformed"]
        )
    )
    assert chief_report.results[0].reason == "pipeline.chief_invalid_output"


def test_callable_self_cancellation_is_per_item_on_all_supported_versions():
    async def cancelled_cheap(text):
        raise asyncio.CancelledError()

    cheap_report = asyncio.run(
        Pipeline(PreFilter(min_chars=1), EscalationPolicy(), cancelled_cheap, _fake_chief).run(
            ["cheap cancelled"]
        )
    )
    assert cheap_report.results[0].stage == "cancelled"
    assert cheap_report.results[0].reason == "pipeline.cheap_callable_cancelled"

    async def chief_candidate(text):
        return {"score": 0.9, "flagged": False}, {"total_tokens": 1, "cost_usd": 0.0}

    async def cancelled_chief(text, judgment):
        raise asyncio.CancelledError()

    chief_report = asyncio.run(
        Pipeline(PreFilter(min_chars=1), EscalationPolicy(), chief_candidate, cancelled_chief).run(
            ["chief cancelled"]
        )
    )
    assert chief_report.results[0].stage == "cancelled"
    assert chief_report.results[0].reason == "pipeline.chief_callable_cancelled"


def test_external_batch_cancellation_still_propagates():
    async def scenario():
        started = asyncio.Event()

        async def slow_cheap(text):
            started.set()
            await asyncio.Event().wait()

        pipe = Pipeline(PreFilter(min_chars=1), EscalationPolicy(), slow_cheap, _fake_chief)
        task = asyncio.create_task(pipe.run(["externally cancelled batch"]))
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())


def test_policy_and_prefilter_reject_non_finite_or_bool_controls():
    for value in (float("nan"), float("inf"), -0.0, -0.1, 1.1, True):
        with pytest.raises((TypeError, ValueError)):
            PreFilter(base_score=value)
    with pytest.raises(TypeError):
        EscalationPolicy(escalate_if_flagged=1)
    with pytest.raises(ValueError):
        EscalationPolicy(escalate_if_score_at_least=math.nan)
    with pytest.raises(ValueError):
        EscalationPolicy(drop_if_score_below=-0.0)
    with pytest.raises(TypeError):
        EscalationPolicy().decide(0.5, flagged="false")
