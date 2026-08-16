# Profile authoring guide

A profile describes one table family. It is configuration, not evidence that
any real publication with a similar layout will work. Start from
`profiles/template.yaml`, preserve the core contract, and add only rules supported
by representative page inspection and synthetic tests.

## Decide whether a profile is enough

| New material | Required change |
| --- | --- |
| Same row grain and geometry, but different labels, units, or date notation | New or versioned profile. |
| Same parser, with a documented optional column or repeated-header variant | Profile update plus regression fixture. |
| Category/period/indicator matrix, multi-level headers, independent panels, or a different observation grain | New parser and profile. |
| Charts, maps, narrative prose, or handwriting | Out of current scope unless a dedicated extractor is implemented and tested. |

The bundled `record_table` parser must not be used for an ordinary matrix table.
Such tables need the `matrix_observation` parser named in the template; that
parser is a declared extension point, not implemented support.

## 1. Declare evidence and limits

Give the profile a stable `profile_id`, semantic `profile_version`, and a precise
`scope`:

- `source_family` states the structural family rather than a marketing category;
- `validated_on` lists only editions, volumes, and layout variants actually tested;
- `known_exclusions` explains absent or incompatible material;
- `claim` states what the evidence does and does not establish.

The included `profiles/example-records.yaml` profile is completely fictional and
exists only to exercise the synthetic workflow. Its `validated_on` entries refer
only to synthetic fixtures. It does not establish support for any real corpus,
publication, language, sector, period, or matrix-style table family.

## 2. Preserve page identity

Keep all three identifiers configured:

- `source_pdf_page_index`: required, immutable, and zero-based in the complete PDF;
- `printed_page_label`: nullable and never substituted for the PDF index;
- `table_id`: required and stable across reruns.

Set `renumber_after_filtering: false`. Rendered-image numbers, spreadsheet row
numbers, and legacy sheet numbers must not silently become source-page identity.
Retain front matter when it affects offsets, volume identity, units, or notes.

## 3. Select a parser and observation grain

Set `parser.kind` and write one unambiguous `row_grain`. Describe relevant geometry,
including orientation, rules, merged cells, repeated blank cells, repeated headers,
multiple panels, and cross-page continuations. If a new source cannot be represented
without publication-specific exceptions in core code, it needs a new parser or a
preprocessing stage.

For cross-page tables, preserve the physical page identity on every row. Alignment
is page-local by default; continuation or ditto inheritance across a page boundary
requires an explicit decision.

## 4. Define fields

Every field entry must provide at least:

```yaml
- name: item_name
  label: Item name
  type: string
  required: true
```

`name` is a stable machine key, `label` is source-facing documentation, `type`
declares semantics, and `required` controls validation. For publication, also state
`preserve_raw: true`, a `standardized_name`, and a conservative
`standardization` policy.

Do not combine concepts merely because they share a printed cell. Split structured
dates and prices only in derived output while retaining the whole raw expression.
Do not overwrite historical region names, silently resolve organizations, or assume
a unit from neighboring rows without a configured and reviewable rule.

## 5. Configure independent sources

Declare at least two OCR/transcription sources and pin their versions at run time.
Independence is a research assumption that must be justified: two identical calls
to the same model and prompt may not provide independent evidence.

Each engine emits one JSONL row with the required keys listed in
[the data model](data-model.md). Save engine outputs separately and immutably. OCR
files are evidence; profiles must not contain copied real records, credentials,
provider secrets, or local paths.

## 6. Separate comparison normalization from standardization

`comparison_normalization` exists only to compare engine candidates. Its default
transforms can apply Unicode NFKC, trim surrounding whitespace, and collapse
repeated whitespace; field-specific transforms and aliases must be declared
explicitly. The raw value remains unchanged, and an equivalent comparison value is
not automatically suitable for publication.

Semantic interpretation belongs under `normalization`: structured dates,
historical geography, units, prices, and taxonomy. Keep this boundary strict. For
example, collapsing whitespace can help identify agreement, while expanding a
two-digit period or interpreting a scaled unit expression changes meaning and must
follow a profile rule with raw/std provenance.

## 7. Tune alignment conservatively

Choose `alignment.anchor_fields` that are relatively stable and discriminative.
Set a non-negative weight for every field used by the matcher and ensure the weights
sum to `1.0`. Do not use an amount alone as an anchor when punctuation and unit
notation are noisy. Keep `preserve_unmatched_rows: true` and avoid cross-page
alignment unless the parser supplies explicit continuation evidence.

Test alignment on duplicate-looking rows, blank repeated cells, a row present in
only one engine, and the first/last row of each page. High similarity is not proof
that two rows are the same observation.

Set `alignment.anchor_engine` to the stable reference source used for ordered
alignment, or `null` when the caller must choose it. This setting ranks alignment;
it never makes that engine authoritative.

## 8. Set consensus and review rules

Set `consensus.expected_sources` to the number expected for the run. A conservative
default is:

```yaml
auto_accept:
  normalized_unanimous_only: true
  allow_single_source: false
  allow_repeat_marker_resolution: false
```

Use only `unanimous`, `majority`, `conflict`, and `missing` as consensus statuses.
Conflicts, single-source cells, row alignment uncertainty, ditto expansion, and
semantic ambiguity should remain reviewable. Preserve all candidates after a
decision.

## 9. Configure repeat marks, dates, geography, units, and prices

- List recognized repeat markers and restrict inheritance to the previous record,
  same field, and same table. Preserve the raw marker. Cross-page inheritance needs
  a decision.
- Retain the date expression and configure allowed precision and any two-digit-year
  century rule. Unresolved dates remain unresolved.
- Keep historical geographic names. Add modern mappings as optional, versioned
  fields only.
- Keep quantity and price units raw; standardize explicitly and never insert a
  default merely because a column heading seems stable.
- Configure monetary or measured amounts as long-form observations when one record
  can contain several values. Represent source-reported conversions separately and
  prohibit unsourced conversion. Unit aliases must be profile-specific and
  conservative; ambiguous signs should remain unresolved unless surrounding source
  notation disambiguates them.

## 10. Require provenance and quality gates

At minimum require complete page identity, raw evidence for every standardized
value, explicit decisions for conflicts and single-source rows, price-to-record
referential integrity, and preservation of disagreements. Report both coverage and
uncertainty; never label OCR agreement as verified accuracy.

When a profile changes, increment its version and add a synthetic regression case
covering the new rule. A useful minimum test set contains:

- two independent engine files and at least one identical row;
- one character or numeric conflict;
- one row missing from an expected engine;
- one repeated-value marker;
- page offsets and a nullable printed label;
- multiple date precisions, units, and currencies;
- a grouped or source-reported price conversion;
- expected decisions, publication records, price rows, and a quality summary.

The repository fixture under `examples/synthetic/` supplies this baseline. Run:

```text
pytest tests/integration/test_synthetic_contract.py
```

Then run the full test suite and the repository's public-release check before
publishing a profile. Real PDFs, page images, OCR dumps, and extracted records stay
outside the public repository.
