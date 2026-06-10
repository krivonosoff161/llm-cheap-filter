# -*- coding: utf-8 -*-
"""Escalation policy — pure rules deciding drop / keep-cheap / escalate-to-chief."""
from __future__ import annotations

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
        if not (0.0 <= self.drop_if_score_below < self.escalate_if_score_at_least <= 1.0):
            raise ValueError(
                "EscalationPolicy requires 0.0 <= drop_if_score_below < "
                "escalate_if_score_at_least <= 1.0 "
                f"(got drop={self.drop_if_score_below}, escalate={self.escalate_if_score_at_least})"
            )

    def decide(self, score: float, flagged: bool = False) -> str:
        if self.escalate_if_flagged and flagged:
            return CHIEF
        if score >= self.escalate_if_score_at_least:
            return CHIEF
        if score < self.drop_if_score_below:
            return DROP
        return CHEAP
