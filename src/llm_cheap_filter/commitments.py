"""Domain-separated configuration commitments shared by pipeline and receipt."""
from __future__ import annotations

import hashlib
import json

from .policy import EscalationPolicy
from .prefilter import PreFilter


TRIAGE_CONFIGURATION_DOMAIN = b"llm-cheap-filter/prefilter-configuration/v1\0"
TRIAGE_POLICY_DOMAIN = b"llm-cheap-filter/escalation-policy/v1\0"


def prefilter_configuration_sha256(prefilter: PreFilter) -> str:
    """Bind exact prefilter values without exposing configured strings."""

    if not isinstance(prefilter, PreFilter):
        raise TypeError("prefilter must be PreFilter")
    payload = {
        "drop_substrings": list(prefilter.drop_substrings),
        "keep_keywords": list(prefilter.keep_keywords),
        "min_chars": prefilter.min_chars,
        "dedup_threshold": prefilter.dedup_threshold,
        "base_score": prefilter.base_score,
    }
    return hashlib.sha256(TRIAGE_CONFIGURATION_DOMAIN + _canonical_json(payload)).hexdigest()


def escalation_policy_sha256(policy: EscalationPolicy) -> str:
    """Bind exact pure-policy thresholds and flag behavior."""

    if not isinstance(policy, EscalationPolicy):
        raise TypeError("policy must be EscalationPolicy")
    payload = {
        "drop_if_score_below": policy.drop_if_score_below,
        "escalate_if_score_at_least": policy.escalate_if_score_at_least,
        "escalate_if_flagged": policy.escalate_if_flagged,
    }
    return hashlib.sha256(TRIAGE_POLICY_DOMAIN + _canonical_json(payload)).hexdigest()


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
