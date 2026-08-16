from __future__ import annotations

import pytest

from historical_table_pipeline.alignment import AlignmentConfig, align_rows
from historical_table_pipeline.consensus import build_consensus
from historical_table_pipeline.models import (
    ConsensusRecord,
    ConsensusStatus,
    ReviewDecision,
    RowInput,
)
from historical_table_pipeline.review import (
    DecisionApplyError,
    apply_decisions,
    collect_review_items,
    decisions_to_jsonl,
    parse_decisions_jsonl,
)


def conflict_record():
    rows = {
        engine_id: [
            RowInput(
                document_id="document-1",
                page_id="page-1",
                table_id="table-1",
                engine_id=engine_id,
                engine_version="1",
                source_row_index=0,
                cells={"catalog_code": "ARC-1", "item_name": value},
            )
        ]
        for engine_id, value in (("alpha", "Blue Ledger"), ("beta", "Blue Register"))
    }
    groups = align_rows(
        rows,
        config=AlignmentConfig(field_weights={"catalog_code": 1}, anchor_engine="alpha"),
    )
    return build_consensus(groups, expected_engine_ids=("alpha", "beta"))[0]


def test_review_packet_and_candidate_decision_are_replayable() -> None:
    record = conflict_record()
    item = collect_review_items([record])[0]
    candidate = item.cell.candidates[0]
    decision = ReviewDecision(
        cell_id=item.cell.cell_id,
        chosen_value=candidate.normalized_value,
        candidate_id=candidate.candidate_id,
        reason="Checked the synthetic page image.",
        reviewer="reviewer-1",
        decided_at="2026-08-16T00:00:00Z",
    )

    applied = apply_decisions([record], [decision])[0]
    resolved = applied.cells["item_name"]

    assert resolved.status is ConsensusStatus.CONFLICT
    assert resolved.is_resolved
    assert resolved.chosen_value == candidate.normalized_value
    assert resolved.decision == decision
    assert resolved.candidates == record.cells["item_name"].candidates
    assert collect_review_items([applied]) == []
    assert ConsensusRecord.from_dict(applied.to_dict()).to_dict() == applied.to_dict()


def test_decision_jsonl_round_trip_uses_one_canonical_contract() -> None:
    cell = conflict_record().cells["item_name"]
    decision = ReviewDecision(
        decision_id="human-decision-1",
        cell_id=cell.cell_id,
        chosen_value="corrected",
        reason="Synthetic correction.",
        reviewer="reviewer-1",
        decided_at="2026-08-16T00:00:00Z",
    )

    payload = decision.to_dict()
    restored = parse_decisions_jsonl(decisions_to_jsonl([decision]).splitlines())

    assert restored == [decision]
    assert set(payload) == {
        "decision_id",
        "cell_id",
        "chosen_value",
        "reason",
        "reviewer",
        "decided_at",
        "metadata",
    }
    assert "action" not in payload and "field" not in payload


def test_apply_rejects_stale_candidate_and_duplicate_cell_decisions() -> None:
    record = conflict_record()
    cell = record.cells["item_name"]
    stale = ReviewDecision(
        cell_id=cell.cell_id,
        chosen_value="Blue Ledger",
        candidate_id="cand_stale",
        reason="Synthetic stale decision.",
        reviewer="reviewer-1",
        decided_at="2026-08-16T00:00:00Z",
    )
    with pytest.raises(DecisionApplyError, match="does not belong"):
        apply_decisions([record], [stale])

    valid = ReviewDecision(
        cell_id=cell.cell_id,
        chosen_value="custom",
        reason="Synthetic correction.",
        reviewer="reviewer-1",
        decided_at="2026-08-16T00:00:00Z",
    )
    with pytest.raises(DecisionApplyError, match="multiple decisions"):
        apply_decisions([record], [valid, valid])
