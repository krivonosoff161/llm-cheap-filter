from __future__ import annotations

from pathlib import Path

import llm_cheap_filter


ROOT = Path(__file__).resolve().parents[1]


def test_distribution_coordinate_and_version_are_exact() -> None:
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'name = "llm-cheap-filter"' in pyproject
    assert 'version = "0.2.0"' in pyproject
    assert "dependencies = []" in pyproject
    assert llm_cheap_filter.__version__ == "0.2.0"


def test_package_declares_no_automatic_harness_entry_point() -> None:
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert "[project.entry-points" not in pyproject
    source = (ROOT / "src" / "llm_cheap_filter" / "__init__.py").read_text(
        encoding="utf-8"
    )
    assert "subprocess" not in source
    assert "socket" not in source
