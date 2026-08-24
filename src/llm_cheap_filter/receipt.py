# -*- coding: utf-8 -*-
"""Closed canonical triage batch receipt V1.

The receipt is a privacy-minimized accounting projection over an already completed
``Pipeline`` report. It never executes injected callables and never serializes item
text, raw cheap/chief decisions, exceptions, prompts, or model output.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from typing import Any, Dict, Literal, Optional, Tuple

from .pipeline import ItemResult, Report, _input_sha256
from .policy import EscalationPolicy
from .prefilter import PreFilter


TRIAGE_BATCH_RECEIPT_V1 = "llm-cheap-filter-triage-batch-receipt-v1.0"
TRIAGE_BATCH_RECEIPT_DOMAIN = b"llm-cheap-filter/triage-batch-receipt/v1\0"
TRIAGE_INPUT_BATCH_DOMAIN = b"llm-cheap-filter/triage-input-batch/v1\0"
TRIAGE_CONFIGURATION_DOMAIN = b"llm-cheap-filter/prefilter-configuration/v1\0"
TRIAGE_POLICY_DOMAIN = b"llm-cheap-filter/escalation-policy/v1\0"
TRIAGE_DECISION_DOMAIN = b"llm-cheap-filter/decision/v1\0"
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
REASON_CODE_PATTERN = re.compile(r"^[a-z][a-z0-9_.-]{0,127}$")
MAX_RECEIPT_RESULTS = 100_000
MAX_DECISION_BYTES = 65_536
MAX_RECEIPT_BYTES = 16_777_216
MAX_USAGE_TOKENS = 9_007_199_254_740_991
MAX_USAGE_COST_USD = 1_000_000_000.0

TriageReceiptStage = Literal[
    "prefilter_drop",
    "cheap_drop",
    "cheap_keep",
    "chief",
    "error",
    "cancelled",
]

_STAGES = {
    "prefilter_drop",
    "cheap_drop",
    "cheap_keep",
    "chief",
    "error",
    "cancelled",
}
_PREFILTER_REASONS = {
    "too_short": "prefilter.too_short",
    "noise_match": "prefilter.noise_match",
    "no_keyword": "prefilter.required_keyword_missing",
    "duplicate": "prefilter.duplicate",
}
_ERROR_REASONS = {
    "pipeline.cheap_invalid_output",
    "pipeline.chief_invalid_output",
    "pipeline.cheap_callable_error",
    "pipeline.chief_callable_error",
}


class TriageReceiptContractError(ValueError):
    """Raised when receipt data violates the closed V1 contract."""


@dataclass(frozen=True)
class TriageReceiptResultV1:
    """One privacy-minimized terminal result bound to exactly one batch input."""

    input_index: int
    input_sha256: str
    stage: TriageReceiptStage
    score: float
    flagged: Optional[bool]
    total_tokens: int
    cost_usd: float
    reason_codes: Tuple[str, ...]
    decision_sha256: str
    may_lower_security_decision: Literal[False]
    operational_authority: Literal["none"]

    def __post_init__(self) -> None:
        if isinstance(self.input_index, bool) or not isinstance(self.input_index, int):
            raise TriageReceiptContractError("input_index must be an integer")
        if self.input_index < 0 or self.input_index >= MAX_RECEIPT_RESULTS:
            raise TriageReceiptContractError("input_index is outside the V1 range")
        _require_digest(self.input_sha256, "input_sha256")
        if self.stage not in _STAGES:
            raise TriageReceiptContractError("unsupported triage receipt stage")
        _require_score(self.score)
        if self.flagged is not None and not isinstance(self.flagged, bool):
            raise TriageReceiptContractError("flagged must be a bool or null")
        _require_usage(self.total_tokens, self.cost_usd)
        if not self.reason_codes or len(self.reason_codes) > 16:
            raise TriageReceiptContractError("reason code count is outside the V1 range")
        if len(self.reason_codes) != len(set(self.reason_codes)) or any(
            not REASON_CODE_PATTERN.fullmatch(code) for code in self.reason_codes
        ):
            raise TriageReceiptContractError("reason codes must be unique canonical tokens")
        _require_digest(self.decision_sha256, "decision_sha256")
        if self.may_lower_security_decision is not False:
            raise TriageReceiptContractError("receipt results cannot lower security decisions")
        if self.operational_authority != "none":
            raise TriageReceiptContractError("receipt results have no operational authority")


@dataclass(frozen=True)
class TriageReceiptSummaryV1:
    """Exact accounting totals derived from the result stage universe."""

    input_count: int
    prefilter_drop: int
    cheap_drop: int
    cheap_keep: int
    chief: int
    error: int
    cancelled: int
    total_tokens: int
    total_cost_usd: float

    def __post_init__(self) -> None:
        counts = (
            self.input_count,
            self.prefilter_drop,
            self.cheap_drop,
            self.cheap_keep,
            self.chief,
            self.error,
            self.cancelled,
        )
        if any(isinstance(value, bool) or not isinstance(value, int) for value in counts):
            raise TriageReceiptContractError("summary counts must be integers")
        if any(value < 0 or value > MAX_RECEIPT_RESULTS for value in counts):
            raise TriageReceiptContractError("summary count is outside the V1 range")
        if sum(counts[1:]) != self.input_count:
            raise TriageReceiptContractError("summary stages do not account for every input")
        _require_usage(self.total_tokens, self.total_cost_usd)


@dataclass(frozen=True)
class TriageBatchReceiptV1:
    """Content-bound, authority-free receipt for one completed triage batch."""

    schema_version: Literal["llm-cheap-filter-triage-batch-receipt-v1.0"]
    receipt_id: str
    input_batch_sha256: str
    prefilter_configuration_sha256: str
    escalation_policy_sha256: str
    results: Tuple[TriageReceiptResultV1, ...]
    summary: TriageReceiptSummaryV1
    verdict_semantics: Literal["triage_accounting_only_no_security_verdict"]
    may_lower_security_decision: Literal[False]
    operational_authority: Literal["none"]

    def __post_init__(self) -> None:
        if self.schema_version != TRIAGE_BATCH_RECEIPT_V1:
            raise TriageReceiptContractError("unsupported triage batch receipt version")
        for value, label in (
            (self.receipt_id, "receipt_id"),
            (self.input_batch_sha256, "input_batch_sha256"),
            (self.prefilter_configuration_sha256, "prefilter_configuration_sha256"),
            (self.escalation_policy_sha256, "escalation_policy_sha256"),
        ):
            _require_digest(value, label)
        if len(self.results) > MAX_RECEIPT_RESULTS:
            raise TriageReceiptContractError("receipt result count exceeds the V1 limit")
        if tuple(result.input_index for result in self.results) != tuple(
            range(len(self.results))
        ):
            raise TriageReceiptContractError("receipt results must bind contiguous input order")
        if self.summary != _summarize_results(self.results):
            raise TriageReceiptContractError("receipt summary does not match exact results")
        if self.input_batch_sha256 != _input_batch_sha256(
            tuple(result.input_sha256 for result in self.results)
        ):
            raise TriageReceiptContractError("receipt input batch binding drift")
        if self.verdict_semantics != "triage_accounting_only_no_security_verdict":
            raise TriageReceiptContractError("receipt cannot represent a security verdict")
        if self.may_lower_security_decision is not False:
            raise TriageReceiptContractError("receipt cannot lower a security decision")
        if self.operational_authority != "none":
            raise TriageReceiptContractError("receipt has no operational authority")
        if self.receipt_id != _receipt_identity(self):
            raise TriageReceiptContractError("receipt_id does not bind canonical receipt content")


def build_triage_batch_receipt_v1(
    report: Report,
    *,
    prefilter: PreFilter,
    policy: EscalationPolicy,
) -> TriageBatchReceiptV1:
    """Build one receipt without retaining raw input or callable output bytes."""

    if not isinstance(report, Report):
        raise TriageReceiptContractError("receipt input must be a Report")
    if report.input_sha256s is None:
        raise TriageReceiptContractError("report lacks pipeline-owned input commitments")
    if len(report.results) != len(report.input_sha256s):
        raise TriageReceiptContractError("report input/result accounting is incomplete")
    if len(report.results) > MAX_RECEIPT_RESULTS:
        raise TriageReceiptContractError("report result count exceeds the V1 limit")

    results = tuple(
        _project_result(index, result, report.input_sha256s[index])
        for index, result in enumerate(report.results)
    )
    payload = {
        "schema_version": TRIAGE_BATCH_RECEIPT_V1,
        "input_batch_sha256": _input_batch_sha256(report.input_sha256s),
        "prefilter_configuration_sha256": prefilter_configuration_sha256(prefilter),
        "escalation_policy_sha256": escalation_policy_sha256(policy),
        "results": [_result_to_dict(result) for result in results],
        "summary": _summary_to_dict(_summarize_results(results)),
        "verdict_semantics": "triage_accounting_only_no_security_verdict",
        "may_lower_security_decision": False,
        "operational_authority": "none",
    }
    payload["receipt_id"] = _identity_from_payload(payload)
    return _receipt_from_dict(payload)


def prefilter_configuration_sha256(prefilter: PreFilter) -> str:
    """Bind exact prefilter values without exposing configured strings in a receipt."""

    if not isinstance(prefilter, PreFilter):
        raise TriageReceiptContractError("prefilter must be PreFilter")
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
        raise TriageReceiptContractError("policy must be EscalationPolicy")
    payload = {
        "drop_if_score_below": policy.drop_if_score_below,
        "escalate_if_score_at_least": policy.escalate_if_score_at_least,
        "escalate_if_flagged": policy.escalate_if_flagged,
    }
    return hashlib.sha256(TRIAGE_POLICY_DOMAIN + _canonical_json(payload)).hexdigest()


def encode_triage_batch_receipt_v1(receipt: TriageBatchReceiptV1) -> bytes:
    """Encode the single canonical UTF-8 JSON representation."""

    if not isinstance(receipt, TriageBatchReceiptV1):
        raise TriageReceiptContractError("receipt must be TriageBatchReceiptV1")
    payload = _receipt_to_dict(receipt)
    encoded = _canonical_json(payload) + b"\n"
    if len(encoded) > MAX_RECEIPT_BYTES:
        raise TriageReceiptContractError("receipt exceeds the V1 byte limit")
    return encoded


def decode_triage_batch_receipt_v1(payload: bytes) -> TriageBatchReceiptV1:
    """Decode exact canonical bytes; ambiguity and unknown fields fail closed."""

    if not isinstance(payload, bytes):
        raise TriageReceiptContractError("receipt payload must be bytes")
    if not payload or len(payload) > MAX_RECEIPT_BYTES:
        raise TriageReceiptContractError("receipt payload size is outside the V1 limit")
    try:
        decoded = json.loads(payload.decode("utf-8"), object_pairs_hook=_strict_json_object)
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise TriageReceiptContractError("receipt is not valid UTF-8 JSON") from exc
    receipt = _receipt_from_dict(decoded)
    if encode_triage_batch_receipt_v1(receipt) != payload:
        raise TriageReceiptContractError("receipt JSON is not canonical V1")
    return receipt


def triage_batch_receipt_v1_json_schema() -> Dict[str, Any]:
    """Return the closed public JSON Schema for canonical receipt bytes."""

    digest = {"type": "string", "pattern": "^[0-9a-f]{64}$"}
    nonnegative_integer = {
        "type": "integer",
        "minimum": 0,
        "maximum": MAX_USAGE_TOKENS,
    }
    finite_cost = {"type": "number", "minimum": 0, "maximum": MAX_USAGE_COST_USD}
    result_properties = {
        "input_index": {
            "type": "integer",
            "minimum": 0,
            "maximum": MAX_RECEIPT_RESULTS - 1,
        },
        "input_sha256": digest,
        "stage": {"enum": sorted(_STAGES)},
        "score": {"type": "number", "minimum": 0, "maximum": 1},
        "flagged": {"type": ["boolean", "null"]},
        "total_tokens": nonnegative_integer,
        "cost_usd": finite_cost,
        "reason_codes": {
            "type": "array",
            "minItems": 1,
            "maxItems": 16,
            "uniqueItems": True,
            "items": {"type": "string", "pattern": "^[a-z][a-z0-9_.-]{0,127}$"},
        },
        "decision_sha256": digest,
        "may_lower_security_decision": {"const": False},
        "operational_authority": {"const": "none"},
    }
    summary_properties = {
        name: nonnegative_integer
        for name in (
            "input_count",
            "prefilter_drop",
            "cheap_drop",
            "cheap_keep",
            "chief",
            "error",
            "cancelled",
            "total_tokens",
        )
    }
    summary_properties["total_cost_usd"] = finite_cost
    root_properties = {
        "schema_version": {"const": TRIAGE_BATCH_RECEIPT_V1},
        "receipt_id": digest,
        "input_batch_sha256": digest,
        "prefilter_configuration_sha256": digest,
        "escalation_policy_sha256": digest,
        "results": {
            "type": "array",
            "maxItems": MAX_RECEIPT_RESULTS,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": list(result_properties),
                "properties": result_properties,
            },
        },
        "summary": {
            "type": "object",
            "additionalProperties": False,
            "required": list(summary_properties),
            "properties": summary_properties,
        },
        "verdict_semantics": {"const": "triage_accounting_only_no_security_verdict"},
        "may_lower_security_decision": {"const": False},
        "operational_authority": {"const": "none"},
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://github.com/krivonosoff161/llm-cheap-filter/blob/main/"
        "schemas/triage-batch-receipt.v1.schema.json",
        "title": "LLM Cheap Filter Triage Batch Receipt V1",
        "type": "object",
        "additionalProperties": False,
        "required": list(root_properties),
        "properties": root_properties,
    }


def _project_result(index: int, result: ItemResult, input_sha256: str) -> TriageReceiptResultV1:
    if not isinstance(result, ItemResult):
        raise TriageReceiptContractError("report contains a non-ItemResult value")
    if input_sha256 != _input_sha256(result.item):
        raise TriageReceiptContractError("report result does not match its input commitment")
    _require_score(result.score)
    _require_usage(result.tokens, result.cost)
    if result.flagged is not None and not isinstance(result.flagged, bool):
        raise TriageReceiptContractError("report flagged value must be bool or null")

    if result.stage == "filtered":
        try:
            reason = _PREFILTER_REASONS[result.reason or ""]
        except KeyError as exc:
            raise TriageReceiptContractError("unsupported prefilter reason") from exc
        stage: TriageReceiptStage = "prefilter_drop"
        decision = {"keep": False, "reason_code": reason, "score": result.score}
        flagged = None
    elif result.stage == "cheap" and result.reason == "below_threshold":
        stage = "cheap_drop"
        reason = "routing.cheap_drop"
        decision = _require_decision(result.decision)
        flagged = result.flagged
    elif result.stage == "cheap" and result.reason is None:
        stage = "cheap_keep"
        reason = "routing.cheap_keep"
        decision = _require_decision(result.decision)
        flagged = result.flagged
    elif result.stage == "chief" and result.reason is None:
        stage = "chief"
        reason = "routing.escalated_chief"
        decision = _require_decision(result.decision)
        flagged = result.flagged
    elif result.stage == "error" and result.reason in _ERROR_REASONS:
        stage = "error"
        reason = result.reason
        decision = {"reason_code": reason, "stage": stage}
        flagged = None
    elif result.stage == "cancelled" and result.reason == "pipeline.callable_cancelled":
        stage = "cancelled"
        reason = result.reason
        decision = {"reason_code": reason, "stage": stage}
        flagged = None
    else:
        raise TriageReceiptContractError("unsupported or ambiguous report result state")

    return TriageReceiptResultV1(
        input_index=index,
        input_sha256=input_sha256,
        stage=stage,
        score=float(result.score),
        flagged=flagged,
        total_tokens=result.tokens,
        cost_usd=float(result.cost),
        reason_codes=(reason,),
        decision_sha256=_decision_sha256(
            decision,
            input_sha256=input_sha256,
            stage=stage,
        ),
        may_lower_security_decision=False,
        operational_authority="none",
    )


def _summarize_results(
    results: Tuple[TriageReceiptResultV1, ...]
) -> TriageReceiptSummaryV1:
    by_stage = {stage: 0 for stage in _STAGES}
    for result in results:
        by_stage[result.stage] += 1
    total_tokens = sum(result.total_tokens for result in results)
    total_cost = sum((result.cost_usd for result in results), 0.0)
    _require_usage(total_tokens, total_cost)
    return TriageReceiptSummaryV1(
        input_count=len(results),
        prefilter_drop=by_stage["prefilter_drop"],
        cheap_drop=by_stage["cheap_drop"],
        cheap_keep=by_stage["cheap_keep"],
        chief=by_stage["chief"],
        error=by_stage["error"],
        cancelled=by_stage["cancelled"],
        total_tokens=total_tokens,
        total_cost_usd=total_cost,
    )


def _input_batch_sha256(input_sha256s: Tuple[str, ...]) -> str:
    for digest in input_sha256s:
        _require_digest(digest, "input_sha256")
    payload = [
        {"input_index": index, "input_sha256": digest}
        for index, digest in enumerate(input_sha256s)
    ]
    return hashlib.sha256(TRIAGE_INPUT_BATCH_DOMAIN + _canonical_json(payload)).hexdigest()


def _decision_sha256(
    decision: Dict[str, Any],
    *,
    input_sha256: Optional[str] = None,
    stage: Optional[str] = None,
) -> str:
    if input_sha256 is None or stage is None:
        payload = _canonical_json(decision)
    else:
        payload = _canonical_json(
            {
                "decision": decision,
                "input_sha256": input_sha256,
                "stage": stage,
            }
        )
    if len(payload) > MAX_DECISION_BYTES:
        raise TriageReceiptContractError("decision exceeds the V1 digest input limit")
    return hashlib.sha256(TRIAGE_DECISION_DOMAIN + payload).hexdigest()


def _require_decision(value: object) -> Dict[str, Any]:
    if not isinstance(value, dict):
        raise TriageReceiptContractError("report decision must be a dict")
    _canonical_json(value)
    return value


def _receipt_identity(receipt: TriageBatchReceiptV1) -> str:
    payload = _receipt_to_dict(receipt)
    payload.pop("receipt_id")
    return _identity_from_payload(payload)


def _identity_from_payload(payload: Dict[str, Any]) -> str:
    identity_payload = dict(payload)
    identity_payload.pop("receipt_id", None)
    return hashlib.sha256(
        TRIAGE_BATCH_RECEIPT_DOMAIN + _canonical_json(identity_payload)
    ).hexdigest()


def _receipt_to_dict(receipt: TriageBatchReceiptV1) -> Dict[str, Any]:
    return {
        "schema_version": receipt.schema_version,
        "receipt_id": receipt.receipt_id,
        "input_batch_sha256": receipt.input_batch_sha256,
        "prefilter_configuration_sha256": receipt.prefilter_configuration_sha256,
        "escalation_policy_sha256": receipt.escalation_policy_sha256,
        "results": [_result_to_dict(result) for result in receipt.results],
        "summary": _summary_to_dict(receipt.summary),
        "verdict_semantics": receipt.verdict_semantics,
        "may_lower_security_decision": receipt.may_lower_security_decision,
        "operational_authority": receipt.operational_authority,
    }


def _result_to_dict(result: TriageReceiptResultV1) -> Dict[str, Any]:
    return {
        "input_index": result.input_index,
        "input_sha256": result.input_sha256,
        "stage": result.stage,
        "score": result.score,
        "flagged": result.flagged,
        "total_tokens": result.total_tokens,
        "cost_usd": result.cost_usd,
        "reason_codes": list(result.reason_codes),
        "decision_sha256": result.decision_sha256,
        "may_lower_security_decision": result.may_lower_security_decision,
        "operational_authority": result.operational_authority,
    }


def _summary_to_dict(summary: TriageReceiptSummaryV1) -> Dict[str, Any]:
    return {
        "input_count": summary.input_count,
        "prefilter_drop": summary.prefilter_drop,
        "cheap_drop": summary.cheap_drop,
        "cheap_keep": summary.cheap_keep,
        "chief": summary.chief,
        "error": summary.error,
        "cancelled": summary.cancelled,
        "total_tokens": summary.total_tokens,
        "total_cost_usd": summary.total_cost_usd,
    }


def _receipt_from_dict(value: object) -> TriageBatchReceiptV1:
    root_fields = {
        "schema_version",
        "receipt_id",
        "input_batch_sha256",
        "prefilter_configuration_sha256",
        "escalation_policy_sha256",
        "results",
        "summary",
        "verdict_semantics",
        "may_lower_security_decision",
        "operational_authority",
    }
    root = _require_exact_object(value, root_fields, "receipt")
    raw_results = root["results"]
    if not isinstance(raw_results, list) or len(raw_results) > MAX_RECEIPT_RESULTS:
        raise TriageReceiptContractError("receipt results must be a bounded list")
    results = tuple(_result_from_dict(item) for item in raw_results)
    summary = _summary_from_dict(root["summary"])
    try:
        return TriageBatchReceiptV1(
            schema_version=root["schema_version"],
            receipt_id=root["receipt_id"],
            input_batch_sha256=root["input_batch_sha256"],
            prefilter_configuration_sha256=root["prefilter_configuration_sha256"],
            escalation_policy_sha256=root["escalation_policy_sha256"],
            results=results,
            summary=summary,
            verdict_semantics=root["verdict_semantics"],
            may_lower_security_decision=root["may_lower_security_decision"],
            operational_authority=root["operational_authority"],
        )
    except (TypeError, ValueError) as exc:
        if isinstance(exc, TriageReceiptContractError):
            raise
        raise TriageReceiptContractError("receipt values violate V1") from exc


def _result_from_dict(value: object) -> TriageReceiptResultV1:
    fields = {
        "input_index",
        "input_sha256",
        "stage",
        "score",
        "flagged",
        "total_tokens",
        "cost_usd",
        "reason_codes",
        "decision_sha256",
        "may_lower_security_decision",
        "operational_authority",
    }
    item = _require_exact_object(value, fields, "receipt result")
    reasons = item["reason_codes"]
    if not isinstance(reasons, list) or any(not isinstance(code, str) for code in reasons):
        raise TriageReceiptContractError("reason_codes must be a string list")
    return TriageReceiptResultV1(
        input_index=item["input_index"],
        input_sha256=item["input_sha256"],
        stage=item["stage"],
        score=_require_json_float(item["score"], "score"),
        flagged=item["flagged"],
        total_tokens=item["total_tokens"],
        cost_usd=_require_json_float(item["cost_usd"], "cost_usd"),
        reason_codes=tuple(reasons),
        decision_sha256=item["decision_sha256"],
        may_lower_security_decision=item["may_lower_security_decision"],
        operational_authority=item["operational_authority"],
    )


def _summary_from_dict(value: object) -> TriageReceiptSummaryV1:
    fields = {
        "input_count",
        "prefilter_drop",
        "cheap_drop",
        "cheap_keep",
        "chief",
        "error",
        "cancelled",
        "total_tokens",
        "total_cost_usd",
    }
    item = _require_exact_object(value, fields, "receipt summary")
    return TriageReceiptSummaryV1(
        input_count=item["input_count"],
        prefilter_drop=item["prefilter_drop"],
        cheap_drop=item["cheap_drop"],
        cheap_keep=item["cheap_keep"],
        chief=item["chief"],
        error=item["error"],
        cancelled=item["cancelled"],
        total_tokens=item["total_tokens"],
        total_cost_usd=_require_json_float(item["total_cost_usd"], "total_cost_usd"),
    )


def _require_exact_object(
    value: object, expected: set, label: str
) -> Dict[str, Any]:
    if not isinstance(value, dict) or set(value) != expected:
        raise TriageReceiptContractError(f"{label} fields do not match V1")
    return value


def _require_json_float(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, float):
        raise TriageReceiptContractError(f"{label} must use canonical JSON number form")
    return value


def _require_score(value: object) -> None:
    if isinstance(value, bool) or not isinstance(value, float):
        raise TriageReceiptContractError("score must be a float")
    if not math.isfinite(value) or not 0.0 <= value <= 1.0:
        raise TriageReceiptContractError("score must be finite and in the 0..1 range")


def _require_usage(tokens: object, cost: object) -> None:
    if isinstance(tokens, bool) or not isinstance(tokens, int):
        raise TriageReceiptContractError("total_tokens must be an integer")
    if not 0 <= tokens <= MAX_USAGE_TOKENS:
        raise TriageReceiptContractError("total_tokens is outside the V1 range")
    if isinstance(cost, bool) or not isinstance(cost, float):
        raise TriageReceiptContractError("cost_usd must be a float")
    if not math.isfinite(cost) or not 0.0 <= cost <= MAX_USAGE_COST_USD:
        raise TriageReceiptContractError("cost_usd is outside the finite V1 range")


def _require_digest(value: object, label: str) -> None:
    if not isinstance(value, str) or not SHA256_PATTERN.fullmatch(value):
        raise TriageReceiptContractError(f"{label} must be lowercase SHA-256")


def _canonical_json(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError, RecursionError) as exc:
        raise TriageReceiptContractError("value is not bounded canonical JSON data") from exc


def _strict_json_object(pairs: list) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise TriageReceiptContractError("duplicate JSON field")
        result[key] = value
    return result
