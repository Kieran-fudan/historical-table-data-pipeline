# Methodology

## Research principle

The pipeline uses multiple OCR transcriptions as independent evidence. Agreement increases confidence but is not ground truth: engines may share training data, preprocessing failures, or the same plausible hallucination. The source image and an auditable review trail remain authoritative evidence.

## 1. Define the observation contract

Start from a profile that states:

- the source collection and table-family identity;
- the table geometry and observation unit;
- physical, printed, and source page identifiers where available;
- raw fields and standardized fields;
- normalization rules that are safe before comparison;
- validations required before publication.

Run `historical-table profile-validate` before processing a document. A valid profile is necessary but not sufficient: visually inspect representative pages before reusing a profile on a new source.

## 2. Obtain independent OCR transcriptions

Use at least two OCR runs that are independent enough to provide useful disagreement signals. They may come from different engines, prompts, preprocessing settings, or human transcription. Record the engine/source label and retain the unmodified text.

### Statistical intuition, not a guarantee

Under an idealized model in which an odd number $n$ of sources have independent, identically distributed single-cell error probability $p$, the probability that a simple majority is wrong is

$$
P(\text{majority wrong}) =
\sum_{k=\lceil n/2 \rceil}^{n} {n \choose k} p^k(1-p)^{n-k}.
$$

For two independent sources with error probabilities $p_1$ and $p_2$, the event that they agree while both are wrong is a subset of both sources being wrong, so its probability is at most $p_1p_2$; agreement on the same specific wrong value is usually rarer. A disagreement, however, does not identify which source is correct and must remain reviewable.

These calculations are intuition under strong assumptions, not an accuracy claim. Shared preprocessing, layouts, training data, prompts, or systematic character confusions create correlated errors and can remove much of the apparent benefit. The pipeline therefore uses agreement only to route work and record evidence. Estimate real transcription accuracy through a documented random or stratified sample checked against the source images, and report the sampling design, denominator, errors, and uncertainty.

The optional `historical-table ocr` adapter supports OpenAI-compatible endpoints and requires explicit `--allow-network`. Any engine can instead be used offline if its results are converted to the canonical JSONL contract.

Do not silently send documents to a network service. Review rights, privacy, retention, cost, and provider terms first.

## 3. Preserve raw and standardized representations

Store exactly what each source reported. Apply only conservative comparison normalization—such as explicitly configured whitespace or punctuation handling—and preserve the raw form next to the standardized form. Never discard an alternative solely because it is in the minority.

Stable document, page, record, and cell identifiers make later decisions reproducible even when exports are reordered.

## 4. Reconcile sources into candidates

`historical-table reconcile` aligns logical records and cells under the selected profile. For each field it retains the contributing sources and emits a status such as agreement, conflict, missing evidence, or unresolved alignment.

Automatic agreement means only that the configured comparison found equivalent values. It is evidence for review and QA, not an accuracy guarantee.

## 5. Review candidates and record decisions

Export candidates with `historical-table review-export`. Review the source alternatives, row context, page identity, and any available page image. Record one explicit decision per review item using the decision contract.

Valid outcomes include selecting a supported value, entering a justified correction with provenance, or leaving the item unresolved. Do not hide uncertainty by guessing. Do not edit generated record files directly.

Detailed review rules are in [the Skill review policy](../skills/digitize-historical-tables/references/review-policy.md).

## 6. Apply decisions

Use `historical-table review-apply` so the CLI can check identifiers, duplicate cell targets, chosen values, and candidate references. Application must create a new derived artifact and leave OCR sources and candidate packets unchanged.

## 7. Validate

Run `historical-table validate` after every decision batch. Validation should cover, as applicable:

- schema and required fields;
- stable identifier uniqueness;
- source and engine provenance;
- unresolved or conflicting candidates;
- page and row coverage;
- quantity, date, unit, currency, and price constraints defined by the profile;
- referential integrity between records and long-form price observations.

A passing validation result means the declared checks passed. It does not establish that every transcription is correct.

## 8. Publish with evidence

`historical-table publish` creates research-facing records, long-form price observations, and a quality summary. Cite the code release or commit, profile, input identifiers and hashes, OCR engines, and review policy. Keep unresolved values and exclusion rules visible in documentation.

The repository does not publish real PDFs, OCR dumps, or extracted real-world datasets by default. Users are responsible for source rights and any separate data release.

## Evidence base

The repository includes only a completely fictional synthetic profile and fixtures. They exercise the contracts, decision compiler, validation gates, and publication path; they do not establish empirical OCR accuracy or support for any real corpus, publication, or matrix-style table family.
