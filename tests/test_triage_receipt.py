from __future__ import annotations

import asyncio
import hashlib
import json

import pytest

from llm_cheap_filter import (
    EscalationPolicy,
    ItemResult,
    Pipeline,
    PreFilter,
    Report,
    TriageReceiptContractError,
    build_triage_batch_receipt_v1,
    decode_triage_batch_receipt_v1,
    encode_triage_batch_receipt_v1,
    escalation_policy_sha256,
    prefilter_configuration_sha256,
    triage_batch_receipt_v1_json_schema,
)


INPUT_DOMAIN = b"llm-cheap-filter/input/v1\0"


def _input_digest(value: str) -> str:
    return hashlib.sha256(INPUT_DOMAIN + value.encode("utf-8")).hexdigest()


def _pipeline_and_report():
    async def cheap(text):
        if "error" in text:
            raise RuntimeError("PRIVATE_EXCEPTION_CANARY")
        score = 0.1 if "drop" in text else 0.4 if "keep" in text else 0.9
        return (
            {
                "score": score,
                "flagged": False,
                "raw_model_output": "MODEL_OUTPUT_CANARY",
            },
            {"total_tokens": 3, "cost_usd": 0.001},
        )

    async def chief(text, judgment):
        return {
            "verdict": "REVIEW",
            "raw_decision": "CHIEF_DECISION_CANARY",
        }, {"total_tokens": 7, "cost_usd": 0.004}

    prefilter = PreFilter(drop_substrings=("SECRET_CONFIG_CANARY",), min_chars=1)
    policy = EscalationPolicy(escalate_if_score_at_least=0.8, drop_if_score_below=0.2)
    inputs = [
        "SECRET_CONFIG_CANARY raw item",
        "drop candidate",
        "keep candidate",
        "chief candidate",
        "error PRIVATE_ITEM_CANARY",
    ]
    report = asyncio.run(Pipeline(prefilter, policy, cheap, chief).run(inputs))
    return prefilter, policy, report


def test_receipt_accounts_for_all_terminal_stages_without_raw_payloads() -> None:
    prefilter, policy, report = _pipeline_and_report()
    receipt = build_triage_batch_receipt_v1(report, prefilter=prefilter, policy=policy)
    encoded = encode_triage_batch_receipt_v1(receipt)

    assert [result.stage for result in receipt.results] == [
        "prefilter_drop",
        "cheap_drop",
        "cheap_keep",
        "chief",
        "error",
    ]
    assert receipt.summary.input_count == 5
    assert receipt.summary.total_tokens == 3 + 3 + 10
    assert receipt.summary.total_cost_usd == pytest.approx(0.007)
    assert receipt.may_lower_security_decision is False
    assert receipt.operational_authority == "none"
    assert receipt.verdict_semantics == "triage_accounting_only_no_security_verdict"
    for forbidden in (
        b"SECRET_CONFIG_CANARY",
        b"PRIVATE_ITEM_CANARY",
        b"PRIVATE_EXCEPTION_CANARY",
        b"MODEL_OUTPUT_CANARY",
        b"CHIEF_DECISION_CANARY",
        b"raw_model_output",
        b"raw_decision",
        b"prompt",
    ):
        assert forbidden not in encoded


def test_cancelled_stage_is_explicit_and_authority_free() -> None:
    text = "cancelled raw item"
    report = Report(
        [
            ItemResult(
                text,
                "cancelled",
                0.6,
                reason="pipeline.callable_cancelled",
            )
        ],
        input_sha256s=(_input_digest(text),),
    )
    receipt = build_triage_batch_receipt_v1(
        report, prefilter=PreFilter(), policy=EscalationPolicy()
    )

    assert receipt.results[0].stage == "cancelled"
    assert receipt.summary.cancelled == 1
    assert receipt.results[0].may_lower_security_decision is False


def test_receipt_round_trip_is_exact_and_canonical() -> None:
    prefilter, policy, report = _pipeline_and_report()
    receipt = build_triage_batch_receipt_v1(report, prefilter=prefilter, policy=policy)
    encoded = encode_triage_batch_receipt_v1(receipt)

    assert decode_triage_batch_receipt_v1(encoded) == receipt
    assert encoded.endswith(b"\n")
    assert b" " not in encoded


