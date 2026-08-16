from __future__ import annotations

import copy
from collections import Counter
from dataclasses import replace
from functools import lru_cache
from typing import Any

import pytest

from historical_table_pipeline.alignment import AlignmentConfig
from historical_table_pipeline.consensus import ConsensusConfig, reconcile_sources
from historical_table_pipeline.decision_compiler import (
    DecisionCompileError,
    compile_workflow_decisions,
)
from historical_table_pipeline.models import ConsensusRecord, stable_cell_id
from historical_table_pipeline.review import apply_decisions

DECIDED_AT = "2020-01-01T00:00:00Z"
FIELDS = (
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
)


def _row(
    engine_id: str,
    page_number: int,
    source_row_index: int,
    **updates: str,
) -> dict[str, Any]:
    cells = {
        "item_name": f"Archive item {page_number}-{source_row_index}",
        "catalog_code": f"ARC-{page_number}{source_row_index}",
        "category": "Register",
        "location": "Vault North",
        "organization": "Aster Archive",
        "recorded_date": f"200{page_number}.{source_row_index + 1}",
        "quantity": "1",
        "quantity_unit": "folder",
        "description": "Fictional catalog entry",
        "amount_text": "CR 12",
        "amount_unit_text": "CR",
        "note": "",
    }
    cells.update(updates)
    return {
        "document_id": "fictional-archive",
        "page_id": f"page-{page_number}",
        "source_pdf_page_index": page_number - 1,
        "printed_page_label": str(page_number),
        "table_id": f"table-{page_number}",
        "engine_id": engine_id,
        "engine_version": "fixture-1",
        "source_row_index": source_row_index,
        "cells": cells,
    }


@lru_cache(maxsize=1)
def _records() -> tuple[ConsensusRecord, ...]:
    alpha = [
        _row(
            "ocr-alpha",
            1,
            0,
            item_name="Aurora Index",
            catalog_code="ARC-100",
            location="Vault North",
            organization="Aster Archive",
        ),
        _row(
            "ocr-alpha",
            1,
            1,
            item_name="SAME-AS-ABOVE",
            catalog_code="ARC-101",
            location="SAME-AS-ABOVE",
            organization="SAME-AS-ABOVE",
        ),
        _row(
            "ocr-alpha",
            1,
            2,
            item_name="Cedar Ledger",
            catalog_code="ARC-102",
        ),
        _row(
            "ocr-alpha",
            2,
            0,
            item_name="Harbor Notes",
            catalog_code="ARC-200",
        ),
        _row(
            "ocr-alpha",
            2,
            1,
            item_name="Meadow List",
            catalog_code="ARC-201",
        ),
    ]
    beta = [
        _row(
            "ocr-beta",
            1,
            0,
            item_name="Aurora Index",
            catalog_code="ARC-100",
            location="Vault North",
            organization="Aster Archive",
        ),
        _row(
            "ocr-beta",
            1,
            1,
            item_name="DITTO",
            catalog_code="ARC-101",
            location="DITTO",
            organization="DITTO",
        ),
        _row(
            "ocr-beta",
            1,
            2,
            item_name="Ceder Ledger",
            catalog_code="ARC-102",
        ),
        _row(
            "ocr-beta",
            2,
            1,
            item_name="Meadow List",
            catalog_code="ARC-201",
        ),
    ]
    records = reconcile_sources(
        {"ocr-alpha": alpha, "ocr-beta": beta},
        alignment_config=AlignmentConfig(
            anchor_engine="ocr-alpha",
            field_weights={"item_name": 0.2, "catalog_code": 0.8},
            minimum_match_similarity=0.7,
        ),
        consensus_config=ConsensusConfig(fields=FIELDS),
    )
    assert len(records) == 5
    return tuple(records)


