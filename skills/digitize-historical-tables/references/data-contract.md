# Data contract

Use this reference when preparing OCR inputs or checking reconciliation artifacts. Let the CLI-generated schemas and templates for the installed version control exact field names.

## Canonical OCR input

Provide UTF-8 JSONL with one logical table record per line. Each line must identify:

- document;
- page, including physical or printed identity when available;
- table and source-row position;
- OCR engine/source;
- cells in source order;
- optional source reference and metadata.

Keep raw cell text unchanged. Store standardized text separately when the contract supports it. Do not encode an unknown value as an empty string if the source distinguishes missing, illegible, and intentionally blank cells.

Use stable source labels. Two runs from the same engine and prompt are separate runs, but they are not necessarily independent evidence.

## Stable identity and provenance

The pipeline derives stable record and cell identifiers from document, page, table, row, and field identity. Do not invent or edit these identifiers in review files.

Every candidate and applied value must remain traceable to:

- the originating OCR source or explicit reviewer correction;
- its raw transcription;
- page and row context;
- the profile and software version;
- the decision that selected or changed it.

## Reconciliation candidates

`historical-table reconcile` emits review candidates rather than final truth. A candidate packet should retain:

- candidate and cell identity;
- all source alternatives;
- source support for each alternative;
- agreement, conflict, missing, or unresolved status;
- contextual fields needed for review;
- any conservative comparison normalization applied.

Never discard a minority alternative before publication evidence is complete.

## Decisions

Create decisions from the template produced by `historical-table review-export`. Do not handcraft a schema from memory.

Each canonical decision targets exactly one consensus `cell_id`. It requires `chosen_value`, `reason`, `reviewer`, and `decided_at`; `decision_id`, `candidate_id`, and `metadata` are optional. Express one supported outcome:

- select a source-supported alternative by including its `candidate_id` and matching normalized `chosen_value`;
- record a justified corrected `chosen_value` with reviewer provenance and no `candidate_id`;
- keep the item unresolved by leaving it without an applied decision.

Include a concise reason when selecting against the apparent consensus or entering a correction. Never place credentials, private paths, or copied page content beyond the minimum evidence in a decision file.

The synthetic workflow ledger contains higher-level review events. Let the CLI decision compiler convert them to canonical cell decisions; do not translate them manually or mix both contracts in one file.

## Applied and published outputs

Application creates derived data; it never mutates OCR inputs or candidate packets. Publication may include:

- normalized record observations;
- long-form price observations;
- provenance links;
- unresolved and exclusion indicators;
- a machine-readable quality summary.

An empty published value must remain distinguishable from an unresolved or excluded value wherever the output schema supports that distinction.
