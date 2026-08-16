"""Structural and provenance validation for reconciled consensus artifacts."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from typing import Any

from historical_table_pipeline.config import Profile
from historical_table_pipeline.models import (
    ConsensusRecord,
    stable_record_id_from_provenance,
)


def validate_consensus(
    records: Sequence[ConsensusRecord],
    profile: Profile,
) -> dict[str, Any]:
    """Return a deterministic validation report without changing artifacts.

    Unresolved cells are reported separately from structural errors. Callers
    decide whether their workflow permits publishing unresolved evidence.
    """

    errors: list[str] = []
    warnings: list[str] = []
    record_ids: set[str] = set()
    cell_ids: set[str] = set()
    candidate_ids: set[str] = set()
    status_counts: Counter[str] = Counter()
    unresolved_targets: list[dict[str, str]] = []
    missing_source_records = 0
    require_page_index = bool(
        profile.raw.get("quality", {}).get("require_complete_page_identity", False)
    )

    for record in records:
        record_section = (record.document_id, record.page_id, record.table_id)
        if record.record_id in record_ids:
            errors.append(f"duplicate record_id: {record.record_id}")
        record_ids.add(record.record_id)
        anchor_sources = [
            source
            for source in record.sources
            if source.engine_id == record.anchor_engine_id
        ]
        if len(anchor_sources) != 1:
            errors.append(
                f"{record.record_id}: anchor_engine_id does not select exactly one source"
            )
        elif stable_record_id_from_provenance(anchor_sources[0]) != record.record_id:
            errors.append(f"{record.record_id}: record_id does not match anchor provenance")
        if record.missing_engine_ids:
            missing_source_records += 1

        physical_pages = {
            source.source_pdf_page_index
            for source in record.sources
            if source.source_pdf_page_index is not None
        }
        if len(physical_pages) > 1:
            errors.append(
                f"{record.record_id}: sources disagree on source_pdf_page_index"
            )
        printed_labels = {
            source.printed_page_label
            for source in record.sources
            if source.printed_page_label is not None
        }
        if len(printed_labels) > 1:
            errors.append(f"{record.record_id}: sources disagree on printed_page_label")

        missing_fields = set(profile.field_names) - set(record.cells)
        extra_fields = set(record.cells) - set(profile.field_names)
        if missing_fields:
            errors.append(
                f"{record.record_id}: missing profile fields: "
                + ", ".join(sorted(missing_fields))
            )
        if extra_fields:
            errors.append(
                f"{record.record_id}: undeclared fields: "
                + ", ".join(sorted(extra_fields))
            )

        for source in record.sources:
            source_section = (source.document_id, source.page_id, source.table_id)
            if source_section != record_section:
                errors.append(
                    f"{record.record_id}: source section does not match consensus record"
                )
            if require_page_index and source.source_pdf_page_index is None:
                errors.append(
                    f"{record.record_id}: source {source.engine_id}:"
                    f"{source.source_row_index} lacks source_pdf_page_index"
                )

        for field_name, cell in record.cells.items():
            status_counts[cell.status.value] += 1
            if cell.cell_id in cell_ids:
                errors.append(f"duplicate cell_id: {cell.cell_id}")
            cell_ids.add(cell.cell_id)
            if field_name != cell.field:
                errors.append(
                    f"{record.record_id}: field mapping {field_name!r} does not match cell"
                )
            if not cell.is_resolved:
                unresolved_targets.append(
                    {
                        "record_id": record.record_id,
                        "cell_id": cell.cell_id,
                        "field": field_name,
                        "status": cell.status.value,
                    }
                )
            for candidate in cell.candidates:
                if candidate.candidate_id in candidate_ids:
                    errors.append(f"duplicate candidate_id: {candidate.candidate_id}")
                candidate_ids.add(candidate.candidate_id)
                if candidate.field != field_name:
                    errors.append(
                        f"{cell.cell_id}: candidate {candidate.candidate_id} has wrong field"
                    )
                provenance = candidate.provenance
                candidate_section = (
                    provenance.document_id,
                    provenance.page_id,
                    provenance.table_id,
                )
                if candidate_section != record_section:
                    errors.append(
                        f"{cell.cell_id}: candidate {candidate.candidate_id} has wrong section"
                    )

    if not records:
        warnings.append("consensus artifact contains no records")

    return {
        "schema_version": "1",
        "structurally_valid": not errors,
        "ready_to_publish": not errors and not unresolved_targets,
        "record_count": len(records),
        "cell_count": sum(status_counts.values()),
        "status_counts": dict(sorted(status_counts.items())),
        "missing_source_records": missing_source_records,
        "unresolved_cell_count": len(unresolved_targets),
        "unresolved_targets": unresolved_targets,
        "errors": errors,
        "warnings": warnings,
        "claim_boundary": (
            "Passing structural checks and multi-source agreement do not establish "
            "accuracy against the scanned source."
        ),
    }


__all__ = ["validate_consensus"]
