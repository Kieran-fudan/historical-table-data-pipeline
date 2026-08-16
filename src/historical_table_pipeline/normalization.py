"""Configurable, deterministic normalization for comparing source cells.

Normalization affects comparison values only.  The original value and source
field name remain available to the consensus layer as audit evidence.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

from .models import JsonScalar, RowInput

Transform = Callable[[JsonScalar], JsonScalar]


def _text_transform(function: Callable[[str], str]) -> Transform:
    def apply(value: JsonScalar) -> JsonScalar:
        return function(value) if isinstance(value, str) else value

    return apply


def _collapse_whitespace(value: str) -> str:
    return " ".join(value.split())


def _remove_whitespace(value: str) -> str:
    return "".join(value.split())


_DASHES = str.maketrans({"‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-", "−": "-"})


def _canonical_number(value: JsonScalar) -> JsonScalar:
    """Canonicalize numeric-looking strings without converting them to float."""

    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        value = str(value)
    if not isinstance(value, str):
        return value
    compact = value.replace(",", "").strip()
    if not re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)", compact):
        return value
    try:
        number = Decimal(compact)
    except InvalidOperation:
        return value
    if not number.is_finite():
        return value
    normalized = format(number.normalize(), "f")
    if "." in normalized:
        normalized = normalized.rstrip("0").rstrip(".")
    return "0" if normalized in ("-0", "+0", "") else normalized


BUILTIN_TRANSFORMS: Mapping[str, Transform] = {
    "nfkc": _text_transform(lambda value: unicodedata.normalize("NFKC", value)),
    "strip": _text_transform(str.strip),
    "collapse_whitespace": _text_transform(_collapse_whitespace),
    "whitespace": _text_transform(_collapse_whitespace),
    "remove_whitespace": _text_transform(_remove_whitespace),
    "casefold": _text_transform(str.casefold),
    "lower": _text_transform(str.lower),
    "upper": _text_transform(str.upper),
    "uppercase_latin": _text_transform(str.upper),
    "normalize_dashes": _text_transform(lambda value: value.translate(_DASHES)),
    "canonical_number": _canonical_number,
}


@dataclass(frozen=True, slots=True)
class FieldNormalization:
    """Rules for one canonical field.

    Replacements are literal and run after named transforms.  Values matching
    ``missing_values`` after those steps become ``None``.
    """

    transforms: tuple[str, ...] = ("nfkc", "strip", "collapse_whitespace")
    replacements: Mapping[str, str] = field(default_factory=dict)
    missing_values: tuple[JsonScalar, ...] = ("",)

    def __post_init__(self) -> None:
        object.__setattr__(self, "transforms", tuple(self.transforms))
        object.__setattr__(self, "replacements", dict(self.replacements))
        object.__setattr__(self, "missing_values", tuple(self.missing_values))

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any] | Sequence[str] | None) -> FieldNormalization:
        if payload is None:
            return cls()
        if isinstance(payload, Sequence) and not isinstance(payload, (str, bytes)):
            return cls(transforms=tuple(str(item) for item in payload))
        if not isinstance(payload, Mapping):
            raise TypeError("field normalization must be a mapping or transform list")
        transforms = payload.get("transforms", cls().transforms)
        if isinstance(transforms, str):
            transforms = (transforms,)
        replacements = payload.get("replacements", {})
        missing_values = payload.get("missing_values", cls().missing_values)
        if isinstance(missing_values, (str, bytes)):
            missing_values = (missing_values,)
        return cls(
            transforms=tuple(str(item) for item in transforms),
            replacements={str(key): str(value) for key, value in replacements.items()},
            missing_values=tuple(missing_values),
        )


@dataclass(frozen=True, slots=True)
class NormalizationConfig:
    """Model-neutral configuration for canonical fields and comparison rules."""

    default: FieldNormalization = field(default_factory=FieldNormalization)
    fields: Mapping[str, FieldNormalization] = field(default_factory=dict)
    field_aliases: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        clean_fields: dict[str, FieldNormalization] = {}
        for name, rule in self.fields.items():
            clean_fields[str(name)] = (
                rule
                if isinstance(rule, FieldNormalization)
                else FieldNormalization.from_mapping(rule)
            )
        aliases = {str(alias): str(canonical) for alias, canonical in self.field_aliases.items()}
        if any(not alias or not canonical for alias, canonical in aliases.items()):
            raise ValueError("field aliases and canonical names must be non-empty")
        object.__setattr__(self, "fields", clean_fields)
        object.__setattr__(self, "field_aliases", aliases)

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any] | None) -> NormalizationConfig:
        if payload is None:
            return cls()
        default_payload = payload.get("default") or payload.get("defaults")
        raw_fields = payload.get("fields", {})
        aliases = payload.get("field_aliases", payload.get("aliases", {}))
        return cls(
            default=FieldNormalization.from_mapping(default_payload),
            fields={
                str(name): FieldNormalization.from_mapping(rule)
                for name, rule in raw_fields.items()
            },
            field_aliases={str(key): str(value) for key, value in aliases.items()},
        )

    def canonical_field(self, source_field: str) -> str:
        return self.field_aliases.get(source_field, source_field)

    def rule_for(self, canonical_field: str) -> FieldNormalization:
        return self.fields.get(canonical_field, self.default)


@dataclass(frozen=True, slots=True)
class NormalizedCell:
    field: str
    source_field: str
    raw_value: JsonScalar
    normalized_value: JsonScalar


class NormalizationCollisionError(ValueError):
    """Raised when two source columns map to one canonical field in one row."""


class Normalizer:
    """Apply a normalization config with an optional custom transform registry."""

    def __init__(
        self,
        config: NormalizationConfig | Mapping[str, Any] | None = None,
        *,
        transforms: Mapping[str, Transform] | None = None,
    ) -> None:
        if config is None or isinstance(config, Mapping):
            self.config = NormalizationConfig.from_mapping(config)
        else:
            self.config = config
        self.transforms: dict[str, Transform] = dict(BUILTIN_TRANSFORMS)
        if transforms:
            self.transforms.update(transforms)
        used = set(self.config.default.transforms)
        for rule in self.config.fields.values():
            used.update(rule.transforms)
        unknown = sorted(used - self.transforms.keys())
        if unknown:
            raise ValueError(f"unknown normalization transforms: {', '.join(unknown)}")

    def normalize_value(self, field_name: str, value: JsonScalar) -> JsonScalar:
        canonical = self.config.canonical_field(field_name)
        rule = self.config.rule_for(canonical)
        result = value
        for transform_name in rule.transforms:
            result = self.transforms[transform_name](result)
        if isinstance(result, str):
            for old, new in rule.replacements.items():
                result = result.replace(old, new)
        return None if result in rule.missing_values else result

    def normalize_row(self, row: RowInput) -> dict[str, NormalizedCell]:
        result: dict[str, NormalizedCell] = {}
        for source_field, raw_value in row.cells.items():
            canonical = self.config.canonical_field(source_field)
            normalized = self.normalize_value(source_field, raw_value)
            if canonical in result:
                previous = result[canonical]
                raise NormalizationCollisionError(
                    f"row {row.engine}:{row.source_row} maps both "
                    f"{previous.source_field!r} and {source_field!r} to {canonical!r}"
                )
            result[canonical] = NormalizedCell(
                field=canonical,
                source_field=source_field,
                raw_value=raw_value,
                normalized_value=normalized,
            )
        return result


def normalize_value(
    value: JsonScalar,
    *,
    field_name: str = "value",
    config: NormalizationConfig | Mapping[str, Any] | None = None,
) -> JsonScalar:
    """Convenience wrapper for one value."""

    return Normalizer(config).normalize_value(field_name, value)


def normalize_row(
    row: RowInput,
    config: NormalizationConfig | Mapping[str, Any] | None = None,
) -> dict[str, NormalizedCell]:
    """Convenience wrapper returning canonical cells without mutating ``row``."""

    return Normalizer(config).normalize_row(row)


__all__ = [
    "BUILTIN_TRANSFORMS",
    "FieldNormalization",
    "NormalizedCell",
    "NormalizationCollisionError",
    "NormalizationConfig",
    "Normalizer",
    "normalize_row",
    "normalize_value",
]
