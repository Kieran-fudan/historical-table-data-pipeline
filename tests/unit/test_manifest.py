from __future__ import annotations

from pathlib import Path

from historical_table_pipeline.manifest import create_manifest


def test_run_identity_is_content_derived(tmp_path: Path) -> None:
    profile = tmp_path / "profile.yaml"
    source = tmp_path / "engine.jsonl"
    profile.write_text("demo", encoding="utf-8")
    source.write_text('{"row": 1}\n', encoding="utf-8")
    first = create_manifest(profile, [source], parameters={"mode": "strict"})
    second = create_manifest(profile, [source], parameters={"mode": "strict"})
    assert first.run_id == second.run_id
    assert first.created_at != ""
    source.write_text('{"row": 2}\n', encoding="utf-8")
    third = create_manifest(profile, [source], parameters={"mode": "strict"})
    assert third.run_id != first.run_id

    renamed = tmp_path / "renamed-engine.jsonl"
    renamed.write_text('{"row": 2}\n', encoding="utf-8")
    fourth = create_manifest(profile, [renamed], parameters={"mode": "strict"})
    assert fourth.run_id != third.run_id
