"""Small deterministic I/O helpers used by every pipeline stage."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import tempfile
from collections.abc import Iterable, Iterator, Mapping, Sequence
from contextlib import suppress
from pathlib import Path
from typing import Any


class DataContractError(ValueError):
    """Raised when a JSONL/CSV artifact violates the public contract."""


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_file(path: str | Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def read_jsonl(path: str | Path) -> Iterator[dict[str, Any]]:
    artifact = Path(path)
    with artifact.open("r", encoding="utf-8-sig") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise DataContractError(f"{artifact}:{line_number}: invalid JSON: {exc}") from exc
            if not isinstance(value, dict):
                raise DataContractError(f"{artifact}:{line_number}: expected a JSON object")
            yield value


def read_csv(path: str | Path) -> Iterator[dict[str, str]]:
    artifact = Path(path)
    with artifact.open("r", encoding="utf-8-sig", newline="") as handle:
        yield from csv.DictReader(handle)


def _atomic_text_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent, text=True
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    except BaseException:
        with suppress(FileNotFoundError):
            os.unlink(temporary_name)
        raise


def write_json(path: str | Path, value: Any, *, pretty: bool = True) -> Path:
    artifact = Path(path)
    if pretty:
        text = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    else:
        text = canonical_json(value) + "\n"
    _atomic_text_write(artifact, text)
    return artifact


def write_jsonl(path: str | Path, rows: Iterable[Mapping[str, Any]]) -> Path:
    artifact = Path(path)
    text = "".join(canonical_json(dict(row)) + "\n" for row in rows)
    _atomic_text_write(artifact, text)
    return artifact


def write_csv(
    path: str | Path,
    rows: Iterable[Mapping[str, Any]],
    fieldnames: Sequence[str],
) -> Path:
    artifact = Path(path)
    artifact.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{artifact.name}.", suffix=".tmp", dir=artifact.parent, text=True
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, artifact)
    except BaseException:
        with suppress(FileNotFoundError):
            os.unlink(temporary_name)
        raise
    return artifact
