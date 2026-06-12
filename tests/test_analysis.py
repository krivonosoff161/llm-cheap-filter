# -*- coding: utf-8 -*-
"""Offline tests for savings and threshold calibration helpers."""

from llm_cheap_filter import (
    ItemResult,
    Report,
    build_savings_report,
    calibrate_thresholds,
)


def test_build_savings_report_uses_observed_chief_average() -> None:
    report = Report(
        [
            ItemResult("drop", "filtered", 0.0),
            ItemResult("cheap", "cheap", 0.4, tokens=10, cost=0.001),
            ItemResult("chief", "chief", 0.9, tokens=60, cost=0.02),
        ]
    )

    savings = build_savings_report(report)

    assert savings.items_in == 3
    assert savings.actual_tokens == 70
    assert savings.counterfactual_tokens == 180
    assert savings.saved_tokens == 110
    assert savings.actual_cost == 0.021
    assert savings.counterfactual_cost == 0.06
    assert savings.as_dict()["saved_cost"] == 0.039
    assert savings.baseline_source == "observed_chief_average"
    assert savings.as_dict()["savings_rate"] == 0.65


def test_build_savings_report_accepts_explicit_baseline_without_chief_calls() -> None:
    report = Report(
        [
            ItemResult("drop", "filtered", 0.0),
            ItemResult("cheap", "cheap", 0.4, tokens=10, cost=0.001),
        ]
    )

    savings = build_savings_report(report, chief_tokens_per_item=100, chief_cost_per_item=0.05)

    assert savings.counterfactual_tokens == 200
    assert savings.counterfactual_cost == 0.1
    assert savings.baseline_source == "provided"


def test_build_savings_report_requires_baseline_when_no_chief_calls() -> None:
    report = Report([ItemResult("cheap", "cheap", 0.4, tokens=10, cost=0.001)])

    try:
        build_savings_report(report)
    except ValueError as exc:
        assert "chief baseline required" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_savings_report_markdown_is_stable() -> None:
    report = Report([ItemResult("chief", "chief", 0.9, tokens=50, cost=0.01)])

    markdown = build_savings_report(report).as_markdown()

    assert markdown.startswith("# LLM triage savings report\n")
    assert "| Items in | 1 |" in markdown
    assert markdown.endswith("Counterfactual means: every input item goes directly to the chief model.\n")


def test_calibrate_thresholds_reports_false_accept_and_false_escalate_tradeoff() -> None:
    scores = [0.95, 0.7, 0.45, 0.2]
    labels = [True, False, True, False]

    low, high = calibrate_thresholds(scores, labels, thresholds=(0.4, 0.8))

    assert low.threshold == 0.4
    assert low.chief_calls == 3
    assert low.false_accepts == 0
    assert low.false_escalates == 1
    assert low.recall == 1.0

    assert high.threshold == 0.8
    assert high.chief_calls == 1
    assert high.false_accepts == 1
    assert high.false_escalates == 0
    assert high.precision == 1.0


def test_calibrate_thresholds_validates_shapes_and_thresholds() -> None:
    assert calibrate_thresholds([], []) == []

    for args in [([0.1], []), ([0.1], [True])]:
        try:
            if len(args[0]) != len(args[1]):
                calibrate_thresholds(args[0], args[1])
            else:
                calibrate_thresholds(args[0], args[1], thresholds=(-0.1,))
        except ValueError:
            pass
        else:
            raise AssertionError("expected ValueError")


def test_calibration_point_as_dict_rounds_rates() -> None:
    point = calibrate_thresholds([0.9, 0.1, 0.8], [True, False, False], thresholds=(0.5,))[0]

    assert point.as_dict() == {
        "threshold": 0.5,
        "items": 3,
        "chief_calls": 2,
        "chief_rate": 0.667,
        "false_accepts": 0,
        "false_escalates": 1,
        "precision": 0.5,
        "recall": 1.0,
    }