def test_receipt_binds_policy_configuration_inputs_and_decisions() -> None:
    prefilter, policy, report = _pipeline_and_report()
    receipt = build_triage_batch_receipt_v1(report, prefilter=prefilter, policy=policy)

    assert receipt.prefilter_configuration_sha256 == prefilter_configuration_sha256(prefilter)
    assert receipt.escalation_policy_sha256 == escalation_policy_sha256(policy)
    assert [result.input_sha256 for result in receipt.results] == list(report.input_sha256s)
    assert len({result.decision_sha256 for result in receipt.results}) == len(receipt.results)

    changed = build_triage_batch_receipt_v1(
        report,
        prefilter=PreFilter(drop_substrings=("different",), min_chars=1),
        policy=EscalationPolicy(escalate_if_score_at_least=0.9),
    )
    assert changed.prefilter_configuration_sha256 != receipt.prefilter_configuration_sha256
    assert changed.escalation_policy_sha256 != receipt.escalation_policy_sha256
    assert changed.receipt_id != receipt.receipt_id


def test_receipt_rejects_missing_or_rebound_input_accounting() -> None:
    prefilter, policy, report = _pipeline_and_report()
    report.input_sha256s = None
    with pytest.raises(TriageReceiptContractError, match="lacks"):
        build_triage_batch_receipt_v1(report, prefilter=prefilter, policy=policy)

    with pytest.raises(ValueError, match="commitment"):
        Report(
            [ItemResult("item", "filtered", 0.0, reason="too_short")],
            input_sha256s=("0" * 64,),
        )


def test_decoder_rejects_unknown_duplicate_noncanonical_and_tampered_bytes() -> None:
    prefilter, policy, report = _pipeline_and_report()
    receipt = build_triage_batch_receipt_v1(report, prefilter=prefilter, policy=policy)
    encoded = encode_triage_batch_receipt_v1(receipt)
    payload = json.loads(encoded)

    unknown = dict(payload)
    unknown["raw_item"] = "forbidden"
    with pytest.raises(TriageReceiptContractError, match="fields"):
        decode_triage_batch_receipt_v1(
            json.dumps(unknown, sort_keys=True, separators=(",", ":")).encode() + b"\n"
        )

    duplicate = encoded.replace(b'{"escalation_policy_sha256"', b'{"receipt_id":"0","escalation_policy_sha256"', 1)
    with pytest.raises(TriageReceiptContractError, match="duplicate"):
        decode_triage_batch_receipt_v1(duplicate)

    with pytest.raises(TriageReceiptContractError, match="canonical"):
        decode_triage_batch_receipt_v1(encoded.replace(b":", b": ", 1))

    tampered = dict(payload)
    tampered["receipt_id"] = "0" * 64
    with pytest.raises(TriageReceiptContractError, match="receipt_id"):
        decode_triage_batch_receipt_v1(
            json.dumps(tampered, sort_keys=True, separators=(",", ":")).encode() + b"\n"
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("score", float("nan")),
        ("score", True),
        ("total_tokens", True),
        ("total_tokens", -1),
        ("cost_usd", float("inf")),
        ("cost_usd", -1.0),
        ("flagged", "false"),
    ],
)
def test_decoder_rejects_non_finite_or_ambiguous_result_values(field, value) -> None:
    prefilter, policy, report = _pipeline_and_report()
    receipt = build_triage_batch_receipt_v1(report, prefilter=prefilter, policy=policy)
    payload = json.loads(encode_triage_batch_receipt_v1(receipt))
    payload["results"][1][field] = value
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), allow_nan=True
    ).encode() + b"\n"

    with pytest.raises(TriageReceiptContractError):
        decode_triage_batch_receipt_v1(encoded)


def test_schema_is_closed_and_exposes_only_receipt_fields() -> None:
    schema = triage_batch_receipt_v1_json_schema()

    assert schema["additionalProperties"] is False
    assert schema["properties"]["may_lower_security_decision"] == {"const": False}
    assert schema["properties"]["operational_authority"] == {"const": "none"}
    result_schema = schema["properties"]["results"]["items"]
    assert result_schema["additionalProperties"] is False
    forbidden = {"item", "decision", "exception", "prompt", "model_output"}
    assert forbidden.isdisjoint(result_schema["properties"])
