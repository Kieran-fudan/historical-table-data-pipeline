# Data model and provenance contract

This project keeps evidence, reconciliation, review, and publication as separate
layers. A standardized value never replaces an OCR transcription. The shortest
useful provenance chain is:

`published value -> decision (when required) -> consensus candidate -> engine row -> source page`

The contracts below are UTF-8 JSON or JSONL. Exact CLI schemas are versioned with
the package; profile files declare the document-specific parts of the contract.

## 1. Canonical OCR row

One JSONL line is one table row reported by one OCR engine. Required keys are:

| Key | Meaning |
| --- | --- |
| `document_id` | Stable identifier for the complete source document. |
| `page_id` | Stable logical identifier for this source page. |
| `source_pdf_page_index` | Zero-based index in the complete, unsplit PDF. |
| `printed_page_label` | Label printed on the page, or `null` when absent. |
| `table_id` | Stable table identifier; a page may contain multiple tables. |
| `engine_id` | Stable OCR source label. |
| `engine_version` | Pinned engine, model, prompt, or transcription version. |
| `source_row_index` | Zero-based row position within the table. |
| `cells` | Mapping from profile field name to the raw scalar observation. |

Optional keys are `bbox`, `prompt_hash`, and `run_id`. Producers may retain
additional provider metadata, but must not place secrets or private local paths in
an artifact.

The three page/table identifiers are not interchangeable. Front matter can make
`source_pdf_page_index` differ from `printed_page_label`, and page filtering must
not renumber either value. `table_id` disambiguates multiple tables on one page.

`cells` contains raw observations. Do not correct characters, expand ditto marks,
insert units, or convert dates before this immutable layer is saved. Use `null` for
an unknown or unobserved value only when that meaning is known; a source-visible
blank, an illegible cell, and a missing OCR row are different states.

The Python API accepts descriptive keys above and maps them to its internal aliases
(`document`, `page`, `table`, `source_row`, and `engine`). Physical-page and run
metadata remain attached to the source row.

## 2. Alignment and consensus

Alignment groups rows only within the same document, page, and table. Profile
anchor fields and weights guide ordered alignment; `anchor_engine` selects a stable
reference order but grants no authority, and an unmatched row is retained.
Each consensus record has a stable `record_id`, source-row provenance, missing
engine labels, an `anchor_engine_id`, and a map of consensus cells. The anchor
engine identifies the immutable source row used to derive `record_id`; it is an
identity reference, not a claim that this engine is more accurate. Changing an
OCR model version or JSONL filename does not change the record ID; changing the
anchor row's document/page/table/row identity does.

Each cell retains:

- a stable `cell_id` and canonical field name;
- `chosen_value`, which may remain `null`;
- every candidate's `raw_value` and conservative `normalized_value`;
- engine, document, page, table, row, and optional source-reference provenance;
- supporting candidate IDs and missing engines;
- an attached replayable decision, when one exists.

Consensus status has four values:

| Status | Meaning |
| --- | --- |
| `unanimous` | At least two expected observations agree after configured conservative normalization. |
| `majority` | A strict configured majority supports one value. |
| `conflict` | Competing non-null values have no strict majority. |
| `missing` | No value exists, or only one exists while multiple engines are expected. |

Comparison normalization is deliberately narrower than semantic standardization.
Configured Unicode and whitespace transforms can help compare candidates, but they
do not alter raw values or authorize a published interpretation. Dates, prices,
units, geography, and taxonomy are standardized only in later derived layers.

Agreement is not ground truth. Correlated OCR errors remain possible. `missing` is
a cell status; the quality metric `missing_source_rows` counts aligned rows that
lack at least one expected engine and is not another status value.

## 3. Decisions

The deterministic core uses one replayable decision per consensus cell:

| Key | Meaning |
| --- | --- |
| `cell_id` | Required exact consensus-cell target. |
| `chosen_value` | Required JSON scalar selected for the derived cell; it does not overwrite evidence. |
| `reason`, `reviewer`, `decided_at` | Required review rationale, reviewer identity, and timestamp. |
| `candidate_id` | Optional link to a source-supported candidate. When present, its normalized value must equal `chosen_value`. |
| `decision_id` | Optional stable identifier; the core derives one when omitted. |
| `metadata` | Optional finite JSON metadata, never a replacement for source evidence. |

