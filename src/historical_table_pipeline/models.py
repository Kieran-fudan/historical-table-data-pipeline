"""Lossless data models for auditable multi-source reconciliation."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from hashlib import sha256
from typing import Any

JsonScalar = str | int | float | bool | None
JsonValue = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def stable_id(prefix: str, *parts: Any, length: int = 24) -> str:
    """Build a compact deterministic identifier from JSON-compatible parts."""

    digest = sha256(_canonical_json(parts).encode()).hexdigest()[:length]
    return f"{prefix}_{digest}"


def _validate_scalar(value: Any, *, label: str, allow_none: bool = True) -> None:
    if value is None and allow_none:
        return
    if not isinstance(value, (str, int, float, bool)) or value is None:
        raise TypeError(f"{label} must be a JSON scalar")
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError(f"{label} must not be NaN or infinity")


def _validate_json(value: Any, *, label: str) -> None:
    try:
        _canonical_json(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be finite JSON-compatible data") from exc


def _first(payload: Mapping[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        if key in payload:
            return payload[key]
    return default


@dataclass(frozen=True, slots=True)
class Provenance:
    """Full origin of one engine's logical source row."""

    document_id: str
    page_id: str
    table_id: str
    engine_id: str
    source_row_index: JsonScalar
    engine_version: str | None = None
    source_pdf_page_index: JsonScalar = None
    printed_page_label: str | None = None
    source_ref: str | None = None
    metadata: Mapping[str, JsonValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("document_id", "page_id", "table_id", "engine_id"):
            if not getattr(self, name):
                raise ValueError(f"{name} must be a non-empty string")
        _validate_scalar(self.source_row_index, label="source_row_index", allow_none=False)
        _validate_scalar(self.source_pdf_page_index, label="source_pdf_page_index")
        _validate_json(dict(self.metadata), label="metadata")
        object.__setattr__(self, "metadata", dict(self.metadata))

    @property
    def engine(self) -> str:
        return self.engine_id

    @property
    def document(self) -> str:
        return self.document_id

    @property
    def page(self) -> str:
        return self.page_id

    @property
    def table(self) -> str:
        return self.table_id

    @property
    def source_row(self) -> str:
        return str(self.source_row_index)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> Provenance:
        return cls(
            document_id=str(_first(payload, "document_id", "document", default="")),
            page_id=str(_first(payload, "page_id", "page", default="")),
            table_id=str(_first(payload, "table_id", "table", default="")),
            engine_id=str(_first(payload, "engine_id", "engine", default="")),
            source_row_index=_first(payload, "source_row_index", "source_row"),
            engine_version=_first(payload, "engine_version"),
            source_pdf_page_index=_first(payload, "source_pdf_page_index"),
            printed_page_label=_first(payload, "printed_page_label"),
            source_ref=_first(payload, "source_ref"),
            metadata=payload.get("metadata", {}),
        )

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "document_id": self.document_id,
            "page_id": self.page_id,
            "source_pdf_page_index": self.source_pdf_page_index,
            "printed_page_label": self.printed_page_label,
            "table_id": self.table_id,
            "engine_id": self.engine_id,
            "engine_version": self.engine_version,
            "source_row_index": self.source_row_index,
            "source_ref": self.source_ref,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class RowInput:
    """One logical table row from one extraction engine.

    The canonical public keys are the long ``*_id``/``*_index`` names.  The
    loader accepts the earlier short aliases, but :meth:`to_dict` always emits
    the single canonical contract.
    """

    document_id: str
    page_id: str
    table_id: str
    engine_id: str
    source_row_index: JsonScalar
    cells: Mapping[str, JsonScalar]
    engine_version: str | None = None
    source_pdf_page_index: JsonScalar = None
    printed_page_label: str | None = None
    source_ref: str | None = None
    metadata: Mapping[str, JsonValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        provenance = self.provenance
        if not isinstance(self.cells, Mapping):
            raise TypeError("cells must be a mapping of field names to JSON scalars")
        clean_cells: dict[str, JsonScalar] = {}
        for name, value in self.cells.items():
            if not isinstance(name, str) or not name:
                raise ValueError("cell field names must be non-empty strings")
            _validate_scalar(value, label=f"cells[{name!r}]")
            clean_cells[name] = value
        object.__setattr__(self, "cells", clean_cells)
        object.__setattr__(self, "metadata", dict(provenance.metadata))

    @property
    def engine(self) -> str:
        return self.engine_id

    @property
    def document(self) -> str:
        return self.document_id

    @property
    def page(self) -> str:
        return self.page_id

    @property
    def table(self) -> str:
        return self.table_id

    @property
    def source_row(self) -> str:
        return str(self.source_row_index)

    @property
    def provenance(self) -> Provenance:
        return Provenance(
            document_id=self.document_id,
            page_id=self.page_id,
            table_id=self.table_id,
            engine_id=self.engine_id,
            source_row_index=self.source_row_index,
            engine_version=self.engine_version,
            source_pdf_page_index=self.source_pdf_page_index,
            printed_page_label=self.printed_page_label,
            source_ref=self.source_ref,
            metadata=self.metadata,
        )

    @property
    def section_key(self) -> tuple[str, str, str]:
        return (self.document_id, self.page_id, self.table_id)

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, Any],
        *,
        engine_id: str | None = None,
        engine: str | None = None,
        source_ref: str | None = None,
    ) -> RowInput:
        aliases = {
            "document_id": ("document_id", "document"),
            "page_id": ("page_id", "page"),
            "table_id": ("table_id", "table"),
            "source_row_index": (
                "source_row_index",
                "source_row",
                "source_row_id",
                "row_index",
                "row_number",
            ),
        }
        missing = [name for name, keys in aliases.items() if _first(payload, *keys) is None]
        if "cells" not in payload:
            missing.append("cells")
        if missing:
            raise ValueError(f"row is missing required fields: {', '.join(missing)}")
        resolved_engine = (
            engine_id
            or engine
            or _first(payload, "engine_id", "engine", "source_engine")
        )
        if not resolved_engine:
            raise ValueError("row requires engine_id (in the object or from the loader)")
        known = {
            "document_id",
            "document",
            "page_id",
            "page",
            "table_id",
            "table",
            "source_row_index",
            "source_row",
            "source_row_id",
            "row_index",
            "row_number",
            "cells",
            "engine_id",
            "engine",
            "source_engine",
            "engine_version",
            "source_pdf_page_index",
            "printed_page_label",
            "source_ref",
            "metadata",
        }
        metadata = dict(payload.get("metadata", {}))
        metadata.update({str(key): value for key, value in payload.items() if key not in known})
        resolved_ref = source_ref if source_ref is not None else payload.get("source_ref")
        return cls(
            document_id=str(_first(payload, *aliases["document_id"])),
            page_id=str(_first(payload, *aliases["page_id"])),
            table_id=str(_first(payload, *aliases["table_id"])),
            engine_id=str(resolved_engine),
            source_row_index=_first(payload, *aliases["source_row_index"]),
            cells=payload["cells"],
            engine_version=(
                None if payload.get("engine_version") is None else str(payload["engine_version"])
            ),
            source_pdf_page_index=payload.get("source_pdf_page_index"),
            printed_page_label=(
                None
                if payload.get("printed_page_label") is None
                else str(payload["printed_page_label"])
            ),
            source_ref=None if resolved_ref is None else str(resolved_ref),
            metadata=metadata,
        )

    def to_dict(self) -> dict[str, JsonValue]:
        result = self.provenance.to_dict()
        result["cells"] = dict(self.cells)
        return result


