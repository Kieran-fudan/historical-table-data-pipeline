"""File-oriented orchestration around the deterministic reconciliation core."""

from __future__ import annotations

import hashlib
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from historical_table_pipeline.alignment import AlignmentConfig, align_rows
from historical_table_pipeline.config import Profile, load_profile
from historical_table_pipeline.consensus import (
    ConsensusConfig,
    build_consensus,
    consensus_records_from_dicts,
)
from historical_table_pipeline.io import (
    canonical_json,
    read_jsonl,
    sha256_file,
    write_json,
    write_jsonl,
)
from historical_table_pipeline.manifest import create_manifest, write_manifest
from historical_table_pipeline.models import ConsensusRecord, ReviewDecision, RowInput
from historical_table_pipeline.normalization import NormalizationConfig
from historical_table_pipeline.review import (
    apply_decisions,
    collect_review_items,
)
from historical_table_pipeline.validation import validate_consensus


class WorkflowError(ValueError):
    """Raised when files cannot safely advance to the next workflow stage."""


def _mapping(value: Any, location: str) -> Mapping[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise WorkflowError(f"{location} must be a mapping")
    return value


def normalization_from_profile(profile: Profile) -> NormalizationConfig:
    raw = _mapping(profile.raw.get("comparison_normalization"), "comparison_normalization")
    return NormalizationConfig.from_mapping(raw)


def alignment_from_profile(profile: Profile) -> AlignmentConfig:
    raw = _mapping(profile.raw.get("alignment"), "alignment")
    anchor = raw.get("anchor_engine")
    return AlignmentConfig(
        field_weights=profile.alignment_weights,
        default_weight=float(raw.get("default_weight", 0.0)),
        gap_penalty=float(raw.get("gap_penalty", -0.4)),
        mismatch_penalty=float(raw.get("mismatch_penalty", -0.85)),
        minimum_match_similarity=float(raw.get("minimum_match_similarity", 0.45)),
        fuzzy_strings=bool(raw.get("fuzzy_strings", True)),
        anchor_engine=None if anchor in (None, "") else str(anchor),
    )


def consensus_from_profile(profile: Profile) -> ConsensusConfig:
    raw = _mapping(profile.raw.get("consensus"), "consensus")
    return ConsensusConfig(
        fields=profile.field_names,
        majority_fraction=float(raw.get("majority_fraction", 0.5)),
        minimum_majority_votes=int(raw.get("minimum_majority_votes", 2)),
    )


def _minimum_engines(profile: Profile) -> int:
    ocr = _mapping(profile.raw.get("ocr"), "ocr")
    return max(2, int(ocr.get("minimum_independent_engines", 2)))


def _page_index_required(profile: Profile) -> bool:
    identity = _mapping(profile.raw.get("page_identity"), "page_identity")
    rule = _mapping(identity.get("source_pdf_page_index"), "page_identity.source_pdf_page_index")
    return bool(rule.get("required", False))


def load_ocr_inputs(
    input_paths: Sequence[str | Path],
    profile: Profile,
) -> dict[str, list[RowInput]]:
    """Load, validate, and group canonical OCR rows by source engine."""

    if not input_paths:
        raise WorkflowError("at least two OCR input files are required")
    rows_by_engine: dict[str, list[RowInput]] = {}
    seen_rows: set[tuple[str, str, str, str, str]] = set()
    known_fields = set(profile.field_names)
    require_page_index = _page_index_required(profile)

    for raw_path in input_paths:
        path = Path(raw_path).expanduser().resolve()
        if not path.is_file():
            raise WorkflowError(f"OCR input does not exist: {path}")
        for line_number, payload in enumerate(read_jsonl(path), start=1):
            try:
                enriched_payload = dict(payload)
                metadata = dict(payload.get("metadata", {}))
                metadata.setdefault("input_artifact", path.name)
                metadata.setdefault("input_line_number", line_number)
                enriched_payload["metadata"] = metadata
                source_ref = payload.get("source_ref") or f"{path.name}:{line_number}"
                row = RowInput.from_dict(enriched_payload, source_ref=str(source_ref))
            except (TypeError, ValueError) as exc:
                raise WorkflowError(f"{path.name}:{line_number}: {exc}") from exc
            unknown = sorted(set(row.cells) - known_fields)
            if unknown:
                raise WorkflowError(
                    f"{path.name}:{line_number}: fields are not declared by the profile: "
                    + ", ".join(unknown)
                )
            if not row.engine_version:
                raise WorkflowError(
                    f"{path.name}:{line_number}: engine_version is required for provenance"
                )
            if require_page_index and row.source_pdf_page_index is None:
                raise WorkflowError(
                    f"{path.name}:{line_number}: source_pdf_page_index is required"
                )
            if row.source_pdf_page_index is not None and (
                isinstance(row.source_pdf_page_index, bool)
                or not isinstance(row.source_pdf_page_index, int)
                or row.source_pdf_page_index < 0
            ):
                raise WorkflowError(
                    f"{path.name}:{line_number}: source_pdf_page_index must be a "
                    "non-negative integer"
                )
            identity = (
                row.engine_id,
                row.document_id,
                row.page_id,
                row.table_id,
                canonical_json(row.source_row_index),
            )
            if identity in seen_rows:
                raise WorkflowError(
                    f"duplicate engine/document/page/table/source-row identity at "
                    f"{path.name}:{line_number}"
                )
            seen_rows.add(identity)
            rows_by_engine.setdefault(row.engine_id, []).append(row)

    minimum = _minimum_engines(profile)
    if len(rows_by_engine) < minimum:
        raise WorkflowError(
            f"profile requires at least {minimum} independently labeled sources; "
            f"found {len(rows_by_engine)}"
        )
    return dict(sorted(rows_by_engine.items()))


def _preliminary_summary(
    records: Sequence[ConsensusRecord],
    rows_by_engine: Mapping[str, Sequence[RowInput]],
) -> dict[str, Any]:
    cells = [cell for record in records for cell in record.cells.values()]
    statuses = Counter(cell.status.value for cell in cells)
    return {
        "schema_version": "1",
        "rows_by_engine": {
            engine: len(rows) for engine, rows in sorted(rows_by_engine.items())
        },
        "aligned_records": len(records),
        "cell_status_counts": dict(sorted(statuses.items())),
        "unresolved_cells": sum(not cell.is_resolved for cell in cells),
        "missing_source_rows": sum(bool(record.missing_engine_ids) for record in records),
        "claim_boundary": (
            "Agreement is internal consistency evidence, not an accuracy estimate "
            "against source images."
        ),
    }


def reconcile_files(
    profile_path: str | Path,
    input_paths: Sequence[str | Path],
    output_root: str | Path,
) -> dict[str, Any]:
    """Create a content-addressed reconciliation run and return its paths."""

    profile = load_profile(profile_path)
    resolved_inputs = [Path(path).expanduser().resolve() for path in input_paths]
    rows_by_engine = load_ocr_inputs(resolved_inputs, profile)
    normalization = normalization_from_profile(profile)
    alignment = alignment_from_profile(profile)
    consensus_config = consensus_from_profile(profile)
    parameters = {
        "command": "reconcile",
        "engine_ids": list(rows_by_engine),
        "comparison_normalization": profile.raw.get("comparison_normalization", {}),
        "alignment": {
            "field_weights": dict(alignment.field_weights),
            "default_weight": alignment.default_weight,
            "gap_penalty": alignment.gap_penalty,
            "mismatch_penalty": alignment.mismatch_penalty,
            "minimum_match_similarity": alignment.minimum_match_similarity,
            "fuzzy_strings": alignment.fuzzy_strings,
            "anchor_engine": alignment.anchor_engine,
        },
        "consensus": {
            "fields": list(consensus_config.fields),
            "majority_fraction": consensus_config.majority_fraction,
            "minimum_majority_votes": consensus_config.minimum_majority_votes,
        },
    }
    manifest = create_manifest(
        profile.path,
        resolved_inputs,
        parameters=parameters,
        relative_to=Path.cwd(),
    )
    run_dir = Path(output_root).expanduser().resolve() / manifest.run_id
    stage_dir = run_dir / "01-reconcile"
    stage_dir.mkdir(parents=True, exist_ok=True)

    groups = align_rows(
        rows_by_engine,
        normalization=normalization,
        config=alignment,
    )
    records = build_consensus(
        groups,
        expected_engine_ids=tuple(rows_by_engine),
        normalization=normalization,
        config=consensus_config,
    )
    manifest_path = run_dir / "manifest.json"
    if not manifest_path.exists():
        write_manifest(manifest_path, manifest)
    write_jsonl(stage_dir / "aligned-rows.jsonl", (group.to_dict() for group in groups))
    consensus_path = write_jsonl(
        stage_dir / "consensus.jsonl", (record.to_dict() for record in records)
    )
    review_items = collect_review_items(records)
    review_path = write_jsonl(
        stage_dir / "review-queue.jsonl", (item.to_dict() for item in review_items)
    )
    summary = _preliminary_summary(records, rows_by_engine)
    write_json(stage_dir / "reconciliation-summary.json", summary)
    write_json(stage_dir / "validation-report.json", validate_consensus(records, profile))
    return {
        "run_id": manifest.run_id,
        "run_directory": str(run_dir),
        "manifest": str(manifest_path),
        "consensus": str(consensus_path),
        "review_queue": str(review_path),
        **summary,
    }


def resolve_consensus_path(path: str | Path) -> Path:
    artifact = Path(path).expanduser().resolve()
    if artifact.is_file():
        return artifact
    if not artifact.is_dir():
        raise WorkflowError(f"consensus artifact does not exist: {artifact}")
    candidates = [
        artifact / "reviewed-consensus.jsonl",
        artifact / "01-reconcile" / "consensus.jsonl",
        artifact / "consensus.jsonl",
    ]
    matches = [candidate for candidate in candidates if candidate.is_file()]
    if len(matches) != 1:
        raise WorkflowError(
            "directory must contain exactly one recognized consensus artifact "
            "(reviewed-consensus.jsonl or 01-reconcile/consensus.jsonl)"
        )
    return matches[0]


def load_consensus(path: str | Path) -> tuple[Path, list[ConsensusRecord]]:
    artifact = resolve_consensus_path(path)
    try:
        records = consensus_records_from_dicts(list(read_jsonl(artifact)))
    except (KeyError, TypeError, ValueError) as exc:
        raise WorkflowError(f"invalid consensus artifact {artifact}: {exc}") from exc
    return artifact, records


def export_review(
    consensus_path: str | Path,
    output_dir: str | Path,
) -> dict[str, Any]:
    artifact, records = load_consensus(consensus_path)
    destination = Path(output_dir).expanduser().resolve()
    destination.mkdir(parents=True, exist_ok=True)
    items = collect_review_items(records)
    queue_path = write_jsonl(
        destination / "review-queue.jsonl", (item.to_dict() for item in items)
    )
    template_rows = [
        {
            "cell_id": item.cell.cell_id,
            "chosen_value": {"REPLACE_WITH_JSON_SCALAR": True},
            "reason": "REQUIRED: explain the evidence used",
            "reviewer": "REQUIRED: person or agent identifier",
            "decided_at": "REQUIRED: ISO-8601 timestamp",
            "metadata": {"source_consensus_sha256": sha256_file(artifact)},
        }
        for item in items
    ]
    template_path = write_jsonl(destination / "decision-template.jsonl", template_rows)
    summary = {
        "source_consensus": artifact.name,
        "source_consensus_sha256": sha256_file(artifact),
        "review_item_count": len(items),
        "review_queue": str(queue_path),
        "decision_template": str(template_path),
    }
    write_json(destination / "review-export.json", summary)
    return summary


def _load_or_compile_decisions(
    decision_path: Path,
    records: Sequence[ConsensusRecord],
    *,
    default_reviewer: str | None = None,
    default_decided_at: str | None = None,
) -> list[ReviewDecision]:
    payloads = list(read_jsonl(decision_path))
    if not payloads:
        raise WorkflowError("decision file is empty")
    try:
        if all("cell_id" in payload for payload in payloads):
            return [ReviewDecision.from_dict(payload) for payload in payloads]
        if all("decision_type" in payload for payload in payloads):
            from historical_table_pipeline.decision_compiler import compile_workflow_decisions

            return compile_workflow_decisions(
                records,
                payloads,
                default_reviewer=default_reviewer,
                default_decided_at=default_decided_at,
            )
    except (KeyError, TypeError, ValueError) as exc:
        raise WorkflowError(f"invalid decision file {decision_path}: {exc}") from exc
    raise WorkflowError(
        "decision file must contain either canonical cell decisions or workflow-level "
        "decision_type events, without mixing contracts"
    )


def apply_decision_file(
    consensus_path: str | Path,
    decision_path: str | Path,
    profile_path: str | Path,
    output_root: str | Path | None = None,
    *,
    default_reviewer: str | None = None,
    default_decided_at: str | None = None,
) -> dict[str, Any]:
    artifact, records = load_consensus(consensus_path)
    decisions_artifact = Path(decision_path).expanduser().resolve()
    if not decisions_artifact.is_file():
        raise WorkflowError(f"decision file does not exist: {decisions_artifact}")
    profile = load_profile(profile_path)
    decisions = _load_or_compile_decisions(
        decisions_artifact,
        records,
        default_reviewer=default_reviewer,
        default_decided_at=default_decided_at,
    )
    try:
        reviewed = apply_decisions(records, decisions, strict=True)
    except ValueError as exc:
        raise WorkflowError(f"decisions cannot be applied: {exc}") from exc
    identity = {
        "source_consensus_sha256": sha256_file(artifact),
        "compiled_decisions": [decision.to_dict() for decision in decisions],
        "profile_sha256": sha256_file(profile.path),
    }
    application_id = "apply_" + hashlib.sha256(
        canonical_json(identity).encode("utf-8")
    ).hexdigest()[:16]
    if output_root is None:
        root = (
            artifact.parent.parent / "02-review"
            if artifact.parent.name == "01-reconcile"
            else artifact.parent / "review-applications"
        )
    else:
        root = Path(output_root).expanduser().resolve()
    destination = root / application_id
    destination.mkdir(parents=True, exist_ok=True)
    compiled_path = write_jsonl(
        destination / "compiled-decisions.jsonl",
        (decision.to_dict() for decision in decisions),
    )
    reviewed_path = write_jsonl(
        destination / "reviewed-consensus.jsonl",
        (record.to_dict() for record in reviewed),
    )
    remaining = collect_review_items(reviewed)
    remaining_path = write_jsonl(
        destination / "remaining-review-queue.jsonl",
        (item.to_dict() for item in remaining),
    )
    report = validate_consensus(reviewed, profile)
    report_path = write_json(destination / "validation-report.json", report)
    application = {
        "schema_version": "1",
        "application_id": application_id,
        "source_consensus_sha256": sha256_file(artifact),
        "source_decisions_sha256": sha256_file(decisions_artifact),
        "profile_sha256": sha256_file(profile.path),
        "compiled_decision_count": len(decisions),
        "remaining_review_items": len(remaining),
        "reviewed_consensus_sha256": sha256_file(reviewed_path),
    }
    write_json(destination / "application.json", application)
    return {
        **application,
        "application_directory": str(destination),
        "compiled_decisions": str(compiled_path),
        "reviewed_consensus": str(reviewed_path),
        "remaining_review_queue": str(remaining_path),
        "validation_report": str(report_path),
        "ready_to_publish": report["ready_to_publish"],
    }


__all__ = [
    "WorkflowError",
    "alignment_from_profile",
    "apply_decision_file",
    "consensus_from_profile",
    "export_review",
    "load_consensus",
    "load_ocr_inputs",
    "normalization_from_profile",
    "reconcile_files",
    "resolve_consensus_path",
]
