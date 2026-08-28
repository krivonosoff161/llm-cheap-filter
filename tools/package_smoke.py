"""Verify the exact Cheap Filter wheel/sdist and isolated installed import."""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path


EXPECTED_WHEEL = "llm_cheap_filter-0.2.0-py3-none-any.whl"
EXPECTED_SDIST = "llm_cheap_filter-0.2.0.tar.gz"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("dist", type=Path)
    dist = parser.parse_args().dist.resolve()
    wheel = dist / EXPECTED_WHEEL
    sdist = dist / EXPECTED_SDIST
    if not wheel.is_file() or not sdist.is_file():
        raise SystemExit("exact Cheap Filter wheel/sdist set is missing")
    artifacts = sorted(path.name for path in dist.iterdir() if path.is_file())
    if artifacts != sorted([EXPECTED_SDIST, EXPECTED_WHEEL]):
        raise SystemExit(f"unexpected dist artifact set: {artifacts}")
    with zipfile.ZipFile(wheel) as archive:
        names = set(archive.namelist())
        metadata_name = next(
            name for name in names if name.endswith(".dist-info/METADATA")
        )
        metadata = archive.read(metadata_name).decode("utf-8")
    required = {
        "llm_cheap_filter/__init__.py",
        "llm_cheap_filter/pipeline.py",
        "llm_cheap_filter/receipt.py",
        "llm_cheap_filter/py.typed",
    }
    if not required <= names:
        raise SystemExit("Cheap Filter wheel is missing its public package surface")
    if any(name.endswith("entry_points.txt") for name in names):
        raise SystemExit("Cheap Filter base package unexpectedly declares an entry point")
    requirements = [
        line for line in metadata.splitlines() if line.startswith("Requires-Dist:")
    ]
    if any('extra == "dev"' not in line for line in requirements):
        raise SystemExit("zero-runtime-dependency wheel declares a dependency")
    with tempfile.TemporaryDirectory() as temporary:
        target = Path(temporary) / "site"
        subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                "--no-deps",
                "--no-compile",
                "--target",
                str(target),
                str(wheel),
            ],
            check=True,
        )
        subprocess.run(
            [
                sys.executable,
                "-I",
                "-c",
                (
                    "import sys;sys.path.insert(0,sys.argv[1]);"
                    "import llm_cheap_filter as p;"
                    "assert p.__version__=='0.2.0';"
                    "assert p.TRIAGE_BATCH_RECEIPT_V1=="
                    "'llm-cheap-filter-triage-batch-receipt-v1.0'"
                ),
                str(target),
            ],
            check=True,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
