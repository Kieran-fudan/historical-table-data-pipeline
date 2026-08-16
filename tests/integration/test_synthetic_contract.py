from __future__ import annotations

import json
import math
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
PROFILE_TEMPLATE = ROOT / "profiles" / "template.yaml"
EXAMPLE_PROFILE = ROOT / "profiles" / "example-records.yaml"
FIXTURE = ROOT / "examples" / "synthetic"

ROW_REQUIRED_KEYS = {
    "document_id",
    "page_id",
    "source_pdf_page_index",
    "printed_page_label",
    "table_id",
    "engine_id",
    "engine_version",
    "source_row_index",
    "cells",
}
FIELD_REQUIRED_KEYS = {"name", "label", "type", "required"}
CONSENSUS_STATUSES = {"unanimous", "majority", "conflict", "missing"}
EXAMPLE_FIELDS = {
    "item_name",
    "catalog_code",
    "category",
    "location",
    "organization",
    "recorded_date",
    "quantity",
    "quantity_unit",
    "description",
    "amount_text",
    "amount_unit_text",
    "note",
}
def _load_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict), f"{path} must contain one YAML mapping"
    return value


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        value = json.loads(line)
        assert isinstance(value, dict), f"{path}:{line_number} must be a JSON object"
        rows.append(value)
    return rows


def _row_key(row: dict[str, Any]) -> tuple[str, str, str, int]:
    return (
        row["document_id"],
        row["page_id"],
        row["table_id"],
        row["source_row_index"],
    )


def _fixture_parts() -> tuple[
    dict[str, Any],
    dict[str, Any],
    dict[str, list[dict[str, Any]]],
]:
    manifest = _load_yaml(FIXTURE / "manifest.yaml")
    profile = _load_yaml(EXAMPLE_PROFILE)
    rows_by_engine = {
        item["engine_id"]: _load_jsonl(FIXTURE / item["path"])
        for item in manifest["engines"]
    }
    return manifest, profile, rows_by_engine


def test_profiles_make_scope_parser_and_provenance_explicit() -> None:
    for path in (PROFILE_TEMPLATE, EXAMPLE_PROFILE):
        profile = _load_yaml(path)
        assert profile["profile_schema_version"] == "1.0"
        assert profile["profile_id"]
        assert profile["profile_version"]
        assert profile["name"]
        assert profile["record_type"]

        fields = profile["fields"]
        assert fields
        assert all(item.keys() >= FIELD_REQUIRED_KEYS for item in fields)
        field_names = {item["name"] for item in fields}
        assert len(field_names) == len(fields)
        assert all(item["preserve_raw"] is True for item in fields)
        assert all(item["standardized_name"] for item in fields)

        page_identity = profile["page_identity"]
        assert page_identity["source_pdf_page_index"]["base"] == 0
        assert page_identity["source_pdf_page_index"]["immutable"] is True
        assert page_identity["printed_page_label"]["nullable"] is True
        assert page_identity["table_id"]["required"] is True
        assert page_identity["renumber_after_filtering"] is False

        assert profile["parser"]["kind"] == "record_table"
        matrix = profile["parser"]["matrix_tables"]
        assert matrix["supported"] is False
        assert matrix["required_parser"] == "matrix_observation"

        required_keys = set(profile["ocr"]["row_jsonl_contract"]["required_keys"])
        assert required_keys == ROW_REQUIRED_KEYS
        assert profile["ocr"]["minimum_independent_engines"] >= 2
        assert profile["consensus"]["expected_sources"] >= 2
        assert set(profile["consensus"]["statuses"]) == CONSENSUS_STATUSES

        anchors = set(profile["alignment"]["anchor_fields"])
        weights = profile["alignment"]["weights"]
        assert "anchor_engine" in profile["alignment"]
        assert anchors <= field_names
        assert set(weights) <= field_names
        assert all(weight >= 0 for weight in weights.values())
        assert math.isclose(sum(weights.values()), 1.0, abs_tol=1e-12)

    example = _load_yaml(EXAMPLE_PROFILE)
    assert example["profile_id"] == "example-records"
    assert example["record_type"] == "generic_record"
    assert {item["name"] for item in example["fields"]} == EXAMPLE_FIELDS
    semantic_roles = {
        item.get("semantic_role") for item in example["fields"] if item.get("semantic_role")
    }
    assert {"label", "date", "quantity", "quantity_unit", "amount", "amount_unit"} <= (
        semantic_roles
    )


