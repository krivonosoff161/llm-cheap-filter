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

    def decide(self, score: float, flagged: bool = False) -> str:
        if self.escalate_if_flagged and flagged:
            return CHIEF
        if score >= self.escalate_if_score_at_least:
            return CHIEF
        if score < self.drop_if_score_below:
            return DROP
        return CHEAP