def _events() -> list[dict[str, Any]]:
    return [
        {
            "decision_id": "fixture-decision-001",
            "decision_type": "choose_candidate",
            "target": {
                "document_id": "fictional-archive",
                "page_id": "page-1",
                "table_id": "table-1",
                "source_row_index": 2,
                "field_name": "item_name",
            },
            "chosen": {
                "raw": "Cedar Ledger",
                "std": "Cedar Ledger",
                "engine_id": "ocr-alpha",
            },
            "evidence": {
                "candidate_values": ["Cedar Ledger", "Ceder Ledger"],
                "engine_ids": ["ocr-alpha", "ocr-beta"],
            },
            "rationale": "The fictional review card selects the first spelling.",
            "reviewer_kind": "fixture_reviewer",
            "status": "approved",
        },
        {
            "decision_id": "fixture-decision-002",
            "decision_type": "accept_single_source_row",
            "target": {
                "document_id": "fictional-archive",
                "page_id": "page-2",
                "table_id": "table-2",
                "source_row_index": 0,
            },
            "chosen": {"engine_id": "ocr-alpha"},
            "evidence": {
                "present_engines": ["ocr-alpha"],
                "missing_engines": ["ocr-beta"],
            },
            "rationale": "The fictional review card confirms the single-source row.",
            "reviewer_kind": "fixture_reviewer",
            "status": "approved",
        },
        {
            "decision_id": "fixture-decision-003",
            "decision_type": "resolve_repeat_marker",
            "target": {
                "document_id": "fictional-archive",
                "page_id": "page-1",
                "table_id": "table-1",
                "source_row_index": 1,
                "field_names": ["item_name", "location", "organization"],
            },
            "chosen": {
                "item_name": {
                    "raw_by_engine": {
                        "ocr-alpha": "SAME-AS-ABOVE",
                        "ocr-beta": "DITTO",
                    },
                    "std": "Aurora Index",
                },
                "location": {
                    "raw_by_engine": {
                        "ocr-alpha": "SAME-AS-ABOVE",
                        "ocr-beta": "DITTO",
                    },
                    "std": "Vault North",
                },
                "organization": {
                    "raw_by_engine": {
                        "ocr-alpha": "SAME-AS-ABOVE",
                        "ocr-beta": "DITTO",
                    },
                    "std": "Aster Archive",
                },
            },
            "evidence": {
                "inherits_from_source_row_index": 0,
                "same_table_only": True,
            },
            "rationale": "The fictional markers inherit from the preceding row.",
            "reviewer_kind": "fixture_reviewer",
            "status": "approved",
        },
    ]


def test_compile_fixture_workflow_into_replayable_cell_decisions() -> None:
    records = _records()
    decisions = compile_workflow_decisions(
        records,
        _events(),
        default_decided_at=DECIDED_AT,
    )

    assert len(decisions) == 16
    assert len({decision.decision_id for decision in decisions}) == 16
    assert len({decision.cell_id for decision in decisions}) == 16
    assert Counter(decision.metadata["source_decision_id"] for decision in decisions) == {
        "fixture-decision-001": 1,
        "fixture-decision-002": 12,
        "fixture-decision-003": 3,
    }
    assert all(decision.reviewer == "fixture_reviewer" for decision in decisions)
    assert all(decision.decided_at == DECIDED_AT for decision in decisions)

    selected = next(
        item
        for item in decisions
        if item.metadata["source_decision_id"] == "fixture-decision-001"
    )
    assert selected.chosen_value == "Cedar Ledger"
    assert selected.candidate_id is not None

    accepted = [
        item
        for item in decisions
        if item.metadata["source_decision_id"] == "fixture-decision-002"
    ]
    single_source_record = next(
        record
        for record in records
        if record.page_id == "page-2"
        and any(source.source_row_index == 0 for source in record.sources)
    )
    expected_missing_cells = {
        cell.cell_id for cell in single_source_record.cells.values() if not cell.is_resolved
    }
    assert {item.cell_id for item in accepted} == expected_missing_cells

    repeat = [
        item
        for item in decisions
        if item.metadata["source_decision_id"] == "fixture-decision-003"
    ]
    assert {item.chosen_value for item in repeat} == {
        "Aurora Index",
        "Vault North",
        "Aster Archive",
    }
    assert all(item.candidate_id is None for item in repeat)

    applied = apply_decisions(records, decisions)
    applied_by_cell = {
        cell.cell_id: cell
        for record in applied
        for cell in record.cells.values()
        if cell.decision is not None
    }
    assert set(applied_by_cell) == {decision.cell_id for decision in decisions}
    assert all(
        applied_by_cell[item.cell_id].chosen_value == item.chosen_value
        for item in decisions
    )