Use the decision template emitted by the installed CLI because stable IDs are
generated from source provenance. A decision changes a derived layer; it never
edits OCR JSONL or deletes rejected candidates.

```json
{
  "cell_id": "cell_example",
  "chosen_value": "Sample item",
  "candidate_id": "cand_example",
  "reason": "Matches the authorized source-page image.",
  "reviewer": "reviewer-id",
  "decided_at": "2026-08-16T00:00:00Z"
}
```

The synthetic file
`examples/synthetic/decisions/reconciliation.jsonl` is a compact workflow-level
audit example. It demonstrates a candidate choice, acceptance of a single-source
row, and explicit same-table ditto resolution. Those high-level events are not a
second core decision schema: the CLI recognizes them and the decision compiler
expands them into the canonical cell decisions above before application.

## 4. Raw and standardized publication fields

Research-facing records keep each configured field as a pair:

```json
{
  "item_name": {
    "raw": {"ocr-alpha": "same as above", "ocr-beta": "ditto"},
    "std": "Sample item",
    "status": "resolved_by_decision"
  }
}
```

`raw` is keyed by engine and is never overwritten. `std` is the published form
and may be a scalar, structured object, list of linked observation IDs, or `null`.
`resolved_by_decision` is a publication-layer state showing why `std` is usable;
it is not a consensus-voting status.

Historical geography should retain the source-era name. A modern mapping, if
needed, is an additional versioned field rather than a replacement. Units likewise
need separate raw and standardized representations, and no default unit should be
invented merely because most rows share one.

## 5. Dates

Dates preserve the complete expression and expose only supported precision:

| Field | Example |
| --- | --- |
| `date_raw` | `2000 (1 unit), 2001 (4 units)` |
| `date_start` | `2000` |
| `date_end` | `2001` |
| `date_precision` | `range_year` |

Allowed precision is profile-specific, for example `year`, `month`, `range_year`,
`range_month`, or `unresolved`. A two-digit year can be expanded only under an
explicit century policy. Do not manufacture a day or collapse a range to one date.

## 6. Long-form prices

A record can report multiple monetary observations, so prices use a separate long
table. Each row contains:

- `price_id` and its parent `record_id`;
- `value_raw`, `value_numeric`, `currency_code`, and `scale_factor`;
- `basis` and `denominator_unit` (for example per unit or a grouped total);
- `conversion_role`, `source_reported`, and any `unresolved_reason`;
- `source_cell_ids` linking back to price evidence.

The represented amount is `value_numeric * scale_factor`; keep the two components
separate to preserve source notation such as “万”. A source-printed conversion is
stored as another observation with `conversion_role: source_reported_conversion`.
Never create historical exchange-rate conversions without an explicit, cited
derivation layer.

## 7. Matrix-table boundary

The included parser models record-oriented tables: one source row corresponds to
one item listing or explicitly flagged aggregate/orphan record. Ordinary matrix
tables do not fit that grain. Category-by-indicator, period-by-indicator, and
multi-level-column tables require a new
`matrix_observation` parser and a long observation contract such as:

`document/page/table + category_raw/std + indicator_raw/std/code + period + value_raw/numeric + unit_raw/std + footnote/provenance`

Adding matrix field names to a record profile is not a valid shortcut. New
geometry needs page-level header reconstruction, merged-cell rules, repeated-header
handling, cross-page continuation tests, and matrix-specific referential checks.

## 8. Quality summary

Quality output records evidence about the run, not a claim of transcription
accuracy. At minimum report rows by engine, aligned records, unanimous records,
conflict cells, `missing_source_rows`, repeat-marker cells, manual decisions, and
provenance completeness. Domain exports should also check date precision, price
referential integrity, currencies, units, and unresolved values.

The fully synthetic fixture under `examples/synthetic/` provides executable examples
of all contracts without redistributing any PDF, OCR dump, real record, or personal
path.
