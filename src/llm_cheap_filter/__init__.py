# -*- coding: utf-8 -*-
"""llm-cheap-filter — deterministic pre-filter + cheap→chief escalation pipeline."""
from .analysis import CalibrationPoint, SavingsReport, build_savings_report, calibrate_thresholds
from .pipeline import CheapCall, ChiefCall, ItemResult, Pipeline, Report
from .policy import CHEAP, CHIEF, DROP, EscalationPolicy
from .prefilter import PreFilter, PreVerdict
from .receipt import (
    TRIAGE_BATCH_RECEIPT_V1,
    TriageBatchReceiptV1,
    TriageReceiptContractError,
    TriageReceiptResultV1,
    TriageReceiptSummaryV1,
    build_triage_batch_receipt_v1,
    decode_triage_batch_receipt_v1,
    encode_triage_batch_receipt_v1,
    escalation_policy_sha256,
    prefilter_configuration_sha256,
    triage_batch_receipt_v1_json_schema,
)

__all__ = [
    "PreFilter", "PreVerdict",
    "EscalationPolicy", "DROP", "CHEAP", "CHIEF",
    "Pipeline", "ItemResult", "Report", "CheapCall", "ChiefCall",
    "SavingsReport", "CalibrationPoint", "build_savings_report", "calibrate_thresholds",
    "TRIAGE_BATCH_RECEIPT_V1", "TriageBatchReceiptV1", "TriageReceiptResultV1",
    "TriageReceiptSummaryV1", "TriageReceiptContractError",
    "build_triage_batch_receipt_v1", "encode_triage_batch_receipt_v1",
    "decode_triage_batch_receipt_v1", "triage_batch_receipt_v1_json_schema",
    "prefilter_configuration_sha256", "escalation_policy_sha256",
]
__version__ = "0.2.0"
