# -*- coding: utf-8 -*-
"""Escalation policy — pure rules deciding drop / keep-cheap / escalate-to-chief."""
from __future__ import annotations

import math
from dataclasses import dataclass

DROP = "drop"
CHEAP = "cheap"
CHIEF = "chief"


@dataclass
class EscalationPolicy:
    """Given the cheap stage's score (+ optional flag), decide what happens next.

    - flagged (e.g. a red-flag the cheap model raised) -> escalate to chief
    - score >= escalate_if_score_at_least              -> escalate to chief
    - score <  drop_if_score_below                     -> drop
    - otherwise                                        -> keep the cheap result
    """
    escalate_if_score_at_least: float = 0.65
    escalate_if_flagged: bool = True
    drop_if_score_below: float = 0.2

    def __post_init__(self) -> None:
        # scores are 0..1 by convention; a drop threshold at/above the escalate
        # threshold would silently shadow one of the branches — fail fast instead
        if not isinstance(self.escalate_if_flagged, bool):
            raise TypeError("escalate_if_flagged must be a bool")
        for value, label in (
            (self.drop_if_score_below, "drop_if_score_below"),
            (self.escalate_if_score_at_least, "escalate_if_score_at_least"),
        ):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError(f"{label} must be numeric")
            if not math.isfinite(float(value)):
                raise ValueError(f"{label} must be finite")
        self.drop_if_score_below = float(self.drop_if_score_below)
        self.escalate_if_score_at_least = float(self.escalate_if_score_at_least)
        if not (0.0 <= self.drop_if_score_below < self.escalate_if_score_at_least <= 1.0):
            raise ValueError(
                "EscalationPolicy requires 0.0 <= drop_if_score_below < "
                "escalate_if_score_at_least <= 1.0 "
                f"(got drop={self.drop_if_score_below}, escalate={self.escalate_if_score_at_least})"
            )

    def decide(self, score: float, flagged: bool = False) -> str:
        if isinstance(score, bool) or not isinstance(score, (int, float)):
            raise TypeError("score must be numeric")
        score = float(score)
        if not math.isfinite(score) or not 0.0 <= score <= 1.0:
            raise ValueError("score must be finite and in the 0..1 range")
        if not isinstance(flagged, bool):
            raise TypeError("flagged must be a bool")
        if self.escalate_if_flagged and flagged:
            return CHIEF
        if score >= self.escalate_if_score_at_least:
            return CHIEF
        if score < self.drop_if_score_below:
            return DROP
        return CHEAP
