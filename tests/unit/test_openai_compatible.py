from __future__ import annotations

from pathlib import Path

import pytest

from historical_table_pipeline.config import load_profile
from historical_table_pipeline.providers.openai_compatible import (
    OcrProviderError,
    build_system_prompt,
    parse_response,
)


@pytest.fixture
def profile(tmp_path: Path):
    path = tmp_path / "profile.yaml"
    path.write_text(
        """profile_version: '1'
name: demo
record_type: entity
fields:
  - name: code
    required: true
  - name: value
""",
        encoding="utf-8",
    )
    return load_profile(path)


def test_prompt_is_derived_from_profile(profile) -> None:
    prompt = build_system_prompt(profile)
    assert '"code"' in prompt
    assert "leading zeroes" in prompt
    assert "convert currencies" in prompt


def test_parse_fenced_json_preserves_leading_zero(profile) -> None:
    rows = parse_response(
        '```json\n{"rows":[{"source_row_index":0,"cells":{"code":"017","value":"¥5"}}]}\n```',
        profile,
    )
    assert rows[0]["cells"]["code"] == "017"


def test_parse_rejects_undeclared_fields(profile) -> None:
    with pytest.raises(OcrProviderError, match="not declared"):
        parse_response('{"rows":[{"cells":{"other":"x"}}]}', profile)
