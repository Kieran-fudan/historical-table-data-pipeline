from __future__ import annotations

import pytest

from historical_table_pipeline.quality import summarize_statuses, zero_error_upper_bound


def test_zero_error_bound_is_about_three_per_thousand_for_n_1000() -> None:
    assert zero_error_upper_bound(1000) == pytest.approx(0.002991, rel=1e-3)


def test_quality_summary_does_not_overclaim_accuracy() -> None:
    summary = summarize_statuses(
        [{"status": "unanimous"}, {"status": "conflict"}, {"status": "missing_source"}]
    )
    assert summary["total_cells"] == 3
    assert summary["unresolved_cells"] == 2
    assert "does not" in summary["claim_boundary"]


def test_decision_resolved_conflict_is_not_counted_as_unresolved() -> None:
    summary = summarize_statuses(
        [
            {"status": "conflict", "resolved": True},
            {"status": "missing", "resolved": False},
        ]
    )
    assert summary["unresolved_cells"] == 1
