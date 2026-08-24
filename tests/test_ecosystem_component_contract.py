from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ROOT_KEYS = {
    "schema_version",
    "component_id",
    "display_name",
    "repository",
    "visibility",
    "kind",
    "summary",
    "package",
    "owns",
    "consumes",
    "contracts",
    "docs",
    "compatibility",
    "integration_status",
    "evidence_refs",
    "claims",
    "non_claims",
    "authority",
}
HISTORICAL = {
    "docs/security-portfolio-roadmap.md",
    "docs/security-portfolio-roadmap-public.yaml",
    "docs/security-portfolio-roadmap-contract.json",
}


def load_manifest() -> dict[str, object]:
    return json.loads((ROOT / "component.yaml").read_text(encoding="utf-8"))


def test_component_manifest_is_closed_and_truthful() -> None:
    manifest = load_manifest()
    assert set(manifest) == ROOT_KEYS
    assert manifest["schema_version"] == "AgenticSecurityEcosystemComponent.v1"
    assert manifest["component_id"] == "llm-cheap-filter"
    assert manifest["kind"] == "support_adapter"
    assert manifest["integration_status"] == "standalone"
    assert manifest["authority"] == "none"
    package = manifest["package"]
    assert package == {
        "name": "llm-cheap-filter",
        "version": "0.1.0",
        "install": "pip install -e .",
        "entry_points": [],
    }
    compatibility = manifest["compatibility"]
    assert isinstance(compatibility, dict)
    assert compatibility["python"] == ">=3.9"
    platforms = compatibility["platforms"]
    assert isinstance(platforms, dict)
    assert platforms == {
        "supported": ["linux", "windows"],
        "tested": ["linux", "windows"],
    }

    contracts = manifest["contracts"]
    assert isinstance(contracts, list)
    assert all(item["direction"] in {"provides", "consumes"} for item in contracts)
    assert {
        (item["id"], item["version"], item["direction"], item["required"])
        for item in contracts
    } == {
        ("component-manifest", "1", "consumes", False),
        ("triage-batch-receipt", "1.0", "provides", False),
    }


def test_document_roles_exist_and_preserve_historical_snapshots() -> None:
    manifest = load_manifest()
    docs = manifest["docs"]
    assert isinstance(docs, list)
    by_path = {item["path"]: item["role"] for item in docs}
    assert HISTORICAL <= set(by_path)
    assert all(by_path[path] == "historical" for path in HISTORICAL)
    assert all((ROOT / path).is_file() for path in by_path)
    assert all((ROOT / path).is_file() for path in manifest["evidence_refs"])


def test_front_door_keeps_support_boundary_explicit() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    roadmap = (ROOT / "docs" / "component-roadmap.md").read_text(encoding="utf-8")
    assert "docs/component-roadmap.md" in readme
    assert "agentic-security-harness/blob/main/docs/ecosystem-roadmap.md" in readme
    assert "standalone support adapter" in readme
    assert "Linux and Windows are both supported and tested" in roadmap
    non_claims = set(load_manifest()["non_claims"])
    assert {"security control", "correctness oracle", "trust source"} <= non_claims
