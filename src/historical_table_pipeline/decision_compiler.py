"""Compile workflow-level audit events into replayable cell decisions.

The workflow ledger uses human-readable source locators so it can express one
review event for an entire missing row or a group of ditto-marked cells.  The
core review layer intentionally accepts only one decision per stable cell ID.
This module bridges the two contracts without weakening evidence checks.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from .models import (
    CellCandidate,
    ConsensusCell,
    ConsensusRecord,
    JsonScalar,
    ReviewDecision,
)


class DecisionCompileError(ValueError):
    """Raised when a workflow decision cannot be tied to unique source evidence."""


LocatorKey = tuple[str, str, str, tuple[str, str]]


def _value_token(value: Any) -> tuple[str, str]:
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise DecisionCompileError("workflow evidence must be finite JSON data") from exc
    return (type(value).__name__, encoded)


def _same_value(left: Any, right: Any) -> bool:
    return type(left) is type(right) and left == right


def _mapping(value: Any, *, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise DecisionCompileError(f"{label} must be an object")
    return value


def _text(payload: Mapping[str, Any], key: str, *, label: str) -> str:
    if key not in payload:
        raise DecisionCompileError(f"{label}.{key} is required")
    value = payload[key]
    if not isinstance(value, str) or not value.strip():
        raise DecisionCompileError(f"{label}.{key} must be a non-empty string")
    return value


def _optional_text(payload: Mapping[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise DecisionCompileError(f"{key} must be a non-empty string when provided")
    return value


def _text_list(payload: Mapping[str, Any], key: str, *, label: str) -> list[str]:
    if key not in payload:
        raise DecisionCompileError(f"{label}.{key} is required")
    value = payload[key]
    if not isinstance(value, list) or not value:
        raise DecisionCompileError(f"{label}.{key} must be a non-empty list")
    if any(not isinstance(item, str) or not item.strip() for item in value):
        raise DecisionCompileError(f"{label}.{key} must contain non-empty strings")
    if len(value) != len(set(value)):
        raise DecisionCompileError(f"{label}.{key} must not contain duplicates")
    return value


def _locator_key(target: Mapping[str, Any], *, label: str) -> LocatorKey:
    document_id = _text(target, "document_id", label=label)
    page_id = _text(target, "page_id", label=label)
    table_id = _text(target, "table_id", label=label)
    if "source_row_index" not in target:
        raise DecisionCompileError(f"{label}.source_row_index is required")
    source_row_index = target["source_row_index"]
    if isinstance(source_row_index, bool) or not isinstance(source_row_index, (int, str)):
        raise DecisionCompileError(
            f"{label}.source_row_index must be a non-negative integer or non-empty string"
        )
    if isinstance(source_row_index, int) and source_row_index < 0:
        raise DecisionCompileError(f"{label}.source_row_index must be non-negative")
    if isinstance(source_row_index, str) and not source_row_index.strip():
        raise DecisionCompileError(f"{label}.source_row_index must not be empty")
    return (document_id, page_id, table_id, _value_token(source_row_index))


def _coerce_records(
    records: Sequence[ConsensusRecord | Mapping[str, Any]],
) -> list[ConsensusRecord]:
    output: list[ConsensusRecord] = []
    seen_record_ids: set[str] = set()
    for index, value in enumerate(records):
        try:
            record = (
                value
                if isinstance(value, ConsensusRecord)
                else ConsensusRecord.from_dict(value)
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise DecisionCompileError(f"invalid consensus record at index {index}: {exc}") from exc
        if record.record_id in seen_record_ids:
            raise DecisionCompileError(f"duplicate consensus record_id {record.record_id!r}")
        seen_record_ids.add(record.record_id)
        output.append(record)
    return output


def _build_record_index(
    records: Sequence[ConsensusRecord],
) -> dict[LocatorKey, list[ConsensusRecord]]:
    index: dict[LocatorKey, list[ConsensusRecord]] = {}
    for record in records:
        record_keys: set[LocatorKey] = set()
        for source in record.sources:
            source_section = (source.document_id, source.page_id, source.table_id)
            record_section = (record.document_id, record.page_id, record.table_id)
            if source_section != record_section:
                raise DecisionCompileError(
                    f"record {record.record_id!r} contains cross-section source provenance"
                )
            key: LocatorKey = (*record_section, _value_token(source.source_row_index))
            record_keys.add(key)
        for key in record_keys:
            index.setdefault(key, []).append(record)
    return index


def _locate_record(
    index: Mapping[LocatorKey, Sequence[ConsensusRecord]],
    target: Mapping[str, Any],
    *,
    label: str,
) -> ConsensusRecord:
    key = _locator_key(target, label=label)
    matches = list(index.get(key, ()))
    if not matches:
        raise DecisionCompileError(f"{label} refers to an unknown target")
    if len(matches) > 1:
        raise DecisionCompileError(f"{label} is ambiguous across aligned records")
    return matches[0]


def _cell(record: ConsensusRecord, field_name: str, *, label: str) -> ConsensusCell:
    cell = record.cells.get(field_name)
    if cell is None:
        raise DecisionCompileError(f"{label} refers to unknown field {field_name!r}")
    if cell.is_resolved:
        raise DecisionCompileError(f"{label} refers to already resolved cell {cell.cell_id!r}")
    return cell


def _candidate_by_engine_and_raw(
    cell: ConsensusCell,
    *,
    engine_id: str,
    raw_value: Any,
    label: str,
) -> CellCandidate:
    matches = [
        candidate
        for candidate in cell.candidates
        if candidate.provenance.engine_id == engine_id
        and _same_value(candidate.raw_value, raw_value)
    ]
    if not matches:
        raise DecisionCompileError(
            f"{label} evidence mismatch: no candidate has the selected engine/raw value"
        )
    if len(matches) > 1:
        raise DecisionCompileError(
            f"{label} is ambiguous: multiple candidates have the selected engine/raw value"
        )
    return matches[0]


def _candidate_by_engine(
    cell: ConsensusCell,
    *,
    engine_id: str,
    label: str,
) -> CellCandidate:
    matches = [
        candidate
        for candidate in cell.candidates
        if candidate.provenance.engine_id == engine_id
    ]
    if not matches:
        raise DecisionCompileError(
            f"{label} evidence mismatch: selected engine has no candidate for {cell.field!r}"
        )
    if len(matches) > 1:
        raise DecisionCompileError(
            f"{label} is ambiguous: selected engine has multiple candidates for {cell.field!r}"
        )
    return matches[0]


def _require_reported_engines(
    evidence: Mapping[str, Any],
    key: str,
    actual: Sequence[str],
    *,
    label: str,
) -> None:
    reported = _text_list(evidence, key, label=label)
    if Counter(reported) != Counter(actual):
        raise DecisionCompileError(f"{label}.{key} does not match consensus evidence")


def _make_decision(
    *,
    cell: ConsensusCell,
    chosen_value: JsonScalar,
    candidate_id: str | None,
    event: Mapping[str, Any],
    source_decision_id: str,
    source_decision_type: str,
    default_reviewer: str | None,
    default_decided_at: str | None,
) -> ReviewDecision:
    reason = _text(event, "rationale", label=source_decision_id)
    reviewer = (
        _optional_text(event, "reviewer")
        or _optional_text(event, "reviewer_kind")
        or default_reviewer
    )
    decided_at = _optional_text(event, "decided_at") or default_decided_at
    if not isinstance(reviewer, str) or not reviewer.strip():
        raise DecisionCompileError(
            f"{source_decision_id} requires reviewer, reviewer_kind, or default_reviewer"
        )
    if not isinstance(decided_at, str) or not decided_at.strip():
        raise DecisionCompileError(
            f"{source_decision_id} requires decided_at or default_decided_at"
        )
    try:
        return ReviewDecision(
            cell_id=cell.cell_id,
            chosen_value=chosen_value,
            candidate_id=candidate_id,
            reason=reason,
            reviewer=reviewer,
            decided_at=decided_at,
            metadata={
                "source_decision_id": source_decision_id,
                "source_decision_type": source_decision_type,
            },
        )
    except (TypeError, ValueError) as exc:
        raise DecisionCompileError(
            f"{source_decision_id} cannot produce a core decision: {exc}"
        ) from exc


def _compile_choose_candidate(
    record: ConsensusRecord,
    event: Mapping[str, Any],
    target: Mapping[str, Any],
    *,
    source_decision_id: str,
    default_reviewer: str | None,
    default_decided_at: str | None,
) -> list[ReviewDecision]:
    field_name = _text(target, "field_name", label=f"{source_decision_id}.target")
    cell = _cell(record, field_name, label=source_decision_id)
    chosen = _mapping(event.get("chosen"), label=f"{source_decision_id}.chosen")
    engine_id = _text(chosen, "engine_id", label=f"{source_decision_id}.chosen")
    if "raw" not in chosen or "std" not in chosen:
        raise DecisionCompileError(f"{source_decision_id}.chosen requires raw and std")
    candidate = _candidate_by_engine_and_raw(
        cell,
        engine_id=engine_id,
        raw_value=chosen["raw"],
        label=source_decision_id,
    )
    if not _same_value(candidate.normalized_value, chosen["std"]):
        raise DecisionCompileError(
            f"{source_decision_id} evidence mismatch: chosen.std differs from "
            "candidate normalization"
        )

    evidence = _mapping(event.get("evidence"), label=f"{source_decision_id}.evidence")
    _require_reported_engines(
        evidence,
        "engine_ids",
        [item.provenance.engine_id for item in cell.candidates],
        label=f"{source_decision_id}.evidence",
    )
    reported_values = evidence.get("candidate_values")
    if not isinstance(reported_values, list) or not reported_values:
        raise DecisionCompileError(
            f"{source_decision_id}.evidence.candidate_values must be a non-empty list"
        )
    if Counter(map(_value_token, reported_values)) != Counter(
        _value_token(item.raw_value) for item in cell.candidates
    ):
        raise DecisionCompileError(
            f"{source_decision_id}.evidence.candidate_values does not match consensus evidence"
        )
    return [
        _make_decision(
            cell=cell,
            chosen_value=candidate.normalized_value,
            candidate_id=candidate.candidate_id,
            event=event,
            source_decision_id=source_decision_id,
            source_decision_type="choose_candidate",
            default_reviewer=default_reviewer,
            default_decided_at=default_decided_at,
        )
    ]


def _compile_accept_single_source_row(
    record: ConsensusRecord,
    event: Mapping[str, Any],
    *,
    source_decision_id: str,
    default_reviewer: str | None,
    default_decided_at: str | None,
) -> list[ReviewDecision]:
    chosen = _mapping(event.get("chosen"), label=f"{source_decision_id}.chosen")
    engine_id = _text(chosen, "engine_id", label=f"{source_decision_id}.chosen")
    present_engines = [source.engine_id for source in record.sources]
    if len(present_engines) != 1 or present_engines[0] != engine_id:
        raise DecisionCompileError(
            f"{source_decision_id} evidence mismatch: target is not a row from only "
            "the selected engine"
        )
    if not record.missing_engine_ids:
        raise DecisionCompileError(
            f"{source_decision_id} evidence mismatch: target has no missing expected engine"
        )

    evidence = _mapping(event.get("evidence"), label=f"{source_decision_id}.evidence")
    _require_reported_engines(
        evidence,
        "present_engines",
        present_engines,
        label=f"{source_decision_id}.evidence",
    )
    _require_reported_engines(
        evidence,
        "missing_engines",
        list(record.missing_engine_ids),
        label=f"{source_decision_id}.evidence",
    )

    unresolved = [cell for _, cell in sorted(record.cells.items()) if not cell.is_resolved]
    if not unresolved:
        raise DecisionCompileError(f"{source_decision_id} target has no unresolved cells")
    decisions: list[ReviewDecision] = []
    for cell in unresolved:
        candidate = _candidate_by_engine(cell, engine_id=engine_id, label=source_decision_id)
        decisions.append(
            _make_decision(
                cell=cell,
                chosen_value=candidate.normalized_value,
                candidate_id=candidate.candidate_id,
                event=event,
                source_decision_id=source_decision_id,
                source_decision_type="accept_single_source_row",
                default_reviewer=default_reviewer,
                default_decided_at=default_decided_at,
            )
        )
    return decisions


def _raw_by_engine(cell: ConsensusCell, *, label: str) -> dict[str, JsonScalar]:
    result: dict[str, JsonScalar] = {}
    for candidate in cell.candidates:
        engine_id = candidate.provenance.engine_id
        if engine_id in result:
            raise DecisionCompileError(
                f"{label} is ambiguous: multiple candidates come from engine {engine_id!r}"
            )
        result[engine_id] = candidate.raw_value
    return result


def _compile_resolve_repeat_marker(
    record: ConsensusRecord,
    event: Mapping[str, Any],
    target: Mapping[str, Any],
    record_index: Mapping[LocatorKey, Sequence[ConsensusRecord]],
    *,
    source_decision_id: str,
    default_reviewer: str | None,
    default_decided_at: str | None,
) -> list[ReviewDecision]:
    field_names = _text_list(
        target,
        "field_names",
        label=f"{source_decision_id}.target",
    )
    chosen = _mapping(event.get("chosen"), label=f"{source_decision_id}.chosen")
    if set(chosen) != set(field_names):
        raise DecisionCompileError(
            f"{source_decision_id}.chosen fields must exactly match target.field_names"
        )
    evidence = _mapping(event.get("evidence"), label=f"{source_decision_id}.evidence")
    if evidence.get("same_table_only") is not True:
        raise DecisionCompileError(
            f"{source_decision_id}.evidence.same_table_only must be true"
        )
    if "inherits_from_source_row_index" not in evidence:
        raise DecisionCompileError(
            f"{source_decision_id}.evidence.inherits_from_source_row_index is required"
        )
    inherited_target = {
        "document_id": target["document_id"],
        "page_id": target["page_id"],
        "table_id": target["table_id"],
        "source_row_index": evidence["inherits_from_source_row_index"],
    }
    predecessor = _locate_record(
        record_index,
        inherited_target,
        label=f"{source_decision_id}.evidence",
    )
    if predecessor.record_id == record.record_id or predecessor.ordinal >= record.ordinal:
        raise DecisionCompileError(
            f"{source_decision_id} evidence mismatch: inherited row is not a preceding record"
        )

    decisions: list[ReviewDecision] = []
    for field_name in field_names:
        cell = _cell(record, field_name, label=source_decision_id)
        selection = _mapping(
            chosen[field_name],
            label=f"{source_decision_id}.chosen.{field_name}",
        )
        if "std" not in selection:
            raise DecisionCompileError(
                f"{source_decision_id}.chosen.{field_name}.std is required"
            )
        reported_raw = _mapping(
            selection.get("raw_by_engine"),
            label=f"{source_decision_id}.chosen.{field_name}.raw_by_engine",
        )
        actual_raw = _raw_by_engine(cell, label=source_decision_id)
        if set(reported_raw) != set(actual_raw) or any(
            not _same_value(reported_raw[engine_id], raw_value)
            for engine_id, raw_value in actual_raw.items()
        ):
            raise DecisionCompileError(
                f"{source_decision_id} evidence mismatch: raw_by_engine differs for {field_name!r}"
            )

        predecessor_cell = predecessor.cells.get(field_name)
        if predecessor_cell is None or not predecessor_cell.is_resolved:
            raise DecisionCompileError(
                f"{source_decision_id} evidence mismatch: inherited {field_name!r} is unresolved"
            )
        if not _same_value(selection["std"], predecessor_cell.chosen_value):
            raise DecisionCompileError(
                f"{source_decision_id} evidence mismatch: chosen.std does not equal inherited value"
            )
        decisions.append(
            _make_decision(
                cell=cell,
                chosen_value=selection["std"],
                candidate_id=None,
                event=event,
                source_decision_id=source_decision_id,
                source_decision_type="resolve_repeat_marker",
                default_reviewer=default_reviewer,
                default_decided_at=default_decided_at,
            )
        )
    return decisions


def compile_workflow_decisions(
    records: Sequence[ConsensusRecord | Mapping[str, Any]],
    workflow_decisions: Iterable[Mapping[str, Any]],
    *,
    default_reviewer: str | None = None,
    default_decided_at: str | None = None,
) -> list[ReviewDecision]:
    """Compile approved workflow events into strict, cell-level decisions.

    Records are located only through ``document_id``, ``page_id``, ``table_id``,
    and ``source_row_index`` in source provenance. Unknown or non-unique
    locators, stale evidence, duplicate source events, and duplicate cell targets
    fail the entire compilation.

    The example workflow ledger has ``reviewer_kind`` but no timestamp. Callers
    should therefore provide ``default_decided_at`` unless every event carries a
    non-empty ``decided_at`` value.
    """

    parsed_records = _coerce_records(records)
    record_index = _build_record_index(parsed_records)
    output: list[ReviewDecision] = []
    source_ids: set[str] = set()
    cell_ids: set[str] = set()

    for event_index, raw_event in enumerate(workflow_decisions):
        event = _mapping(raw_event, label=f"workflow_decisions[{event_index}]")
        source_decision_id = _text(
            event,
            "decision_id",
            label=f"workflow_decisions[{event_index}]",
        )
        if source_decision_id in source_ids:
            raise DecisionCompileError(
                f"duplicate workflow decision_id {source_decision_id!r}"
            )
        source_ids.add(source_decision_id)
        source_decision_type = _text(
            event,
            "decision_type",
            label=source_decision_id,
        )
        if event.get("status") != "approved":
            raise DecisionCompileError(f"{source_decision_id} is not approved")
        target = _mapping(event.get("target"), label=f"{source_decision_id}.target")
        record = _locate_record(record_index, target, label=f"{source_decision_id}.target")

        if source_decision_type == "choose_candidate":
            compiled = _compile_choose_candidate(
                record,
                event,
                target,
                source_decision_id=source_decision_id,
                default_reviewer=default_reviewer,
                default_decided_at=default_decided_at,
            )
        elif source_decision_type == "accept_single_source_row":
            compiled = _compile_accept_single_source_row(
                record,
                event,
                source_decision_id=source_decision_id,
                default_reviewer=default_reviewer,
                default_decided_at=default_decided_at,
            )
        elif source_decision_type == "resolve_repeat_marker":
            compiled = _compile_resolve_repeat_marker(
                record,
                event,
                target,
                record_index,
                source_decision_id=source_decision_id,
                default_reviewer=default_reviewer,
                default_decided_at=default_decided_at,
            )
        else:
            raise DecisionCompileError(
                f"{source_decision_id} has unsupported decision_type {source_decision_type!r}"
            )

        duplicate_targets = sorted(
            decision.cell_id for decision in compiled if decision.cell_id in cell_ids
        )
        if duplicate_targets:
            raise DecisionCompileError(
                "workflow decisions target the same cell more than once: "
                + ", ".join(duplicate_targets)
            )
        cell_ids.update(decision.cell_id for decision in compiled)
        output.extend(compiled)

    return output


__all__ = ["DecisionCompileError", "compile_workflow_decisions"]
