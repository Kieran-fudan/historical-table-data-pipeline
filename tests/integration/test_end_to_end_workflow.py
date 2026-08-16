from __future__ import annotations

import json
from pathlib import Path

from historical_table_pipeline.config import load_profile
from historical_table_pipeline.publish import publish
from historical_table_pipeline.validation import validate_consensus
from historical_table_pipeline.workflow import (
    apply_decision_file,
    export_review,
    load_consensus,
    reconcile_files,
)

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "examples" / "synthetic"
PROFILE = ROOT / "profiles" / "example-records.yaml"


def _json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _jsonl(path: Path) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_synthetic_reconcile_review_validate_publish_is_replayable(tmp_path: Path) -> None:
    inputs = [
        FIXTURE / "ocr" / "engine-a.jsonl",
        FIXTURE / "ocr" / "engine-b.jsonl",
    ]
    input_rows = [row for path in inputs for row in _jsonl(path)]
    expected_records = len(
        {
            (
                row["document_id"],
                row["page_id"],
                row["table_id"],
                row["source_row_index"],
            )
            for row in input_rows
        }
    )
    first = reconcile_files(PROFILE, inputs, tmp_path / "runs")
    second = reconcile_files(PROFILE, inputs, tmp_path / "runs")

    assert first["run_id"] == second["run_id"]
    assert first["aligned_records"] == expected_records
    assert first["unresolved_cells"] > 0
    review = export_review(first["consensus"], tmp_path / "review")
    assert review["review_item_count"] == first["unresolved_cells"]

    application = apply_decision_file(
        first["consensus"],
        FIXTURE / "decisions" / "reconciliation.jsonl",
        PROFILE,
        tmp_path / "applications",
        default_decided_at="2000-01-01T00:00:00Z",
    )
    assert application["compiled_decision_count"] == review["review_item_count"]
    assert application["remaining_review_items"] == 0
    assert application["ready_to_publish"] is True

    _, reviewed = load_consensus(application["reviewed_consensus"])
    report = validate_consensus(reviewed, load_profile(PROFILE))
    assert report["structurally_valid"] is True
    assert report["unresolved_cell_count"] == 0

    publication = tmp_path / "publication"
    quality = publish(
        reviewed,
        load_profile(PROFILE),
        publication,
        include_research_formats=False,
    )
    assert quality["published_records"] == expected_records
    assert quality["price_observations"] >= 1
    assert quality["currencies"]
    assert quality["provenance_completeness"] == 1.0
    assert (publication / "records.csv").is_file()
    assert (publication / "prices.csv").is_file()
    first_record = json.loads(
        (publication / "records.jsonl").read_text(encoding="utf-8").splitlines()[0]
    )
    assert first_record["source_pdf_page_index"] == min(
        row["source_pdf_page_index"] for row in input_rows
    )
    assert _json(publication / "quality-summary.json")["unresolved_cells"] == 0