def test_compile_accepts_lossless_consensus_dicts() -> None:
    serialized = [record.to_dict() for record in _records()]
    decisions = compile_workflow_decisions(
        serialized,
        _events(),
        default_decided_at=DECIDED_AT,
    )
    assert len(decisions) == 16


def test_compile_requires_explicit_decision_time() -> None:
    with pytest.raises(DecisionCompileError, match="requires decided_at"):
        compile_workflow_decisions(_records(), _events())


def test_compile_rejects_unknown_and_ambiguous_long_key_targets() -> None:
    unknown = [_events()[0]]
    unknown[0]["target"]["source_row_index"] = 99
    with pytest.raises(DecisionCompileError, match="unknown target"):
        compile_workflow_decisions(_records(), unknown, default_decided_at=DECIDED_AT)

    short_alias = [_events()[0]]
    short_alias[0]["target"]["document"] = short_alias[0]["target"].pop("document_id")
    with pytest.raises(DecisionCompileError, match="document_id is required"):
        compile_workflow_decisions(_records(), short_alias, default_decided_at=DECIDED_AT)

    source = _records()[2]
    clone_id = "fixture-ambiguous-record"
    clone = replace(
        source,
        record_id=clone_id,
        cells={
            name: replace(cell, cell_id=stable_cell_id(clone_id, name))
            for name, cell in source.cells.items()
        },
    )
    with pytest.raises(DecisionCompileError, match="ambiguous"):
        compile_workflow_decisions(
            (*_records(), clone),
            [_events()[0]],
            default_decided_at=DECIDED_AT,
        )


def test_compile_rejects_candidate_and_reported_evidence_mismatches() -> None:
    wrong_raw = [_events()[0]]
    wrong_raw[0]["chosen"]["raw"] = "Absent fictional value"
    with pytest.raises(DecisionCompileError, match="evidence mismatch"):
        compile_workflow_decisions(_records(), wrong_raw, default_decided_at=DECIDED_AT)

    wrong_candidates = [_events()[0]]
    wrong_candidates[0]["evidence"]["candidate_values"] = ["Cedar Ledger"]
    with pytest.raises(DecisionCompileError, match="does not match consensus evidence"):
        compile_workflow_decisions(
            _records(), wrong_candidates, default_decided_at=DECIDED_AT
        )

    wrong_missing_engine = [_events()[1]]
    wrong_missing_engine[0]["evidence"]["missing_engines"] = ["ocr-gamma"]
    with pytest.raises(DecisionCompileError, match="does not match consensus evidence"):
        compile_workflow_decisions(
            _records(), wrong_missing_engine, default_decided_at=DECIDED_AT
        )


def test_compile_rejects_stale_repeat_evidence() -> None:
    wrong_raw = [_events()[2]]
    wrong_raw[0]["chosen"]["location"]["raw_by_engine"]["ocr-beta"] = "STALE"
    with pytest.raises(DecisionCompileError, match="raw_by_engine differs"):
        compile_workflow_decisions(_records(), wrong_raw, default_decided_at=DECIDED_AT)

    wrong_inherited_value = [_events()[2]]
    wrong_inherited_value[0]["chosen"]["organization"]["std"] = "Another Archive"
    with pytest.raises(DecisionCompileError, match="does not equal inherited value"):
        compile_workflow_decisions(
            _records(), wrong_inherited_value, default_decided_at=DECIDED_AT
        )


def test_compile_rejects_duplicate_cell_targets_and_unapproved_events() -> None:
    duplicate = [_events()[0], copy.deepcopy(_events()[0])]
    duplicate[1]["decision_id"] = "fixture-duplicate-decision"
    with pytest.raises(DecisionCompileError, match="same cell more than once"):
        compile_workflow_decisions(_records(), duplicate, default_decided_at=DECIDED_AT)

    unapproved = [_events()[0]]
    unapproved[0]["status"] = "pending"
    with pytest.raises(DecisionCompileError, match="not approved"):
        compile_workflow_decisions(_records(), unapproved, default_decided_at=DECIDED_AT)
