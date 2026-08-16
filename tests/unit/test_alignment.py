from __future__ import annotations

from dataclasses import replace

from historical_table_pipeline.alignment import AlignmentConfig, align_rows, row_similarity
from historical_table_pipeline.models import AlignedRowGroup, RowInput


def make_row(
    engine_id: str,
    source_row_index: int,
    catalog_code: str,
    *,
    item_name: str | None = None,
    page_id: str = "page-1",
) -> RowInput:
    return RowInput(
        document_id="document-1",
        page_id=page_id,
        table_id=f"table-{page_id}",
        engine_id=engine_id,
        engine_version="synthetic-1",
        source_row_index=source_row_index,
        source_pdf_page_index=0,
        printed_page_label="1",
        cells={"catalog_code": catalog_code, "item_name": item_name or catalog_code},
        metadata={"run_id": f"run-{engine_id}"},
    )


def test_weighted_dynamic_programming_preserves_order_and_gaps() -> None:
    alpha = [
        make_row("alpha", index, code)
        for index, code in enumerate(("ARC-A", "ARC-B", "ARC-C"))
    ]
    beta = [
        make_row("beta", index, code)
        for index, code in enumerate(("ARC-A", "ARC-C"))
    ]

    groups = align_rows(
        {"alpha": alpha, "beta": beta},
        config=AlignmentConfig(
            field_weights={"catalog_code": 3, "item_name": 0},
            minimum_match_similarity=0.8,
            anchor_engine="alpha",
        ),
    )

    assert [[row.cells["catalog_code"] for row in group.rows] for group in groups] == [
        ["ARC-A", "ARC-A"],
        ["ARC-B"],
        ["ARC-C", "ARC-C"],
    ]
    assert [group.ordinal for group in groups] == [1, 2, 3]
    assert groups[1].anchor_engine_id == "alpha"


def test_similarity_uses_normalization_and_configured_field_weights() -> None:
    alpha = make_row("alpha", 0, "ＡＲＣ-20", item_name="First title")
    beta = make_row("beta", 0, "ARC-20", item_name="Different title")
    config = AlignmentConfig(field_weights={"catalog_code": 10, "item_name": 0})

    assert row_similarity(alpha, beta, config=config) == 1.0


def test_record_ids_do_not_change_when_a_third_engine_is_attached() -> None:
    alpha = [
        make_row("alpha", index, code)
        for index, code in enumerate(("ARC-A", "ARC-B"))
    ]
    beta = [
        make_row("beta", index, code)
        for index, code in enumerate(("ARC-A", "ARC-B"))
    ]
    config = AlignmentConfig(field_weights={"catalog_code": 1}, anchor_engine="alpha")

    original = align_rows({"alpha": alpha, "beta": beta}, config=config)
    gamma = [
        make_row("gamma", index, code)
        for index, code in enumerate(("ARC-A", "ARC-B"))
    ]
    expanded = align_rows(
        {"alpha": alpha, "beta": beta, "gamma": gamma},
        config=config,
    )

    assert [group.record_id for group in expanded] == [group.record_id for group in original]
    assert all(group.anchor_engine_id == "alpha" for group in expanded)


def test_record_ids_ignore_extraction_version_and_file_location() -> None:
    original = make_row("alpha", 0, "A")
    rerun = replace(
        original,
        engine_version="synthetic-2",
        source_ref="renamed-input.jsonl:99",
    )

    first = align_rows({"alpha": [original]})[0]
    second = align_rows({"alpha": [rerun]})[0]
    assert first.record_id == second.record_id


def test_alignment_round_trip_emits_only_canonical_long_keys() -> None:
    row = RowInput.from_dict(
        {
            "document": "document-1",
            "page": "page-1",
            "table": "table-1",
            "source_row": 0,
            "engine": "alpha",
            "cells": {"catalog_code": "ARC-A"},
        }
    )
    group = align_rows({"alpha": [row]})[0]
    payload = group.to_dict()

    assert {"document_id", "page_id", "table_id", "anchor_engine_id"} <= payload.keys()
    assert "document" not in payload
    assert payload == AlignedRowGroup.from_dict(payload).to_dict()
