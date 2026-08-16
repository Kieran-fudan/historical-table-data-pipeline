from __future__ import annotations

from pathlib import Path

from historical_table_pipeline.config import FieldDefinition, Profile
from historical_table_pipeline.consensus import reconcile_sources
from historical_table_pipeline.enrichment import (
    build_research_views,
    parse_date_expression,
    parse_prices,
)


def test_date_precision_and_century_are_explicit() -> None:
    parsed = parse_date_expression(
        "07.4", {"edition_year": 2012, "two_digit_century": 2000}
    )
    assert parsed["date_start"] == "2007-04"
    assert parsed["date_precision"] == "month"

    ranged = parse_date_expression("2008 (batch one) 2009 (batch two)", {})
    assert ranged["date_start"] == "2008"
    assert ranged["date_end"] == "2009"
    assert ranged["date_precision"] == "range_year"


def test_source_reported_conversion_becomes_two_amount_rows() -> None:
    rows = parse_prices(
        "CR 8.37 thousand (reported equivalent TK 4.25 thousand)",
        None,
        record_id="record-1",
        source_cell_ids=["cell-1"],
        config={
            "currency_aliases": {"CRD": ["CR"], "TOK": ["TK"]},
            "scale_factors": {"thousand": 1000},
            "conversion_markers": ["equivalent"],
        },
    )

    assert [row["currency_code"] for row in rows] == ["CRD", "TOK"]
    assert rows[1]["conversion_role"] == "source_reported_conversion"
    assert rows[0]["scale_factor"] == 1000
    assert rows[0]["basis"] == "unresolved"
    assert rows[0]["unresolved_reason"] is not None


def test_group_quantity_is_context_not_a_second_amount() -> None:
    rows = parse_prices(
        "TK 315750 (6 records total)",
        "TOK combined total",
        record_id="record-1",
        source_cell_ids=["cell-1"],
        config={
            "currency_aliases": {"TOK": ["TK", "TOK"]},
            "group_total_markers": ["total", "combined"],
            "item_labels": ["record"],
            "denominator_label": "records",
        },
    )

    assert len(rows) == 1
    assert rows[0]["value_numeric"] == 315750
    assert rows[0]["value_raw"] == "TK 315750 (6 records total)"
    assert rows[0]["basis"] == "grouped_total"
    assert rows[0]["denominator_unit"] == "6 records"


def test_research_views_resolve_fields_by_semantic_role() -> None:
    cells = {
        "item_name": "Aurora Index",
        "recorded_date": "2001.2",
        "quantity": "2",
        "amount_text": "CR 14",
        "amount_unit_text": "CR per item",
    }
    base_row = {
        "document_id": "fictional-archive",
        "page_id": "page-a",
        "table_id": "table-a",
        "source_pdf_page_index": 0,
        "printed_page_label": "A",
        "source_row_index": 0,
        "cells": cells,
    }
    records = reconcile_sources(
        {
            "ocr-alpha": [{**base_row, "engine_id": "ocr-alpha"}],
            "ocr-beta": [{**base_row, "engine_id": "ocr-beta"}],
        }
    )
    fields = (
        FieldDefinition(
            name="item_name",
            label="Item name",
            metadata={"semantic_role": "label"},
        ),
        FieldDefinition(
            name="recorded_date",
            label="Recorded date",
            metadata={"semantic_role": "date"},
        ),
        FieldDefinition(
            name="quantity",
            label="Quantity",
            metadata={"semantic_role": "quantity"},
        ),
        FieldDefinition(
            name="amount_text",
            label="Amount",
            metadata={"semantic_role": "amount"},
        ),
        FieldDefinition(
            name="amount_unit_text",
            label="Amount unit",
            metadata={"semantic_role": "amount_unit"},
        ),
    )
    profile = Profile(
        path=Path("fictional-profile.yaml"),
        profile_version="1",
        name="Fictional archive",
        record_type="archive_record",
        fields=fields,
        raw={
            "normalization": {
                "dates": {},
                "amounts": {
                    "currency_aliases": {"CRD": ["CR"]},
                    "per_unit_markers": ["per item"],
                    "denominator_label": "item",
                },
            }
        },
    )

    published, amounts = build_research_views(records, profile)

    assert published[0]["date"]["date_start"] == "2001-02"
    assert published[0]["fields"]["quantity"]["std"] == 2
    assert published[0]["fields"]["amount_text"]["std"] == [amounts[0]["price_id"]]
    assert amounts[0]["currency_code"] == "CRD"
    assert amounts[0]["basis"] == "per_unit"
