#!/usr/bin/env python3
"""Fail CI when a public release contains likely credentials or private artifacts."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

IGNORED_DIRS = {".git", ".venv", "__pycache__", ".pytest_cache", ".ruff_cache"}
BINARY_SUFFIXES = {
    ".7z",
    ".docx",
    ".jpeg",
    ".jpg",
    ".mp4",
    ".pdf",
    ".png",
    ".tif",
    ".tiff",
    ".xls",
    ".xlsx",
    ".zip",
}
SECRET_PATTERNS = {
    "generic API key": re.compile(
        r"(?i)(?:api[_-]?key|secret|token)\s*[:=]\s*['\"]?[A-Za-z0-9_\-]{20,}"
    ),
    "OpenAI-style key": re.compile(r"\bsk-[A-Za-z0-9_\-]{20,}\b"),
    "GitHub token": re.compile(r"\b(?:ghp|github_pat)_[A-Za-z0-9_]{20,}\b"),
    "private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
}
LOCAL_PATH_PATTERNS = {
    "Windows user path": re.compile(r"[A-Za-z]:\\Users\\[^\\\s]+", re.IGNORECASE),
    "POSIX home path": re.compile(r"/(?:Users|home)/[^/\s]+/"),
}


def iter_files(root: Path):
    for path in root.rglob("*"):
        if any(
            part in IGNORED_DIRS
            or part.endswith("venv")
            or part.startswith(".venv-")
            for part in path.parts
        ):
            continue
        if path.is_file():
            yield path


def scan(root: Path) -> list[str]:
    findings: list[str] = []
    for path in iter_files(root):
        relative = path.relative_to(root).as_posix()
        lowered = path.name.lower()
        if lowered == ".env" or (
            lowered.startswith(".env.") and lowered != ".env.example"
        ):
            findings.append(f"credential file is not publishable: {relative}")
        if lowered == "settings.local.json":
            findings.append(f"local agent permissions are not publishable: {relative}")
        if path.stat().st_size > 10 * 1024 * 1024:
            findings.append(f"file exceeds 10 MiB public-repo limit: {relative}")
        if path.suffix.lower() in BINARY_SUFFIXES and not relative.startswith(
            "examples/synthetic/"
        ):
            findings.append(f"unreviewed binary/source artifact: {relative}")
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if relative == ".env.example":
            continue
        for label, pattern in SECRET_PATTERNS.items():
            if pattern.search(text):
                findings.append(f"possible {label}: {relative}")
        for label, pattern in LOCAL_PATH_PATTERNS.items():
            if pattern.search(text):
                findings.append(f"possible {label}: {relative}")
    return sorted(set(findings))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", nargs="?", default=".")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    findings = scan(root)
    if findings:
        print("Public repository check failed:", file=sys.stderr)
        for finding in findings:
            print(f"- {finding}", file=sys.stderr)
        return 1
    print("Public repository check passed: no likely secrets or private artifacts found.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