def stable_record_id(rows: Sequence[RowInput], *, anchor_engine: str | None = None) -> str:
    """Derive identity from the group's founding/explicit anchor row only."""

    if not rows:
        raise ValueError("a record ID requires at least one source row")
    section = rows[0].section_key
    if any(row.section_key != section for row in rows):
        raise ValueError("all aligned rows must belong to one document/page/table")
    if anchor_engine is None:
        anchor = rows[0]
    else:
        matches = [row for row in rows if row.engine_id == anchor_engine]
        if not matches:
            raise ValueError(f"anchor engine {anchor_engine!r} is absent from aligned rows")
        anchor = matches[0]
    return stable_record_id_from_provenance(anchor.provenance)


def stable_record_id_from_provenance(provenance: Provenance) -> str:
    """Derive a record ID from the immutable identity of one anchor row."""

    return stable_id(
        "rec",
        provenance.document_id,
        provenance.page_id,
        provenance.table_id,
        provenance.engine_id,
        provenance.source_row_index,
        provenance.source_pdf_page_index,
    )


def stable_cell_id(record_id: str, field_name: str) -> str:
    return stable_id("cell", record_id, field_name)


@dataclass(frozen=True, slots=True)
class AlignedRowGroup:
    document_id: str
    page_id: str
    table_id: str
    ordinal: int
    rows: tuple[RowInput, ...]
    anchor_engine_id: str = ""
    record_id: str = ""

    def __post_init__(self) -> None:
        if not self.rows:
            raise ValueError("an aligned group must contain at least one row")
        section = (self.document_id, self.page_id, self.table_id)
        if any(row.section_key != section for row in self.rows):
            raise ValueError("aligned rows must share document/page/table")
        engines = [row.engine_id for row in self.rows]
        if len(engines) != len(set(engines)):
            raise ValueError("an aligned group may contain at most one row per engine")
        anchor_engine = self.anchor_engine_id or self.rows[0].engine_id
        if anchor_engine not in engines:
            raise ValueError("anchor_engine_id is absent from aligned rows")
        expected = stable_record_id(self.rows, anchor_engine=anchor_engine)
        if self.record_id and self.record_id != expected:
            raise ValueError("record_id does not match anchor-row provenance")
        object.__setattr__(self, "anchor_engine_id", anchor_engine)
        object.__setattr__(self, "record_id", expected)

    @property
    def document(self) -> str:
        return self.document_id

    @property
    def page(self) -> str:
        return self.page_id

    @property
    def table(self) -> str:
        return self.table_id

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> AlignedRowGroup:
        return cls(
            document_id=str(_first(payload, "document_id", "document", default="")),
            page_id=str(_first(payload, "page_id", "page", default="")),
            table_id=str(_first(payload, "table_id", "table", default="")),
            ordinal=int(payload["ordinal"]),
            rows=tuple(RowInput.from_dict(row) for row in payload["rows"]),
            anchor_engine_id=str(payload.get("anchor_engine_id", "")),
            record_id=str(payload.get("record_id", "")),
        )

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "record_id": self.record_id,
            "document_id": self.document_id,
            "page_id": self.page_id,
            "table_id": self.table_id,
            "ordinal": self.ordinal,
            "anchor_engine_id": self.anchor_engine_id,
            "rows": [row.to_dict() for row in self.rows],
        }


