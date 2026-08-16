"""Build auditable multi-engine consensus from aligned source rows."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .alignment import AlignmentConfig, align_rows
from .models import (
    AlignedRowGroup,
    CellCandidate,
    ConsensusCell,
    ConsensusRecord,
    ConsensusStatus,
    JsonScalar,
    RowInput,
    stable_cell_id,
)
from .normalization import NormalizationConfig, Normalizer


@dataclass(frozen=True, slots=True)
class ConsensusConfig:
    """Voting and output-field settings.

    ``fields`` can declare schema fields even when every engine leaves one
    absent.  A strict majority is required; ties remain conflicts.
    """

    fields: tuple[str, ...] = ()
    majority_fraction: float = 0.5
    minimum_majority_votes: int = 2

    def __post_init__(self) -> None:
        if not 0.5 <= self.majority_fraction < 1:
            raise ValueError("majority_fraction must be in [0.5, 1)")
        if self.minimum_majority_votes < 1:
            raise ValueError("minimum_majority_votes must be positive")
        if len(self.fields) != len(set(self.fields)):
            raise ValueError("consensus fields must be unique")
        object.__setattr__(self, "fields", tuple(str(name) for name in self.fields))


def _vote_key(value: JsonScalar) -> tuple[str, str]:
    # bool and int must not collapse into the same Python dictionary key.
    return (
        type(value).__name__,
        json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False),
    )


def _classify_cell(
    candidates: Sequence[CellCandidate],
    *,
    expected_engine_ids: Sequence[str],
    config: ConsensusConfig,
) -> tuple[ConsensusStatus, JsonScalar, tuple[str, ...], tuple[str, ...]]:
    nonmissing = [candidate for candidate in candidates if candidate.normalized_value is not None]
    present_engines = {candidate.provenance.engine_id for candidate in candidates}
    missing_engines = tuple(
        engine for engine in expected_engine_ids if engine not in present_engines
    )
    if not nonmissing:
        # A source-visible blank is still an observation. When two or more
        # expected engines independently report values that normalize to the
        # configured missing sentinel, they agree on absence; do not route
        # that cell to review merely because its chosen value is null.
        if len(candidates) >= 2:
            return (
                ConsensusStatus.UNANIMOUS,
                None,
                tuple(candidate.candidate_id for candidate in candidates),
                missing_engines,
            )
        if len(candidates) == 1 and len(expected_engine_ids) == 1:
            return (
                ConsensusStatus.UNANIMOUS,
                None,
                (candidates[0].candidate_id,),
                missing_engines,
            )
        return ConsensusStatus.MISSING, None, (), missing_engines

    counts = Counter(_vote_key(candidate.normalized_value) for candidate in nonmissing)
    first_value: dict[tuple[str, str], JsonScalar] = {}
    for candidate in nonmissing:
        first_value.setdefault(_vote_key(candidate.normalized_value), candidate.normalized_value)
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    winning_key, winning_count = ranked[0]
    chosen = first_value[winning_key]
    supporters = tuple(
        candidate.candidate_id
        for candidate in candidates
        if candidate.normalized_value is not None
        and _vote_key(candidate.normalized_value) == winning_key
    )

    if len(counts) == 1:
        # One source cannot establish multisource agreement when the caller
        # explicitly expects other engines.  Keep its value, but route it to
        # review under the missing status.
        if len(nonmissing) == 1 and len(expected_engine_ids) > 1:
            return ConsensusStatus.MISSING, chosen, supporters, missing_engines
        return ConsensusStatus.UNANIMOUS, chosen, supporters, missing_engines

    required = max(
        config.minimum_majority_votes,
        int(len(nonmissing) * config.majority_fraction) + 1,
    )
    if winning_count >= required:
        return ConsensusStatus.MAJORITY, chosen, supporters, missing_engines
    return ConsensusStatus.CONFLICT, None, (), missing_engines


def _resolve_expected_engines(
    groups: Sequence[AlignedRowGroup], expected_engine_ids: Sequence[str] | None
) -> tuple[str, ...]:
    if expected_engine_ids is None:
        return tuple(sorted({row.engine_id for group in groups for row in group.rows}))
    engines = tuple(str(engine) for engine in expected_engine_ids)
    if not engines or any(not engine for engine in engines):
        raise ValueError("expected_engines must contain non-empty names")
    if len(engines) != len(set(engines)):
        raise ValueError("expected_engines must be unique")
    observed = {row.engine_id for group in groups for row in group.rows}
    unknown = sorted(observed - set(engines))
    if unknown:
        raise ValueError(f"aligned rows contain unexpected engines: {', '.join(unknown)}")
    return engines


def build_consensus(
    groups: Sequence[AlignedRowGroup],
    *,
    expected_engine_ids: Sequence[str] | None = None,
    normalization: NormalizationConfig | Mapping[str, Any] | Normalizer | None = None,
    config: ConsensusConfig | None = None,
) -> list[ConsensusRecord]:
    """Turn aligned rows into cell-level consensus records.

    Status semantics:

    * ``unanimous``: every non-missing observation agrees (at least two when
      multiple engines are expected);
    * ``majority``: a strict configured majority agrees;
    * ``conflict``: two or more values have no strict majority;
    * ``missing``: no value exists, or only one value exists while multiple
      engines were explicitly/inferred as expected.

    Partial absence alongside two agreeing values remains unanimous and is
    exposed separately in ``missing_engines``.
    """

    groups = list(groups)
    engines = _resolve_expected_engines(groups, expected_engine_ids)
    config = config or ConsensusConfig()
    if isinstance(normalization, Normalizer):
        normalizer = normalization
    else:
        normalizer = Normalizer(normalization)

    output: list[ConsensusRecord] = []
    for group in groups:
        normalized_by_engine = {
            row.engine_id: normalizer.normalize_row(row) for row in group.rows
        }
        fields = list(config.fields)
        additional_fields = sorted(
            {
                field_name
                for normalized in normalized_by_engine.values()
                for field_name in normalized
            }
            - set(fields)
        )
        fields.extend(additional_fields)
        cells: dict[str, ConsensusCell] = {}
        for field_name in fields:
            candidates: list[CellCandidate] = []
            for row in sorted(group.rows, key=lambda item: item.engine_id):
                observation = normalized_by_engine[row.engine_id].get(field_name)
                if observation is None:
                    continue
                candidates.append(
                    CellCandidate.create(
                        record_id=group.record_id,
                        field=field_name,
                        source_field=observation.source_field,
                        raw_value=observation.raw_value,
                        normalized_value=observation.normalized_value,
                        provenance=row.provenance,
                    )
                )
            status, chosen, supporters, missing = _classify_cell(
                candidates,
                expected_engine_ids=engines,
                config=config,
            )
            cells[field_name] = ConsensusCell(
                cell_id=stable_cell_id(group.record_id, field_name),
                field=field_name,
                status=status,
                chosen_value=chosen,
                candidates=tuple(candidates),
                supporting_candidate_ids=supporters,
                missing_engine_ids=missing,
            )
        present_engines = {row.engine_id for row in group.rows}
        record_missing = tuple(engine for engine in engines if engine not in present_engines)
        output.append(
            ConsensusRecord(
                record_id=group.record_id,
                document_id=group.document_id,
                page_id=group.page_id,
                table_id=group.table_id,
                ordinal=group.ordinal,
                sources=tuple(
                    row.provenance for row in sorted(group.rows, key=lambda item: item.engine_id)
                ),
                cells=cells,
                missing_engine_ids=record_missing,
                anchor_engine_id=group.anchor_engine_id,
            )
        )
    return output


def reconcile_sources(
    rows_by_engine: Mapping[str, Sequence[RowInput | Mapping[str, Any]]],
    *,
    normalization: NormalizationConfig | Mapping[str, Any] | Normalizer | None = None,
    alignment_config: AlignmentConfig | None = None,
    consensus_config: ConsensusConfig | None = None,
) -> list[ConsensusRecord]:
    """Convenience API for alignment followed by consensus construction."""

    groups = align_rows(
        rows_by_engine,
        normalization=normalization,
        config=alignment_config,
    )
    return build_consensus(
        groups,
        expected_engine_ids=tuple(rows_by_engine),
        normalization=normalization,
        config=consensus_config,
    )


def consensus_records_from_dicts(
    payloads: Sequence[Mapping[str, Any]],
) -> list[ConsensusRecord]:
    """Losslessly reload consensus JSON objects written between CLI stages."""

    return [ConsensusRecord.from_dict(payload) for payload in payloads]


__all__ = [
    "ConsensusConfig",
    "build_consensus",
    "consensus_records_from_dicts",
    "reconcile_sources",
]
