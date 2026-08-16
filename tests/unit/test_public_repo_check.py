from __future__ import annotations

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_public_repo.py"
SPEC = importlib.util.spec_from_file_location("check_public_repo", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def test_finds_secret_and_local_settings(tmp_path: Path) -> None:
    synthetic_secret = "api_" + "key=" + "abcdefghijklmnopqrstuv"
    (tmp_path / "leak.txt").write_text(synthetic_secret, encoding="utf-8")
    (tmp_path / "settings.local.json").write_text("{}", encoding="utf-8")
    findings = MODULE.scan(tmp_path)
    assert any("API key" in finding for finding in findings)
    assert any("permissions" in finding for finding in findings)


def test_placeholder_env_is_allowed(tmp_path: Path) -> None:
    (tmp_path / ".env.example").write_text("OPENAI_API_KEY=\n", encoding="utf-8")
    assert MODULE.scan(tmp_path) == []
