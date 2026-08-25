# -*- coding: utf-8 -*-
"""Deterministic pre-filter — drop obvious noise BEFORE any LLM call (0 tokens).

Pure, dependency-free rules. The point: most items in a stream are noise or
duplicates; deciding that with code (not an LLM) is free and instant.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from difflib import SequenceMatcher


@dataclass
class PreVerdict:
    keep: bool
    score: float
    reason: str | None = None


@dataclass
class PreFilter:
    """Cheap rules that decide whether an item is worth an LLM at all.

    drop_substrings : case-insensitive noise markers -> drop (e.g. "sponsored").
    keep_keywords   : if non-empty, item must contain >=1 -> else drop (materiality).
    min_chars       : drop items shorter than this.
    dedup_threshold : 0 disables; else 1-100 fuzzy ratio vs already-seen -> drop near-dupes.
    base_score      : score given to a kept item (an LLM stage may refine it).
    """
    drop_substrings: tuple[str, ...] = ()
    keep_keywords: tuple[str, ...] = ()
    min_chars: int = 0
    dedup_threshold: int = 0
    base_score: float = 0.6

    def __post_init__(self) -> None:
        if isinstance(self.min_chars, bool) or not isinstance(self.min_chars, int):
            raise TypeError("min_chars must be an integer")
        if self.min_chars < 0:
            raise ValueError("min_chars must be non-negative")
        if isinstance(self.dedup_threshold, bool) or not isinstance(self.dedup_threshold, int):
            raise TypeError("dedup_threshold must be an integer")
        if not 0 <= self.dedup_threshold <= 100:
            raise ValueError("dedup_threshold must be in the 0..100 range")
        if isinstance(self.base_score, bool) or not isinstance(self.base_score, (int, float)):
            raise TypeError("base_score must be numeric")
        score = float(self.base_score)
        if (
            not math.isfinite(score)
            or (score == 0.0 and math.copysign(1.0, score) < 0.0)
            or not 0.0 <= score <= 1.0
        ):
            raise ValueError("base_score must be finite and in the 0..1 range")
        self.base_score = score
        for values, label in (
            (self.drop_substrings, "drop_substrings"),
            (self.keep_keywords, "keep_keywords"),
        ):
            if not isinstance(values, tuple) or any(
                not isinstance(value, str) or not value for value in values
            ):
                raise TypeError(f"{label} must be a tuple of non-empty strings")

    def score(self, text: str, seen: list[str]) -> PreVerdict:
        if not isinstance(text, str):
            raise TypeError("prefilter text must be a string")
        if not isinstance(seen, list) or any(not isinstance(value, str) for value in seen):
            raise TypeError("prefilter seen values must be strings")
        low = text.lower().strip()
        if len(low) < self.min_chars:
            return PreVerdict(False, 0.0, "too_short")
        for s in self.drop_substrings:
            if s.lower() in low:
                return PreVerdict(False, 0.0, "noise_match")
        if self.keep_keywords and not any(k.lower() in low for k in self.keep_keywords):
            return PreVerdict(False, 0.0, "no_keyword")
        if self.dedup_threshold:
            for prev in seen:
                if SequenceMatcher(None, low, prev).ratio() * 100 >= self.dedup_threshold:
                    return PreVerdict(False, 0.0, "duplicate")
        return PreVerdict(True, self.base_score, None)
