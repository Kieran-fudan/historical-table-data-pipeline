from __future__ import annotations

from pathlib import Path

import pytest

from historical_table_pipeline.config import ProfileError, load_profile


def test_load_minimal_profile(tmp_path: Path) -> None:
    path = tmp_path / "profile.yaml"
    path.write_text(
        """profile_version: '1'
name: demo
record_type: entity
fields:
  - name: item
    required: true
""",
        encoding="utf-8",
    )
    profile = load_profile(path)
    assert profile.name == "demo"
    assert profile.field_names == ("item",)
    assert profile.expected_sources == 2


def test_reject_duplicate_fields(tmp_path: Path) -> None:
    path = tmp_path / "profile.yaml"
    path.write_text(
        """profile_version: '1'
name: demo
record_type: entity
fields:
  - name: item
  - name: item
""",
        encoding="utf-8",
    )
    with pytest.raises(ProfileError, match="Duplicate"):
        load_profile(path)
