"""Generate or verify the content-bound triage receipt V1 artifacts."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from llm_cheap_filter.receipt import triage_batch_receipt_v1_json_schema  # noqa: E402


SCHEMA_PATH = Path("schemas/triage-batch-receipt.v1.schema.json")
MANIFEST_PATH = Path("schemas/triage-batch-receipt.v1.manifest.json")
BOUND_FILES = (
    Path("src/llm_cheap_filter/receipt.py"),
    Path("src/llm_cheap_filter/commitments.py"),
    Path("src/llm_cheap_filter/__init__.py"),
    Path("src/llm_cheap_filter/analysis.py"),
    Path("src/llm_cheap_filter/pipeline.py"),
    Path("src/llm_cheap_filter/policy.py"),
    Path("src/llm_cheap_filter/prefilter.py"),
    Path("tests/test_triage_receipt.py"),
    Path("tests/conftest.py"),
    Path("tests/test_analysis.py"),
    Path("tests/test_pipeline.py"),
    Path("docs/triage-batch-receipt.md"),
    Path("README.md"),
    Path("component.yaml"),
    Path(".github/workflows/tests.yml"),
    Path("tools/triage_receipt_contracts.py"),
)


def _json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    ).encode("utf-8")


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _lf_normalized_sha256(path: Path) -> str:
    payload = _lf_normalized_bytes(path.read_bytes(), path.as_posix())
    return _sha256(payload)


def _lf_normalized_bytes(payload: bytes, label: str) -> bytes:
    payload = payload.replace(b"\r\n", b"\n")
    if b"\r" in payload:
        raise ValueError(f"bare carriage return in {label}")
    return payload


def expected_artifacts() -> dict[Path, bytes]:
    schema_bytes = _json_bytes(triage_batch_receipt_v1_json_schema())
    files = {
        path.as_posix(): _lf_normalized_sha256(ROOT / path) for path in BOUND_FILES
    }
    manifest = {
        "schema_version": "llm-cheap-filter-contract-manifest-v1.0",
        "contract_id": "triage-batch-receipt",
        "contract_version": "1.0",
        "generator": "tools/triage_receipt_contracts.py",
        "artifacts": {SCHEMA_PATH.as_posix(): _sha256(schema_bytes)},
        "bound_files": files,
        "bound_file_digest_semantics": "sha256_lf_normalized_text_v1",
        "verdict_semantics": "triage_accounting_only_no_security_verdict",
        "may_lower_security_decision": False,
        "operational_authority": "none",
    }
    return {SCHEMA_PATH: schema_bytes, MANIFEST_PATH: _json_bytes(manifest)}


def generate() -> int:
    for path, payload in expected_artifacts().items():
        target = ROOT / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
    return 0


def check() -> int:
    failed = False
    for path, expected in expected_artifacts().items():
        target = ROOT / path
        if not target.is_file() or _lf_normalized_bytes(
            target.read_bytes(), path.as_posix()
        ) != expected:
            print(f"drift: {path.as_posix()}")
            failed = True
    return 1 if failed else 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("generate", "check"))
    args = parser.parse_args()
    return generate() if args.command == "generate" else check()


if __name__ == "__main__":
    raise SystemExit(main())