def test_synthetic_input_obeys_row_and_page_contract() -> None:
    manifest, profile, rows_by_engine = _fixture_parts()
    assert manifest["synthetic"] is True
    assert len(rows_by_engine) == 2
    assert sorted(len(rows) for rows in rows_by_engine.values()) == [4, 5]

    field_names = {item["name"] for item in profile["fields"]}
    manifest_pages = {item["page_id"]: item for item in manifest["pages"]}
    versions = {
        item["engine_id"]: item["engine_version"] for item in manifest["engines"]
    }

    for engine_id, rows in rows_by_engine.items():
        seen: set[tuple[str, str, str, int]] = set()
        for row in rows:
            assert row.keys() >= ROW_REQUIRED_KEYS
            assert row["engine_id"] == engine_id
            assert row["engine_version"] == versions[engine_id]
            assert type(row["source_pdf_page_index"]) is int
            assert row["source_pdf_page_index"] >= 0
            assert type(row["source_row_index"]) is int
            assert row["source_row_index"] >= 0
            assert row["printed_page_label"] is None or isinstance(
                row["printed_page_label"], str
            )
            assert set(row["cells"]) == field_names == EXAMPLE_FIELDS
            assert all(
                value is None or isinstance(value, (str, int, float, bool))
                for value in row["cells"].values()
            )

            page = manifest_pages[row["page_id"]]
            assert row["source_pdf_page_index"] == page["source_pdf_page_index"]
            assert row["printed_page_label"] == page["printed_page_label"]
            assert row["table_id"] == page["table_id"]
            assert _row_key(row) not in seen
            seen.add(_row_key(row))


def test_synthetic_scenarios_cover_agreement_conflict_omission_and_repeat() -> None:
    _, profile, rows_by_engine = _fixture_parts()
    grouped: dict[tuple[str, str, str, int], list[dict[str, Any]]] = defaultdict(list)
    for rows in rows_by_engine.values():
        for row in rows:
            grouped[_row_key(row)].append(row)

    assert len(grouped) == 5
    assert sum(len(rows) == 1 for rows in grouped.values()) == 1
    assert any(len(rows) == 2 and rows[0]["cells"] == rows[1]["cells"] for rows in grouped.values())

    repeat_values = set(profile["repeat_markers"]["values"])
    repeat_cells = [
        value
        for rows in rows_by_engine.values()
        for row in rows
        for value in row["cells"].values()
        if value in repeat_values
    ]
    assert len(repeat_cells) == 6

    semantic_conflicts: list[str] = []
    for rows in grouped.values():
        if len(rows) != 2:
            continue
        for field_name in EXAMPLE_FIELDS:
            values = {row["cells"][field_name] for row in rows}
            if len(values) > 1 and not values <= repeat_values:
                semantic_conflicts.append(field_name)
    assert semantic_conflicts == ["item_name"]


def test_workflow_decisions_are_approved_and_referential() -> None:
    decisions = _load_jsonl(FIXTURE / "decisions" / "reconciliation.jsonl")
    assert len(decisions) == 3
    assert len({item["decision_id"] for item in decisions}) == 3
    assert {item["decision_type"] for item in decisions} == {
        "choose_candidate",
        "accept_single_source_row",
        "resolve_repeat_marker",
    }
    assert all(item["status"] == "approved" for item in decisions)
    assert all(item["rationale"] for item in decisions)
    for item in decisions:
        assert item["target"].keys() >= {
            "document_id",
            "page_id",
            "table_id",
            "source_row_index",
        }


def test_synthetic_tree_contains_no_source_binary_personal_path_or_source_fingerprint() -> None:
    manifest = _load_yaml(FIXTURE / "manifest.yaml")
    declared_paths = [manifest["profile"], manifest["decisions"]]
    declared_paths.extend(item["path"] for item in manifest["engines"])
    declared_paths.extend(manifest.get("expected", {}).values())
    assert all(not Path(path).is_absolute() for path in declared_paths)

    forbidden_suffixes = {".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff"}
    personal_path = re.compile(r"(?:[A-Za-z]:\\Users\\|/(?:Users|home)/)")
    cjk_text = re.compile(r"[\u3400-\u9fff]")
    checked_files = [path for path in FIXTURE.rglob("*") if path.is_file()]
    checked_files.append(EXAMPLE_PROFILE)
    for path in checked_files:
        assert path.suffix.lower() not in forbidden_suffixes
        text = path.read_text(encoding="utf-8")
        assert personal_path.search(text) is None
        assert cjk_text.search(text) is None