class ConsensusStatus(StrEnum):
    UNANIMOUS = "unanimous"
    MAJORITY = "majority"
    CONFLICT = "conflict"
    MISSING = "missing"


@dataclass(frozen=True, slots=True)
class CellCandidate:
    candidate_id: str
    field: str
    source_field: str
    raw_value: JsonScalar
    normalized_value: JsonScalar
    provenance: Provenance

    @classmethod
    def create(
        cls,
        *,
        record_id: str,
        field: str,
        source_field: str,
        raw_value: JsonScalar,
        normalized_value: JsonScalar,
        provenance: Provenance,
    ) -> CellCandidate:
        _validate_scalar(raw_value, label="raw_value")
        _validate_scalar(normalized_value, label="normalized_value")
        return cls(
            candidate_id=stable_id(
                "cand",
                record_id,
                field,
                source_field,
                raw_value,
                provenance.to_dict(),
            ),
            field=field,
            source_field=source_field,
            raw_value=raw_value,
            normalized_value=normalized_value,
            provenance=provenance,
        )

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> CellCandidate:
        return cls(
            candidate_id=str(payload["candidate_id"]),
            field=str(payload["field"]),
            source_field=str(payload.get("source_field", payload["field"])),
            raw_value=payload.get("raw_value"),
            normalized_value=payload.get("normalized_value"),
            provenance=Provenance.from_dict(payload["provenance"]),
        )

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "candidate_id": self.candidate_id,
            "field": self.field,
            "source_field": self.source_field,
            "raw_value": self.raw_value,
            "normalized_value": self.normalized_value,
            "provenance": self.provenance.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class ReviewDecision:
    """One replayable cell decision using the canonical public contract."""

    cell_id: str
    chosen_value: JsonScalar
    reason: str
    reviewer: str
    decided_at: str
    decision_id: str = ""
    candidate_id: str | None = None
    metadata: Mapping[str, JsonValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.cell_id:
            raise ValueError("cell_id is required")
        _validate_scalar(self.chosen_value, label="chosen_value")
        if not self.reason or not self.reviewer or not self.decided_at:
            raise ValueError("reason, reviewer, and decided_at are required")
        _validate_json(dict(self.metadata), label="decision metadata")
        decision_id = self.decision_id or stable_id(
            "dec",
            self.cell_id,
            self.chosen_value,
            self.candidate_id,
            self.reason,
            self.reviewer,
        )
        object.__setattr__(self, "decision_id", decision_id)
        object.__setattr__(self, "metadata", dict(self.metadata))

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> ReviewDecision:
        missing = [
            name
            for name in ("cell_id", "chosen_value", "reason", "reviewer", "decided_at")
            if name not in payload
        ]
        if missing:
            raise ValueError(f"decision is missing required fields: {', '.join(missing)}")
        return cls(
            decision_id=str(payload.get("decision_id", "")),
            cell_id=str(payload["cell_id"]),
            chosen_value=payload["chosen_value"],
            candidate_id=(
                None if payload.get("candidate_id") is None else str(payload["candidate_id"])
            ),
            reason=str(payload["reason"]),
            reviewer=str(payload["reviewer"]),
            decided_at=str(payload["decided_at"]),
            metadata=payload.get("metadata", {}),
        )

    def to_dict(self) -> dict[str, JsonValue]:
        result: dict[str, JsonValue] = {
            "decision_id": self.decision_id,
            "cell_id": self.cell_id,
            "chosen_value": self.chosen_value,
            "reason": self.reason,
            "reviewer": self.reviewer,
            "decided_at": self.decided_at,
            "metadata": dict(self.metadata),
        }
        if self.candidate_id is not None:
            result["candidate_id"] = self.candidate_id
        return result


@dataclass(frozen=True, slots=True)
class ConsensusCell:
    cell_id: str
    field: str
    status: ConsensusStatus
    chosen_value: JsonScalar
    candidates: tuple[CellCandidate, ...]
    supporting_candidate_ids: tuple[str, ...] = ()
    missing_engine_ids: tuple[str, ...] = ()
    decision: ReviewDecision | None = None

    @property
    def missing_engines(self) -> tuple[str, ...]:
        return self.missing_engine_ids

    @property
    def is_resolved(self) -> bool:
        return self.status in (ConsensusStatus.UNANIMOUS, ConsensusStatus.MAJORITY) or (
            self.decision is not None
        )

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> ConsensusCell:
        decision = payload.get("decision")
        return cls(
            cell_id=str(payload["cell_id"]),
            field=str(payload["field"]),
            status=ConsensusStatus(payload["status"]),
            chosen_value=payload.get("chosen_value"),
            candidates=tuple(CellCandidate.from_dict(item) for item in payload["candidates"]),
            supporting_candidate_ids=tuple(payload.get("supporting_candidate_ids", ())),
            missing_engine_ids=tuple(
                payload.get("missing_engine_ids", payload.get("missing_engines", ()))
            ),
            decision=None if decision is None else ReviewDecision.from_dict(decision),
        )

    def to_dict(self) -> dict[str, JsonValue]:
        result: dict[str, JsonValue] = {
            "cell_id": self.cell_id,
            "field": self.field,
            "status": self.status.value,
            "chosen_value": self.chosen_value,
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "supporting_candidate_ids": list(self.supporting_candidate_ids),
            "missing_engine_ids": list(self.missing_engine_ids),
            "resolved": self.is_resolved,
        }
        if self.decision is not None:
            result["decision"] = self.decision.to_dict()
        return result


@dataclass(frozen=True, slots=True)
class ConsensusRecord:
    record_id: str
    document_id: str
    page_id: str
    table_id: str
    ordinal: int
    sources: tuple[Provenance, ...]
    cells: Mapping[str, ConsensusCell]
    missing_engine_ids: tuple[str, ...] = ()
    anchor_engine_id: str = ""

    def __post_init__(self) -> None:
        if not self.sources:
            raise ValueError("consensus record must retain at least one source row")
        engines = [source.engine_id for source in self.sources]
        if len(engines) != len(set(engines)):
            raise ValueError("consensus record may contain at most one row per engine")
        anchor_engine = self.anchor_engine_id or self.sources[0].engine_id
        if anchor_engine not in engines:
            raise ValueError("anchor_engine_id is absent from consensus sources")
        for field_name, cell in self.cells.items():
            if field_name != cell.field:
                raise ValueError("consensus cell mapping keys must equal cell.field")
            if cell.cell_id != stable_cell_id(self.record_id, field_name):
                raise ValueError("consensus cell ID does not match record and field")
        object.__setattr__(self, "cells", dict(self.cells))
        object.__setattr__(self, "anchor_engine_id", anchor_engine)

    @property
    def document(self) -> str:
        return self.document_id

    @property
    def page(self) -> str:
        return self.page_id

    @property
    def table(self) -> str:
        return self.table_id

    @property
    def missing_engines(self) -> tuple[str, ...]:
        return self.missing_engine_ids

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> ConsensusRecord:
        raw_cells = payload["cells"]
        return cls(
            record_id=str(payload["record_id"]),
            document_id=str(_first(payload, "document_id", "document", default="")),
            page_id=str(_first(payload, "page_id", "page", default="")),
            table_id=str(_first(payload, "table_id", "table", default="")),
            ordinal=int(payload["ordinal"]),
            sources=tuple(Provenance.from_dict(item) for item in payload["sources"]),
            cells={str(name): ConsensusCell.from_dict(cell) for name, cell in raw_cells.items()},
            missing_engine_ids=tuple(
                payload.get("missing_engine_ids", payload.get("missing_engines", ()))
            ),
            anchor_engine_id=str(payload.get("anchor_engine_id", "")),
        )

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "record_id": self.record_id,
            "document_id": self.document_id,
            "page_id": self.page_id,
            "table_id": self.table_id,
            "ordinal": self.ordinal,
            "anchor_engine_id": self.anchor_engine_id,
            "sources": [source.to_dict() for source in self.sources],
            "missing_engine_ids": list(self.missing_engine_ids),
            "cells": {
                field_name: cell.to_dict()
                for field_name, cell in sorted(self.cells.items())
            },
        }


__all__ = [
    "AlignedRowGroup",
    "CellCandidate",
    "ConsensusCell",
    "ConsensusRecord",
    "ConsensusStatus",
    "JsonScalar",
    "JsonValue",
    "Provenance",
    "ReviewDecision",
    "RowInput",
    "stable_cell_id",
    "stable_id",
    "stable_record_id",
    "stable_record_id_from_provenance",
]
