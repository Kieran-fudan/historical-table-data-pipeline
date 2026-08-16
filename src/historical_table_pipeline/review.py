"""Structured review packets and deterministic decision replay."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any

from .models import (
    ConsensusCell,
    ConsensusRecord,
    ConsensusStatus,
    JsonValue,
    ReviewDecision,
)


@dataclass(frozen=True, slots=True)
class ReviewItem:
    """Self-contained cell packet suitable for a human or model review queue."""

    record_id: str
    document_id: str
    page_id: str
    table_id: str
    ordinal: int
    cell: ConsensusCell

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "record_id": self.record_id,
            "document_id": self.document_id,
            "page_id": self.page_id,
            "table_id": self.table_id,
            "ordinal": self.ordinal,
            "cell": self.cell.to_dict(),
            "decision_contract": {
                "required": [
                    "cell_id",
                    "chosen_value",
                    "reason",
                    "reviewer",
                    "decided_at",
                ],
                "optional": ["decision_id", "candidate_id", "metadata"],
            },
        }


class DecisionApplyError(ValueError):
    """Raised when a replay file does not match the current consensus artifact."""


def collect_review_items(
    records: Sequence[ConsensusRecord],
    *,
    statuses: Iterable[ConsensusStatus | str] = (
        ConsensusStatus.CONFLICT,
        ConsensusStatus.MISSING,
    ),
    include_resolved: bool = False,
) -> list[ReviewItem]:
    """Collect deterministic review packets in record/field order."""

    selected = {ConsensusStatus(status) for status in statuses}
    items: list[ReviewItem] = []
    for record in records:
        for field_name in sorted(record.cells):
            cell = record.cells[field_name]
            if cell.status not in selected:
                continue
            if cell.decision is not None and not include_resolved:
                continue
            items.append(
                ReviewItem(
                    record_id=record.record_id,
                    document_id=record.document_id,
                    page_id=record.page_id,
                    table_id=record.table_id,
                    ordinal=record.ordinal,
                    cell=cell,
                )
            )
    return items


def parse_decisions_jsonl(lines: Iterable[str]) -> list[ReviewDecision]:
    """Parse decisions from JSONL text with useful line-number errors."""

    decisions: list[ReviewDecision] = []
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid decision JSON on line {line_number}: {exc.msg}") from exc
        if not isinstance(payload, Mapping):
            raise ValueError(f"decision line {line_number} must be a JSON object")
        try:
            decisions.append(ReviewDecision.from_dict(payload))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"invalid decision on line {line_number}: {exc}") from exc
    return decisions


def decisions_to_jsonl(decisions: Iterable[ReviewDecision]) -> str:
    """Serialize replay decisions deterministically, ending with a newline."""

    lines = [
        json.dumps(decision.to_dict(), ensure_ascii=False, sort_keys=True)
        for decision in decisions
    ]
    return "" if not lines else "\n".join(lines) + "\n"


def review_items_to_jsonl(items: Iterable[ReviewItem]) -> str:
    lines = [
        json.dumps(item.to_dict(), ensure_ascii=False, sort_keys=True) for item in items
    ]
    return "" if not lines else "\n".join(lines) + "\n"


def _apply_one(cell: ConsensusCell, decision: ReviewDecision) -> ConsensusCell:
    if decision.cell_id != cell.cell_id:
        raise DecisionApplyError("decision target does not match consensus cell")
    if decision.candidate_id is not None:
        matches = [
            candidate
            for candidate in cell.candidates
            if candidate.candidate_id == decision.candidate_id
        ]
        if not matches:
            raise DecisionApplyError(
                f"candidate {decision.candidate_id!r} does not belong to {cell.cell_id}"
            )
        if (
            type(matches[0].normalized_value) is not type(decision.chosen_value)
            or matches[0].normalized_value != decision.chosen_value
        ):
            raise DecisionApplyError(
                "chosen_value does not equal the selected candidate's normalized value"
            )
        supporters = (matches[0].candidate_id,)
    else:
        supporters = tuple(
            candidate.candidate_id
            for candidate in cell.candidates
            if type(candidate.normalized_value) is type(decision.chosen_value)
            and candidate.normalized_value == decision.chosen_value
        )
    return replace(
        cell,
        chosen_value=decision.chosen_value,
        supporting_candidate_ids=supporters,
        decision=decision,
    )


def apply_decisions(
    records: Sequence[ConsensusRecord],
    decisions: Iterable[ReviewDecision | Mapping[str, Any]],
    *,
    strict: bool = True,
) -> list[ConsensusRecord]:
    """Replay structured decisions without mutating records or source evidence.

    In strict mode (the default), stale record/cell IDs, duplicate decisions,
    and foreign candidate IDs fail the entire call.  This is intentional: a
    decision file should never silently drift onto a regenerated artifact.
    """

    parsed = [
        decision
        if isinstance(decision, ReviewDecision)
        else ReviewDecision.from_dict(decision)
        for decision in decisions
    ]
    by_target: dict[str, ReviewDecision] = {}
    for decision in parsed:
        target = decision.cell_id
        if target in by_target:
            raise DecisionApplyError(f"multiple decisions target {decision.cell_id}")
        by_target[target] = decision

    known_targets = {cell.cell_id for record in records for cell in record.cells.values()}
    unknown = sorted(set(by_target) - known_targets)
    if unknown and strict:
        rendered = ", ".join(unknown)
        raise DecisionApplyError(f"decisions target unknown cells: {rendered}")

    output: list[ConsensusRecord] = []
    for record in records:
        cells = dict(record.cells)
        for field_name, cell in record.cells.items():
            decision = by_target.get(cell.cell_id)
            if decision is None:
                continue
            cells[field_name] = _apply_one(cell, decision)
        output.append(replace(record, cells=cells))
    return output


__all__ = [
    "DecisionApplyError",
    "ReviewItem",
    "apply_decisions",
    "collect_review_items",
    "decisions_to_jsonl",
    "parse_decisions_jsonl",
    "review_items_to_jsonl",
]
