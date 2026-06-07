# -*- coding: utf-8 -*-
"""Deterministic pre-filter — drop obvious noise BEFORE any LLM call (0 tokens).

Pure, dependency-free rules. The point: most items in a stream are noise or
duplicates; deciding that with code (not an LLM) is free and instant.
"""
from __future__ import annotations

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

    def score(self, text: str, seen: list[str]) -> PreVerdict:
        low = (text or "").lower().strip()
        if len(low) < self.min_chars:
            return PreVerdict(False, 0.0, "too_short")
        for s in self.drop_substrings:
            if s.lower() in low:
                return PreVerdict(False, 0.0, f"noise:{s}")
        if self.keep_keywords and not any(k.lower() in low for k in self.keep_keywords):
            return PreVerdict(False, 0.0, "no_keyword")
        if self.dedup_threshold:
            for prev in seen:
                if SequenceMatcher(None, low, prev.lower()).ratio() * 100 >= self.dedup_threshold:
                    return PreVerdict(False, 0.0, "duplicate")
        return PreVerdict(True, self.base_score, None)
