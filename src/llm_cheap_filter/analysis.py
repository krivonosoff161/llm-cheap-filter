# -*- coding: utf-8 -*-
"""Offline analysis helpers for reports and threshold calibration.

These helpers do not call LLMs. They turn already-recorded pipeline outputs into
auditable numbers: savings vs an all-chief baseline, and threshold tradeoffs for
cheap-stage scores.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

from .pipeline import Report


@dataclass(frozen=True)
class SavingsReport:
    """Cost and token savings versus an all-chief counterfactual.

    The counterfactual assumes every input item would have gone directly to the
    expensive model. If no explicit per-item baseline is provided, observed chief
    averages from the report are used. That estimate is useful for calibration, not
    an accounting guarantee.
    """

    items_in: int
    actual_tokens: int
    actual_cost: float
    counterfactual_tokens: int
    counterfactual_cost: float
    saved_tokens: int
    saved_cost: float
    savings_rate: float
    baseline_source: str

    def as_dict(self) -> dict:
        return {
            "items_in": self.items_in,
            "actual_tokens": self.actual_tokens,
            "actual_cost": round(self.actual_cost, 6),
            "counterfactual_tokens": self.counterfactual_tokens,
            "counterfactual_cost": round(self.counterfactual_cost, 6),
            "saved_tokens": self.saved_tokens,
            "saved_cost": round(self.saved_cost, 6),
            "savings_rate": round(self.savings_rate, 3),
            "baseline_source": self.baseline_source,
        }

    def as_markdown(self) -> str:
        rows = [
            "# LLM triage savings report",
            "",
            "| Metric | Value |",
            "|---|---:|",
            f"| Items in | {self.items_in} |",
            f"| Actual tokens | {self.actual_tokens} |",
            f"| Counterfactual tokens | {self.counterfactual_tokens} |",
            f"| Saved tokens | {self.saved_tokens} |",
            f"| Actual cost | {self.actual_cost:.6f} |",
            f"| Counterfactual cost | {self.counterfactual_cost:.6f} |",
            f"| Saved cost | {self.saved_cost:.6f} |",
            f"| Savings rate | {self.savings_rate:.3f} |",
            f"| Baseline source | {self.baseline_source} |",
            "",
            "Counterfactual means: every input item goes directly to the chief model.",
        ]
        return "\n".join(rows) + "\n"


@dataclass(frozen=True)
class CalibrationPoint:
    """One cheap-score threshold candidate."""

    threshold: float
    items: int
    chief_calls: int
    chief_rate: float
    false_accepts: int
    false_escalates: int
    precision: float
    recall: float

    def as_dict(self) -> dict:
        return {
            "threshold": self.threshold,
            "items": self.items,
            "chief_calls": self.chief_calls,
            "chief_rate": round(self.chief_rate, 3),
            "false_accepts": self.false_accepts,
            "false_escalates": self.false_escalates,
            "precision": round(self.precision, 3),
            "recall": round(self.recall, 3),
        }


def build_savings_report(
    report: Report,
    *,
    chief_tokens_per_item: int | None = None,
    chief_cost_per_item: float | None = None,
) -> SavingsReport:
    """Estimate savings versus sending every item to the chief model.

    Pass explicit chief baseline values when you know them. If omitted, the function
    derives them from observed chief-stage results. If no chief calls happened and no
    explicit baseline is provided, the baseline is unknown and a ValueError is raised.
    """

    items_in = len(report.results)
    actual_tokens = sum(r.tokens for r in report.results)
    actual_cost = sum(r.cost for r in report.results)
    chief_results = [r for r in report.results if r.stage == "chief"]

    baseline_source = "provided"
    if chief_tokens_per_item is None or chief_cost_per_item is None:
        if not chief_results:
            raise ValueError("chief baseline required when report has no chief results")
        baseline_source = "observed_chief_average"
        if chief_tokens_per_item is None:
            chief_tokens_per_item = round(sum(r.tokens for r in chief_results) / len(chief_results))
        if chief_cost_per_item is None:
            chief_cost_per_item = sum(r.cost for r in chief_results) / len(chief_results)

    counterfactual_tokens = int(chief_tokens_per_item) * items_in
    counterfactual_cost = float(chief_cost_per_item) * items_in
    saved_tokens = max(0, counterfactual_tokens - actual_tokens)
    saved_cost = max(0.0, counterfactual_cost - actual_cost)
    savings_rate = saved_cost / counterfactual_cost if counterfactual_cost > 0 else 0.0

    return SavingsReport(
        items_in=items_in,
        actual_tokens=actual_tokens,
        actual_cost=actual_cost,
        counterfactual_tokens=counterfactual_tokens,
        counterfactual_cost=counterfactual_cost,
        saved_tokens=saved_tokens,
        saved_cost=saved_cost,
        savings_rate=savings_rate,
        baseline_source=baseline_source,
    )


def calibrate_thresholds(
    scores: Sequence[float],
    should_escalate: Sequence[bool],
    *,
    thresholds: Iterable[float] = (0.2, 0.4, 0.6, 0.8),
) -> list[CalibrationPoint]:
    """Sweep cheap-stage escalation thresholds against labeled outcomes.

    ``should_escalate=True`` means a human label or later audit says the item should
    have reached chief. ``false_accepts`` are the dangerous misses: relevant items that
    would not escalate at a threshold. ``false_escalates`` are cost/noise errors.
    """

    if len(scores) != len(should_escalate):
        raise ValueError("scores and should_escalate must have the same length")
    if not scores:
        return []

    clean_scores = [float(score) for score in scores]
    labels = [bool(label) for label in should_escalate]
    positives = sum(1 for label in labels if label)
    points: list[CalibrationPoint] = []

    for raw_threshold in thresholds:
        threshold = float(raw_threshold)
        if not 0.0 <= threshold <= 1.0:
            raise ValueError("thresholds must be in the 0..1 range")
        escalated = [score >= threshold for score in clean_scores]
        chief_calls = sum(1 for value in escalated if value)
        true_positive = sum(1 for pred, label in zip(escalated, labels) if pred and label)
        false_accepts = sum(1 for pred, label in zip(escalated, labels) if not pred and label)
        false_escalates = sum(1 for pred, label in zip(escalated, labels) if pred and not label)
        precision = true_positive / chief_calls if chief_calls else 0.0
        recall = true_positive / positives if positives else 0.0
        points.append(
            CalibrationPoint(
                threshold=threshold,
                items=len(clean_scores),
                chief_calls=chief_calls,
                chief_rate=chief_calls / len(clean_scores),
                false_accepts=false_accepts,
                false_escalates=false_escalates,
                precision=precision,
                recall=recall,
            )
        )
    return points
