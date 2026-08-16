"""Profile loading and validation.

Profiles contain source-specific knowledge. The execution engine deliberately does
not contain years, sector names, currency lists, or model identifiers.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


class ProfileError(ValueError):
    """Raised when a profile is missing a required contract field."""


@dataclass(frozen=True, slots=True)
class FieldDefinition:
    name: str
    label: str
    data_type: str = "string"
    required: bool = False
    comparison_normalizers: tuple[str, ...] = ("nfkc", "whitespace")
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Profile:
    path: Path
    profile_version: str
    name: str
    record_type: str
    fields: tuple[FieldDefinition, ...]
    raw: Mapping[str, Any]

    @property
    def field_names(self) -> tuple[str, ...]:
        return tuple(item.name for item in self.fields)

    @property
    def field_map(self) -> dict[str, FieldDefinition]:
        return {item.name: item for item in self.fields}

    @property
    def alignment_weights(self) -> dict[str, float]:
        alignment = self.raw.get("alignment", {})
        weights = alignment.get("weights", {}) if isinstance(alignment, Mapping) else {}
        if weights:
            return {str(key): float(value) for key, value in weights.items()}
        anchors = alignment.get("anchor_fields", []) if isinstance(alignment, Mapping) else []
        return {str(name): 1.0 for name in anchors} or {
            field.name: 1.0 for field in self.fields
        }

    @property
    def expected_sources(self) -> int:
        consensus = self.raw.get("consensus", {})
        value = consensus.get("expected_sources", 2) if isinstance(consensus, Mapping) else 2
        return max(1, int(value))


def _require_mapping(value: Any, location: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ProfileError(f"{location} must be a mapping")
    return value


def _parse_field(value: Any, index: int) -> FieldDefinition:
    item = _require_mapping(value, f"fields[{index}]")
    name = str(item.get("name", "")).strip()
    if not name:
        raise ProfileError(f"fields[{index}].name is required")
    label = str(item.get("label", name)).strip() or name
    normalizers = item.get("comparison_normalizers", ("nfkc", "whitespace"))
    if isinstance(normalizers, str):
        normalizers = [normalizers]
    if not isinstance(normalizers, (list, tuple)):
        raise ProfileError(f"fields[{index}].comparison_normalizers must be a list")
    known = {
        "name",
        "label",
        "type",
        "data_type",
        "required",
        "comparison_normalizers",
    }
    return FieldDefinition(
        name=name,
        label=label,
        data_type=str(item.get("data_type", item.get("type", "string"))),
        required=bool(item.get("required", False)),
        comparison_normalizers=tuple(str(rule) for rule in normalizers),
        metadata={str(key): value for key, value in item.items() if key not in known},
    )


def load_profile(path: str | Path) -> Profile:
    profile_path = Path(path).expanduser().resolve()
    if not profile_path.is_file():
        raise ProfileError(f"Profile does not exist: {profile_path}")
    try:
        raw_value = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ProfileError(f"Invalid YAML in {profile_path}: {exc}") from exc
    raw = _require_mapping(raw_value, "profile")
    profile_version = str(raw.get("profile_version", "")).strip()
    name = str(raw.get("name", "")).strip()
    record_type = str(raw.get("record_type", "")).strip()
    if not profile_version:
        raise ProfileError("profile_version is required")
    if not name:
        raise ProfileError("name is required")
    if not record_type:
        raise ProfileError("record_type is required")
    fields_value = raw.get("fields")
    if not isinstance(fields_value, list) or not fields_value:
        raise ProfileError("fields must be a non-empty list")
    fields = tuple(_parse_field(item, index) for index, item in enumerate(fields_value))
    names = [item.name for item in fields]
    duplicates = sorted({name for name in names if names.count(name) > 1})
    if duplicates:
        raise ProfileError(f"Duplicate field names: {', '.join(duplicates)}")
    unknown_weights = set(
        str(name) for name in _require_mapping(raw.get("alignment", {}), "alignment")
        .get("weights", {})
    ) - set(names)
    if unknown_weights:
        raise ProfileError(
            "alignment.weights refers to unknown fields: " + ", ".join(sorted(unknown_weights))
        )
    return Profile(
        path=profile_path,
        profile_version=profile_version,
        name=name,
        record_type=record_type,
        fields=fields,
        raw=raw,
    )
