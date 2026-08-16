"""Content-derived run identities and provenance manifests."""

from __future__ import annotations

import hashlib
import platform
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from historical_table_pipeline import __version__
from historical_table_pipeline.io import canonical_json, sha256_file, write_json


@dataclass(frozen=True, slots=True)
class InputArtifact:
    path: str
    sha256: str
    size_bytes: int


@dataclass(frozen=True, slots=True)
class RunManifest:
    schema_version: str
    run_id: str
    created_at: str
    tool_version: str
    profile: InputArtifact
    inputs: tuple[InputArtifact, ...]
    python_version: str
    platform: str
    parameters: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def describe_artifact(path: str | Path, *, relative_to: Path | None = None) -> InputArtifact:
    artifact = Path(path).expanduser().resolve()
    display = artifact
    if relative_to is not None:
        try:
            display = artifact.relative_to(relative_to.resolve())
        except ValueError:
            display = Path(artifact.name)
    return InputArtifact(
        path=display.as_posix(),
        sha256=sha256_file(artifact),
        size_bytes=artifact.stat().st_size,
    )


def create_manifest(
    profile_path: str | Path,
    input_paths: list[str | Path],
    *,
    parameters: dict[str, Any] | None = None,
    relative_to: str | Path | None = None,
) -> RunManifest:
    root = Path(relative_to).resolve() if relative_to is not None else None
    profile = describe_artifact(profile_path, relative_to=root)
    inputs = tuple(
        sorted(
            (describe_artifact(path, relative_to=root) for path in input_paths),
            key=lambda item: (item.sha256, item.path),
        )
    )
    normalized_parameters = parameters or {}
    identity = {
        "schema_version": "1",
        "tool_version": __version__,
        "profile_sha256": profile.sha256,
        "inputs": [
            {"source_name": Path(item.path).name, "sha256": item.sha256}
            for item in inputs
        ],
        "parameters": normalized_parameters,
    }
    run_id = hashlib.sha256(canonical_json(identity).encode("utf-8")).hexdigest()[:16]
    return RunManifest(
        schema_version="1",
        run_id=run_id,
        created_at=datetime.now(UTC).isoformat(),
        tool_version=__version__,
        profile=profile,
        inputs=inputs,
        python_version=sys.version.split()[0],
        platform=platform.platform(),
        parameters=normalized_parameters,
    )


def write_manifest(path: str | Path, manifest: RunManifest) -> Path:
    return write_json(path, manifest.to_dict())
