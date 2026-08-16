"""Publish reviewed consensus as auditable JSONL, CSV, Parquet, and DuckDB views."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from historical_table_pipeline.config import Profile
from historical_table_pipeline.enrichment import build_research_views
from historical_table_pipeline.io import write_csv, write_json, write_jsonl
from historical_table_pipeline.models import ConsensusRecord
from historical_table_pipeline.quality import summarize_statuses


def _wide_rows(records: list[dict[str, Any]], profile: Profile) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for record in records:
        row = {
            "record_id": record["record_id"],
            "document_id": record["document_id"],
            "page_id": record["page_id"],
            "source_pdf_page_index": record["source_pdf_page_index"],
            "printed_page_label": record["printed_page_label"],
            "table_id": record["table_id"],
            "source_row_index": record["source_row_index"],
            "record_status": record["record_status"],
        }
        for field_name in profile.field_names:
            field = record["fields"].get(field_name, {})
            value = field.get("std")
            row[field_name] = (
                json.dumps(value, ensure_ascii=False, sort_keys=True)
                if isinstance(value, (dict, list))
                else value
            )
            row[f"{field_name}__status"] = field.get("status")
        output.append(row)
    return output


def _cell_rows(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for record in records:
        for field_name, field in record["fields"].items():
            rows.append(
                {
                    "record_id": record["record_id"],
                    "cell_id": field.get("cell_id"),
                    "field": field_name,
                    "value_std": (
                        json.dumps(field.get("std"), ensure_ascii=False, sort_keys=True)
                        if isinstance(field.get("std"), (dict, list))
                        else field.get("std")
                    ),
                    "status": field.get("status"),
                    "raw_by_engine_json": json.dumps(
                        field.get("raw", {}), ensure_ascii=False, sort_keys=True
                    ),
                }
            )
    return rows


def build_quality_summary(
    consensus: list[ConsensusRecord],
    records: list[dict[str, Any]],
    prices: list[dict[str, Any]],
) -> dict[str, Any]:
    cells = [cell.to_dict() for record in consensus for cell in record.cells.values()]
    base = summarize_statuses(cells)
    rows_by_engine = Counter(
        source.engine for record in consensus for source in record.sources
    )
    decisions = {
        cell.decision.decision_id: cell.decision
        for record in consensus
        for cell in record.cells.values()
        if cell.decision is not None
    }
    review_events = {
        str(
            decision.metadata.get("source_decision_id", decision.decision_id)
        )
        for decision in decisions.values()
    }
    complete = sum(
        record.get("source_pdf_page_index") is not None
        and bool(record.get("page_id"))
        and bool(record.get("table_id"))
        for record in records
    )
    base.update(
        {
            "aligned_records": len(consensus),
            "published_records": len(records),
            "rows_by_engine": dict(sorted(rows_by_engine.items())),
            "manual_or_agent_decisions": len(review_events),
            "cell_decisions": len(decisions),
            "price_observations": len(prices),
            "unresolved_price_observations": sum(
                item.get("unresolved_reason") is not None for item in prices
            ),
            "currencies": sorted(
                {item["currency_code"] for item in prices if item.get("currency_code")}
            ),
            "provenance_completeness": complete / len(records) if records else 1.0,
            "source_accuracy_estimate": None,
            "source_accuracy_note": (
                "Populate only from a stratified audit against source images; agreement "
                "between OCR engines is not a source-accuracy estimate."
            ),
        }
    )
    return base


def _write_duckdb(
    output_dir: Path,
    wide_rows: list[dict[str, Any]],
    cell_rows: list[dict[str, Any]],
    prices: list[dict[str, Any]],
    columns_by_table: dict[str, list[str]],
) -> dict[str, str] | None:
    try:
        import duckdb
    except ImportError:
        return None
    database_path = output_dir / "research.duckdb"
    connection = duckdb.connect(str(database_path))
    try:
        for table_name, rows in (
            ("records", wide_rows),
            ("cells", cell_rows),
            ("prices", prices),
        ):
            if rows:
                json_path = output_dir / f".{table_name}.load.jsonl"
                write_jsonl(json_path, rows)
                escaped = str(json_path).replace("'", "''")
                connection.execute(
                    f"CREATE OR REPLACE TABLE {table_name} AS "
                    f"SELECT * FROM read_json_auto('{escaped}', "
                    "format='newline_delimited')"
                )
                json_path.unlink()
            else:
                columns = ", ".join(
                    f'"{name.replace(chr(34), chr(34) * 2)}" VARCHAR'
                    for name in columns_by_table[table_name]
                )
                connection.execute(
                    f"CREATE OR REPLACE TABLE {table_name} ({columns})"
                )
            parquet_path = output_dir / f"{table_name}.parquet"
            escaped_parquet = str(parquet_path).replace("'", "''")
            connection.execute(
                f"COPY {table_name} TO '{escaped_parquet}' (FORMAT PARQUET, COMPRESSION ZSTD)"
            )
    finally:
        connection.close()
    return {
        "duckdb": database_path.name,
        "records_parquet": "records.parquet",
        "cells_parquet": "cells.parquet",
        "prices_parquet": "prices.parquet",
    }


def publish(
    consensus: list[ConsensusRecord],
    profile: Profile,
    output_dir: str | Path,
    *,
    include_research_formats: bool = True,
) -> dict[str, Any]:
    destination = Path(output_dir).expanduser().resolve()
    destination.mkdir(parents=True, exist_ok=True)
    records, prices = build_research_views(consensus, profile)
    wide_rows = _wide_rows(records, profile)
    cell_rows = _cell_rows(records)
    record_columns = [
        "record_id",
        "document_id",
        "page_id",
        "source_pdf_page_index",
        "printed_page_label",
        "table_id",
        "source_row_index",
        "record_status",
        *[
            name
            for field_name in profile.field_names
            for name in (field_name, f"{field_name}__status")
        ],
    ]
    cell_columns = [
        "record_id",
        "cell_id",
        "field",
        "value_std",
        "status",
        "raw_by_engine_json",
    ]
    price_columns = [
        "price_id",
        "record_id",
        "value_raw",
        "value_numeric",
        "currency_code",
        "scale_factor",
        "basis",
        "denominator_unit",
        "conversion_role",
        "source_reported",
        "unresolved_reason",
        "source_cell_ids",
        "currency_alias_matched",
    ]
    write_jsonl(destination / "records.jsonl", records)
    write_jsonl(destination / "prices.jsonl", prices)
    write_csv(
        destination / "records.csv",
        wide_rows,
        record_columns,
    )
    write_csv(
        destination / "cells.csv",
        cell_rows,
        cell_columns,
    )
    write_csv(
        destination / "prices.csv",
        [
            {
                **item,
                "source_cell_ids": json.dumps(
                    item.get("source_cell_ids", []), ensure_ascii=False, sort_keys=True
                ),
            }
            for item in prices
        ],
        price_columns,
    )
    quality = build_quality_summary(consensus, records, prices)
    research_files = (
        _write_duckdb(
            destination,
            wide_rows,
            cell_rows,
            prices,
            {
                "records": record_columns,
                "cells": cell_columns,
                "prices": price_columns,
            },
        )
        if include_research_formats
        else None
    )
    quality["research_formats"] = research_files or {
        "status": "not_generated",
        "install_hint": "pip install 'historical-table-data-pipeline[research]'",
    }
    write_json(destination / "quality-summary.json", quality)
    return quality


__all__ = ["build_quality_summary", "publish"]
