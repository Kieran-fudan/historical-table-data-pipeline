"""Order-preserving, weighted alignment of rows from independent engines."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any

from .models import AlignedRowGroup, JsonScalar, RowInput
from .normalization import NormalizationConfig, Normalizer


@dataclass(frozen=True, slots=True)
class AlignmentConfig:
    """Scoring parameters for progressive Needleman-Wunsch alignment.

    If ``field_weights`` is empty, all comparable fields have weight 1.  If it
    is non-empty, unspecified fields use ``default_weight`` (zero by default),
    allowing profiles to identify stable row anchors explicitly.
    """

    field_weights: Mapping[str, float] = field(default_factory=dict)
    default_weight: float = 0.0
    gap_penalty: float = -0.4
    mismatch_penalty: float = -0.85
    minimum_match_similarity: float = 0.45
    fuzzy_strings: bool = True
    anchor_engine: str | None = None

    def __post_init__(self) -> None:
        weights = {str(name): float(weight) for name, weight in self.field_weights.items()}
        if any(weight < 0 for weight in weights.values()):
            raise ValueError("field weights must be non-negative")
        if self.default_weight < 0:
            raise ValueError("default_weight must be non-negative")
        if not 0 <= self.minimum_match_similarity <= 1:
            raise ValueError("minimum_match_similarity must be between 0 and 1")
        if self.gap_penalty > 0 or self.mismatch_penalty > 0:
            raise ValueError("gap and mismatch penalties must be non-positive")
        if self.anchor_engine is not None and not self.anchor_engine:
            raise ValueError("anchor_engine must be non-empty when provided")
        object.__setattr__(self, "field_weights", weights)

    def weight_for(self, field_name: str) -> float:
        if not self.field_weights:
            return 1.0
        return self.field_weights.get(field_name, self.default_weight)


def _value_similarity(left: JsonScalar, right: JsonScalar, *, fuzzy: bool) -> float:
    if left == right and type(left) is type(right):
        return 1.0
    if left is None or right is None:
        return 0.0
    if isinstance(left, str) and isinstance(right, str) and fuzzy:
        return SequenceMatcher(None, left, right, autojunk=False).ratio()
    return 0.0


def row_similarity(
    left: RowInput,
    right: RowInput,
    *,
    normalizer: Normalizer | None = None,
    config: AlignmentConfig | None = None,
) -> float:
    """Return weighted similarity in [0, 1] over non-missing shared fields."""

    if left.section_key != right.section_key:
        return 0.0
    normalizer = normalizer or Normalizer()
    config = config or AlignmentConfig()
    left_cells = normalizer.normalize_row(left)
    right_cells = normalizer.normalize_row(right)
    shared = left_cells.keys() & right_cells.keys()
    numerator = 0.0
    denominator = 0.0
    for field_name in sorted(shared):
        left_value = left_cells[field_name].normalized_value
        right_value = right_cells[field_name].normalized_value
        if left_value is None or right_value is None:
            continue
        weight = config.weight_for(field_name)
        if weight <= 0:
            continue
        denominator += weight
        numerator += weight * _value_similarity(
            left_value, right_value, fuzzy=config.fuzzy_strings
        )
    return numerator / denominator if denominator else 0.0


def _group_similarity(
    group: Sequence[RowInput],
    incoming: RowInput,
    *,
    normalizer: Normalizer,
    config: AlignmentConfig,
) -> float:
    # Maximum linkage keeps a valid match available when one previous OCR
    # engine is noisy; consensus, not alignment, later decides the value.
    return max(
        row_similarity(row, incoming, normalizer=normalizer, config=config)
        for row in group
    )


def _progressive_align(
    groups: Sequence[tuple[RowInput, ...]],
    incoming: Sequence[RowInput],
    *,
    normalizer: Normalizer,
    config: AlignmentConfig,
) -> list[tuple[RowInput, ...]]:
    """Align a sequence of existing groups with one additional engine."""

    rows_count = len(groups)
    incoming_count = len(incoming)
    scores = [[0.0] * (incoming_count + 1) for _ in range(rows_count + 1)]
    back: list[list[str | None]] = [
        [None] * (incoming_count + 1) for _ in range(rows_count + 1)
    ]
    for row_index in range(1, rows_count + 1):
        scores[row_index][0] = scores[row_index - 1][0] + config.gap_penalty
        back[row_index][0] = "up"
    for incoming_index in range(1, incoming_count + 1):
        scores[0][incoming_index] = scores[0][incoming_index - 1] + config.gap_penalty
        back[0][incoming_index] = "left"

    for row_index in range(1, rows_count + 1):
        for incoming_index in range(1, incoming_count + 1):
            similarity = _group_similarity(
                groups[row_index - 1],
                incoming[incoming_index - 1],
                normalizer=normalizer,
                config=config,
            )
            diagonal_increment = (
                similarity
                if similarity >= config.minimum_match_similarity
                else config.mismatch_penalty
            )
            # Priority is the secondary key: prefer a real match, then a gap
            # in the incoming engine, then an inserted incoming row.
            choices = (
                (scores[row_index - 1][incoming_index - 1] + diagonal_increment, 2, "diag"),
                (scores[row_index - 1][incoming_index] + config.gap_penalty, 1, "up"),
                (scores[row_index][incoming_index - 1] + config.gap_penalty, 0, "left"),
            )
            score, _, direction = max(choices, key=lambda item: (item[0], item[1]))
            scores[row_index][incoming_index] = score
            back[row_index][incoming_index] = direction

    aligned_reversed: list[tuple[RowInput, ...]] = []
    row_index, incoming_index = rows_count, incoming_count
    while row_index or incoming_index:
        direction = back[row_index][incoming_index]
        if direction == "diag":
            aligned_reversed.append(
                groups[row_index - 1] + (incoming[incoming_index - 1],)
            )
            row_index -= 1
            incoming_index -= 1
        elif direction == "up":
            aligned_reversed.append(groups[row_index - 1])
            row_index -= 1
        elif direction == "left":
            aligned_reversed.append((incoming[incoming_index - 1],))
            incoming_index -= 1
        else:  # pragma: no cover - defensive guard for a corrupt DP matrix
            raise RuntimeError("alignment traceback reached an invalid state")
    aligned_reversed.reverse()
    return aligned_reversed


def _natural_key(parts: tuple[str, str, str]) -> tuple[tuple[tuple[int, int | str], ...], ...]:
    def split(value: str) -> tuple[tuple[int, int | str], ...]:
        tokens: list[tuple[int, int | str]] = []
        for token in re.split(r"(\d+)", value):
            if not token:
                continue
            tokens.append((0, int(token)) if token.isdigit() else (1, token.casefold()))
        return tuple(tokens)

    return tuple(split(part) for part in parts)


def _coerce_rows(
    rows_by_engine: Mapping[str, Sequence[RowInput | Mapping[str, Any]]],
) -> dict[str, list[RowInput]]:
    result: dict[str, list[RowInput]] = {}
    for engine, raw_rows in rows_by_engine.items():
        engine_name = str(engine)
        if not engine_name:
            raise ValueError("engine names must be non-empty")
        rows: list[RowInput] = []
        for raw_row in raw_rows:
            row = (
                raw_row
                if isinstance(raw_row, RowInput)
                else RowInput.from_dict(raw_row, engine_id=engine_name)
            )
            if row.engine_id != engine_name:
                raise ValueError(
                    f"row engine {row.engine_id!r} does not match mapping key {engine_name!r}"
                )
            rows.append(row)
        result[engine_name] = rows
    return result


def align_rows(
    rows_by_engine: Mapping[str, Sequence[RowInput | Mapping[str, Any]]],
    *,
    normalization: NormalizationConfig | Mapping[str, Any] | Normalizer | None = None,
    config: AlignmentConfig | None = None,
) -> list[AlignedRowGroup]:
    """Align all engines within each document/page/table section.

    Input order inside each engine's JSONL stream is authoritative.  Engines
    are aligned progressively, starting with the longest stream in a section;
    lexical engine name breaks ties so mapping insertion order cannot affect
    the result.
    """

    coerced = _coerce_rows(rows_by_engine)
    if isinstance(normalization, Normalizer):
        normalizer = normalization
    else:
        normalizer = Normalizer(normalization)
    config = config or AlignmentConfig()

    section_rows: dict[tuple[str, str, str], dict[str, list[RowInput]]] = {}
    for engine, rows in coerced.items():
        for row in rows:
            section_rows.setdefault(row.section_key, {}).setdefault(engine, []).append(row)

    output: list[AlignedRowGroup] = []
    for section in sorted(section_rows, key=_natural_key):
        by_engine = section_rows[section]
        engine_order = sorted(by_engine, key=lambda name: (-len(by_engine[name]), name))
        if config.anchor_engine in by_engine:
            engine_order.remove(config.anchor_engine)
            engine_order.insert(0, config.anchor_engine)
        anchor = engine_order[0]
        groups: list[tuple[RowInput, ...]] = [(row,) for row in by_engine[anchor]]
        for engine in engine_order[1:]:
            groups = _progressive_align(
                groups,
                by_engine[engine],
                normalizer=normalizer,
                config=config,
            )
        for ordinal, rows in enumerate(groups, start=1):
            output.append(
                AlignedRowGroup(
                    document_id=section[0],
                    page_id=section[1],
                    table_id=section[2],
                    ordinal=ordinal,
                    rows=rows,
                    anchor_engine_id=rows[0].engine_id,
                )
            )
    return output


__all__ = ["AlignmentConfig", "align_rows", "row_similarity"]
