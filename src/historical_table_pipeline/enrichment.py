"""Conservative research-data views built on reviewed consensus cells.

These helpers never replace source observations. They attach standardized
representations while keeping every engine's raw candidate in the record.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation
from typing import Any

from historical_table_pipeline.config import Profile
from historical_table_pipeline.models import ConsensusRecord, JsonScalar, stable_id


def _text(value: JsonScalar) -> str | None:
    if value is None:
        return None
    result = str(value).strip()
    return result or None


def _expand_year(value: int, *, century: int | None, edition_year: int | None) -> int:
    if value >= 100:
        return value
    if century is not None:
        return century + value
    if edition_year is None:
        raise ValueError("two-digit year requires a configured century or edition year")
    base = edition_year - (edition_year % 100)
    candidate = base + value
    return candidate - 100 if candidate > edition_year + 5 else candidate


def parse_date_expression(value: JsonScalar, config: Mapping[str, Any]) -> dict[str, Any]:
    raw = _text(value)
    result = {
        "date_raw": raw,
        "date_start": None,
        "date_end": None,
        "date_precision": "missing" if raw is None else "unresolved",
        "unresolved_reason": None,
    }
    if raw is None:
        return result
    normalized = unicodedata.normalize("NFKC", raw)
    edition_year = config.get("edition_year")
    edition = int(edition_year) if edition_year is not None else None
    century_value = config.get("two_digit_century")
    century = int(century_value) if century_value is not None else None
    matches = re.findall(r"(?<!\d)(\d{4}|\d{2})(?:[.\-/](\d{1,2}))?", normalized)
    parsed: list[tuple[int, int | None]] = []
    try:
        for year_text, month_text in matches:
            year = _expand_year(int(year_text), century=century, edition_year=edition)
            month = int(month_text) if month_text else None
            if month is not None and not 1 <= month <= 12:
                result["unresolved_reason"] = f"invalid month: {month}"
                return result
            parsed.append((year, month))
    except ValueError as exc:
        result["unresolved_reason"] = str(exc)
        return result
    if not parsed:
        result["unresolved_reason"] = "no configured year pattern matched"
        return result

    def render(item: tuple[int, int | None]) -> str:
        year, month = item
        return f"{year:04d}" if month is None else f"{year:04d}-{month:02d}"

    result["date_start"] = render(parsed[0])
    result["date_end"] = render(parsed[-1])
    if len(parsed) == 1:
        result["date_precision"] = "year" if parsed[0][1] is None else "month"
    elif any(month is not None for _, month in parsed):
        result["date_precision"] = "range_month"
    else:
        result["date_precision"] = "range_year"
    return result


def _numeric(value: str) -> int | float | None:
    compact = value.replace(",", "").strip()
    try:
        number = Decimal(compact)
    except InvalidOperation:
        return None
    if not number.is_finite():
        return None
    if number == number.to_integral_value():
        return int(number)
    return float(number)


def parse_quantity(value: JsonScalar) -> int | float | str | None:
    raw = _text(value)
    if raw is None:
        return None
    parsed = _numeric(unicodedata.normalize("NFKC", raw))
    return parsed if parsed is not None else raw


def _currency_aliases(config: Mapping[str, Any]) -> list[tuple[str, str]]:
    aliases = config.get("currency_aliases", {})
    output: list[tuple[str, str]] = []
    if isinstance(aliases, Mapping):
        for code, values in aliases.items():
            if isinstance(values, str):
                values = [values]
            for alias in values or []:
                output.append((str(alias), str(code)))
    return sorted(output, key=lambda item: (-len(item[0]), item[0]))


def _price_segments(raw: str) -> list[str]:
    normalized = unicodedata.normalize("NFKC", raw)
    segments = [re.sub(r"[()]", "", item).strip() for item in re.split(r"[()]", normalized)]
    return [item for item in segments if item]


def _configured_markers(
    config: Mapping[str, Any], key: str, default: Sequence[str] = ()
) -> tuple[str, ...]:
    value = config.get(key, default)
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, Sequence):
        return tuple(default)
    return tuple(str(item).casefold() for item in value if str(item))


def _contains_marker(value: str, markers: Sequence[str]) -> bool:
    folded = value.casefold()
    return any(marker in folded for marker in markers)


def _scale_factor(value: str, config: Mapping[str, Any]) -> int | float:
    configured = config.get("scale_factors", {})
    if not isinstance(configured, Mapping):
        return 1
    folded = value.casefold()
    markers = sorted(configured.items(), key=lambda item: -len(str(item[0])))
    for marker, factor in markers:
        if str(marker).casefold() in folded:
            numeric = _numeric(str(factor))
            if numeric is not None and numeric > 0:
                return numeric
    return 1


def parse_prices(
    value: JsonScalar,
    unit_value: JsonScalar,
    *,
    record_id: str,
    source_cell_ids: Sequence[str],
    config: Mapping[str, Any],
) -> list[dict[str, Any]]:
    raw = _text(value)
    unit_raw = _text(unit_value)
    if raw is None:
        return []
    aliases = _currency_aliases(config)
    segments = _price_segments(raw)
    explicit_aliases = [
        [(alias, code) for alias, code in aliases if alias in segment]
        for segment in segments
    ]
    explicit_segment_count = sum(bool(matches) for matches in explicit_aliases)
    observations: list[dict[str, Any]] = []
    for segment_index, segment in enumerate(segments):
        matches = explicit_aliases[segment_index]
        if not matches and explicit_segment_count:
            # Parenthetical quantities or notes must not inherit a currency
            # merely because the separate unit column names one.
            continue
        if not matches and unit_raw:
            matches = [(alias, code) for alias, code in aliases if alias in unit_raw]
        if not matches:
            continue
        alias, code = matches[0]
        numbers = re.findall(r"(?<!\d)(\d[\d,]*(?:\.\d+)?)", segment)
        if not numbers:
            continue
        number_text = numbers[0]
        numeric = _numeric(number_text)
        scale_factor = _scale_factor(f"{segment} {unit_raw or ''}", config)
        combined = f"{raw if explicit_segment_count == 1 else segment} {unit_raw or ''}"
        group_markers = _configured_markers(
            config, "group_total_markers", ("total", "combined")
        )
        item_labels = _configured_markers(config, "item_labels", ("item", "record"))
        labels_pattern = "|".join(re.escape(label) for label in item_labels)
        grouped_match = (
            re.search(rf"(\d+)\s*(?:{labels_pattern})s?\b", combined.casefold())
            if labels_pattern
            else None
        )
        if _contains_marker(combined, group_markers):
            basis = "grouped_total"
            label = str(config.get("denominator_label", "items"))
            denominator = f"{grouped_match.group(1)} {label}" if grouped_match else "group"
        elif _contains_marker(
            combined,
            _configured_markers(
                config,
                "per_unit_markers",
                ("/item", "per item", "each item", "/record", "per record"),
            ),
        ):
            basis = "per_unit"
            denominator = str(config.get("denominator_label", "item"))
        else:
            basis = "unresolved"
            denominator = None
        conversion_role = (
            "source_reported_conversion"
            if _contains_marker(
                segment,
                _configured_markers(
                    config,
                    "conversion_markers",
                    ("equivalent", "converted"),
                ),
            )
            else "original"
        )
        observation = {
            "price_id": stable_id(
                "price", record_id, segment_index, segment, code, number_text
            ),
            "record_id": record_id,
            "value_raw": raw if explicit_segment_count == 1 else segment,
            "value_numeric": numeric,
            "currency_code": code,
            "scale_factor": scale_factor,
            "basis": basis,
            "denominator_unit": denominator,
            "conversion_role": conversion_role,
            "source_reported": True,
            "unresolved_reason": (
                "source expression does not state unit versus total"
                if basis == "unresolved"
                else None
            ),
            "source_cell_ids": list(source_cell_ids),
            "currency_alias_matched": alias,
        }
        observations.append(observation)
    if observations:
        return observations
    return [
        {
            "price_id": stable_id("price", record_id, raw, "unresolved"),
            "record_id": record_id,
            "value_raw": raw,
            "value_numeric": None,
            "currency_code": None,
            "scale_factor": None,
            "basis": "unresolved",
            "denominator_unit": None,
            "conversion_role": None,
            "source_reported": True,
            "unresolved_reason": "no configured currency/amount pattern matched",
            "source_cell_ids": list(source_cell_ids),
            "currency_alias_matched": None,
        }
    ]


def _common_source_metadata(record: ConsensusRecord, key: str) -> Any:
    values = {
        getattr(source, key, source.metadata.get(key))
        for source in record.sources
        if getattr(source, key, source.metadata.get(key)) is not None
    }
    if len(values) > 1:
        raise ValueError(f"record {record.record_id} has conflicting source metadata for {key}")
    return next(iter(values)) if values else None


def _semantic_field(profile: Profile, role: str) -> str | None:
    matches = [
        field.name
        for field in profile.fields
        if field.metadata.get("semantic_role") == role
    ]
    if len(matches) > 1:
        raise ValueError(f"profile defines multiple fields with semantic_role={role!r}")
    return matches[0] if matches else None


def build_research_views(
    records: Sequence[ConsensusRecord], profile: Profile
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    normalization = profile.raw.get("normalization", {})
    if not isinstance(normalization, Mapping):
        normalization = {}
    dates = normalization.get("dates", {})
    prices = normalization.get("amounts", normalization.get("prices", {}))
    quantity_field = _semantic_field(profile, "quantity")
    date_field = _semantic_field(profile, "date")
    amount_field = _semantic_field(profile, "amount")
    amount_unit_field = _semantic_field(profile, "amount_unit")
    published: list[dict[str, Any]] = []
    price_rows: list[dict[str, Any]] = []
    for record in records:
        fields: dict[str, Any] = {}
        decision_ids: list[str] = []
        unresolved = False
        for field_name in profile.field_names:
            cell = record.cells.get(field_name)
            if cell is None:
                fields[field_name] = {"raw": {}, "std": None, "status": "missing"}
                unresolved = True
                continue
            raw_by_engine = {
                candidate.provenance.engine: candidate.raw_value for candidate in cell.candidates
            }
            status = "resolved_by_decision" if cell.decision is not None else cell.status.value
            if cell.decision is not None:
                decision_ids.append(cell.decision.decision_id)
            if not cell.is_resolved:
                unresolved = True
            standardized: Any = cell.chosen_value
            if field_name == quantity_field:
                standardized = parse_quantity(standardized)
            fields[field_name] = {
                "raw": raw_by_engine,
                "std": standardized,
                "status": status,
                "cell_id": cell.cell_id,
            }
        date_cell = record.cells.get(date_field) if date_field else None
        date_view = (
            parse_date_expression(
                date_cell.chosen_value if date_cell else None,
                dates if isinstance(dates, Mapping) else {},
            )
            if date_field
            else None
        )
        price_cell = record.cells.get(amount_field) if amount_field else None
        price_unit_cell = (
            record.cells.get(amount_unit_field) if amount_unit_field else None
        )
        if price_cell is not None:
            parsed_prices = parse_prices(
                price_cell.chosen_value,
                price_unit_cell.chosen_value if price_unit_cell else None,
                record_id=record.record_id,
                source_cell_ids=[price_cell.cell_id],
                config=prices if isinstance(prices, Mapping) else {},
            )
            price_rows.extend(parsed_prices)
            if amount_field in fields:
                fields[amount_field]["std"] = [item["price_id"] for item in parsed_prices]
        statuses = {cell.status.value for cell in record.cells.values()}
        if unresolved:
            record_status = "unresolved"
        elif decision_ids:
            record_status = "resolved_by_decision"
        elif statuses == {"unanimous"}:
            record_status = "unanimous"
        else:
            record_status = "majority"
        first_source = record.sources[0] if record.sources else None
        published_record = {
                "record_id": record.record_id,
                "document_id": record.document,
                "page_id": record.page,
                "source_pdf_page_index": _common_source_metadata(
                    record, "source_pdf_page_index"
                ),
                "printed_page_label": _common_source_metadata(record, "printed_page_label"),
                "table_id": record.table,
                "source_row_index": (
                    first_source.source_row_index
                    if first_source
                    else None
                ),
                "record_status": record_status,
                "decision_ids": sorted(set(decision_ids)),
                "fields": fields,
            }
        if date_view is not None:
            published_record["date"] = date_view
        published.append(published_record)
    return published, price_rows


__all__ = [
    "build_research_views",
    "parse_date_expression",
    "parse_prices",
    "parse_quantity",
]
