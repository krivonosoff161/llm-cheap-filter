"""Verify a closed release artifact set against PyPI-compatible JSON indexes."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import tarfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass
from email.parser import BytesParser
from pathlib import Path, PurePosixPath


@dataclass(frozen=True)
class Artifact:
    filename: str
    name: str
    version: str
    package_type: str
    sha256: str


def canonical_name(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).lower()


def _metadata_fields(payload: bytes) -> tuple[str, str]:
    message = BytesParser().parsebytes(payload)
    name = message.get("Name")
    version = message.get("Version")
    if not name or not version:
        raise ValueError("artifact metadata lacks Name or Version")
    return canonical_name(name), version


def inspect_artifact(path: Path) -> Artifact:
    if path.suffix == ".whl":
        with zipfile.ZipFile(path) as archive:
            names = [name for name in archive.namelist() if name.endswith(".dist-info/METADATA")]
            if len(names) != 1:
                raise ValueError(f"{path.name}: expected one wheel METADATA")
            name, version = _metadata_fields(archive.read(names[0]))
        package_type = "bdist_wheel"
    elif path.name.endswith(".tar.gz"):
        with tarfile.open(path, "r:gz") as archive:
            members = [
                member
                for member in archive.getmembers()
                if member.isfile()
                and len(PurePosixPath(member.name).parts) == 2
                and PurePosixPath(member.name).name == "PKG-INFO"
            ]
            if len(members) != 1:
                raise ValueError(f"{path.name}: expected one sdist PKG-INFO")
            stream = archive.extractfile(members[0])
            if stream is None:
                raise ValueError(f"{path.name}: cannot read PKG-INFO")
            name, version = _metadata_fields(stream.read())
        package_type = "sdist"
    else:
        raise ValueError(f"unsupported release artifact: {path.name}")
    return Artifact(
        filename=path.name,
        name=name,
        version=version,
        package_type=package_type,
        sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
    )


def inspect_release(dist_dir: Path, expected: tuple[str, ...]) -> tuple[Artifact, ...]:
    paths = sorted(
        path for path in dist_dir.iterdir()
        if path.is_file() and (path.suffix == ".whl" or path.name.endswith(".tar.gz"))
    )
    artifacts = tuple(inspect_artifact(path) for path in paths)
    expected_pairs = {
        (canonical_name(item.split("==", 1)[0]), item.split("==", 1)[1])
        for item in expected
    }
    observed_pairs = {(item.name, item.version) for item in artifacts}
    if observed_pairs != expected_pairs:
        raise ValueError(
            f"release identity mismatch: expected={sorted(expected_pairs)}, "
            f"observed={sorted(observed_pairs)}"
        )
    for pair in sorted(expected_pairs):
        types = {item.package_type for item in artifacts if (item.name, item.version) == pair}
        if types != {"bdist_wheel", "sdist"}:
            raise ValueError(f"{pair[0]}=={pair[1]} lacks wheel/sdist closure: {sorted(types)}")
    if len({item.filename for item in artifacts}) != len(artifacts):
        raise ValueError("duplicate artifact filename")
    return artifacts


def verify_index(
    artifacts: tuple[Artifact, ...],
    *,
    host: str,
    attempts: int,
    wait_seconds: float,
) -> None:
    if host not in {"pypi.org", "test.pypi.org"}:
        raise ValueError(f"unsupported package index host: {host!r}")
    grouped: dict[tuple[str, str], dict[str, str]] = {}
    for item in artifacts:
        grouped.setdefault((item.name, item.version), {})[item.filename] = item.sha256
    for (name, version), expected in sorted(grouped.items()):
        url = f"https://{host}/pypi/{urllib.parse.quote(name)}/{urllib.parse.quote(version)}/json"
        observed: dict[str, str] | None = None
        for attempt in range(1, attempts + 1):
            try:
                with urllib.request.urlopen(url, timeout=30) as response:  # nosec B310
                    payload = json.load(response)
                observed = {
                    item["filename"]: item["digests"]["sha256"]
                    for item in payload.get("urls", [])
                    if item.get("packagetype") in {"bdist_wheel", "sdist"}
                }
                if observed == expected:
                    break
            except urllib.error.HTTPError as exc:
                if exc.code != 404:
                    raise
            if attempt < attempts:
                time.sleep(wait_seconds)
        if observed != expected:
            raise ValueError(
                f"{host} mismatch for {name}=={version}: "
                f"expected={sorted(expected)}, observed={sorted(observed or {})}"
            )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dist-dir", type=Path, required=True)
    parser.add_argument("--expected", action="append", required=True)
    parser.add_argument("--host")
    parser.add_argument("--attempts", type=int, default=1)
    parser.add_argument("--wait-seconds", type=float, default=0)
    args = parser.parse_args()
    artifacts = inspect_release(args.dist_dir, tuple(args.expected))
    if args.host:
        verify_index(
            artifacts,
            host=args.host,
            attempts=args.attempts,
            wait_seconds=args.wait_seconds,
        )
    print(
        json.dumps(
            {
                "artifacts": [
                    {
                        "filename": item.filename,
                        "name": item.name,
                        "version": item.version,
                        "package_type": item.package_type,
                        "sha256": item.sha256,
                    }
                    for item in artifacts
                ],
                "host": args.host,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
