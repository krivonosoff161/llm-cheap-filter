from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_agent_contract_keeps_portfolio_authority_bounded() -> None:
    text = " ".join((ROOT / "AGENTS.md").read_text(encoding="utf-8").split())
    for phrase in ("main", "codex/*", "never weaken", "separate owner gates", "grant no authority"):
        assert phrase in text
