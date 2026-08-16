# Limitations

## Scope is intentionally narrow

This release demonstrates scanned historical **record tables** whose rows can be mapped to a configured observation schema.

The included profile and fixtures are completely fictional and test software behavior only. This repository makes no claim that the pipeline has been validated on any real corpus or document family. Real sources require separate evaluation and may require a new profile, parser, or both.

## Layout limitations

The current record-table assumptions may not handle these reliably:

- deeply nested or multi-row headers;
- matrix tables with periods or categories spread across columns;
- vertical typesetting or complex mixed reading order;
- charts, maps, narrative pages, footnote-heavy appendices, and handwritten marginalia;
- tables split into visually independent panels on one page;
- continuation rows whose identity cannot be recovered from adjacent context;
- damaged, skewed, low-resolution, or partially missing scans.

Passing profile validation does not demonstrate visual compatibility with a new document.

## OCR and consensus limitations

- OCR engines can make correlated errors.
- Agreement can be confidently wrong.
- Numbers, decimal points, minus signs, ditto marks, legacy currency notation, and abbreviated dates are especially error-prone.
- A missing value and an intentionally blank cell may look identical.
- Engine-reported confidence scores are not calibrated across providers.
- Reconciliation quality depends on correct page, row, and cell alignment.

The pipeline does not promise 100% accuracy and must not be used as a substitute for source inspection.

## Semantic limitations

Standardizing a transcription is different from interpreting a source concept. Currency denomination, unit scale, total versus unit price, grouped items, organization identity, and historical place names can require domain expertise. A profile encodes explicit transformations; it cannot infer every source-specific convention safely.

Published data should distinguish raw text, standardized text, derived fields, reviewer decisions, and unresolved ambiguity.

## Provider and operational limitations

The optional network OCR command supports an OpenAI-compatible adapter, not every provider's native API. Network processing may incur fees and may transmit protected or sensitive material to a third party. Offline imports remain available through canonical JSONL.

Large scans can require substantial disk space and processing time. Reproducibility also depends on retaining exact inputs, profiles, software versions, and decisions.

## Rights and privacy

This repository's Apache-2.0 license covers its software and original documentation only. It does not grant permission to copy or publish source scans, OCR transcriptions, extracted datasets, personal information, or third-party layouts. Users must assess copyright, database rights, contractual restrictions, privacy, and provider terms for their own material.
