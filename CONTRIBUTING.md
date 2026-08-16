# Contributing

Thank you for improving the pipeline. Contributions should strengthen reproducibility, provenance, or support for a clearly documented table family.

## Development setup

1. Create a virtual environment with a Python version supported by `pyproject.toml`.
2. Install the project and development dependencies from the repository root.
3. Run the test suite before making changes.
4. Use only synthetic or redistributable fixtures.

The exact install and test commands are documented in the README and CI workflow so local and automated checks stay aligned.

## Design rules

- Keep parsing, reconciliation, decisions, application, and validation separate.
- Preserve raw values and source provenance alongside standardized values.
- Express document-specific behavior in a profile; do not add publication-specific branches to the core without a general contract.
- Treat multi-OCR agreement as evidence, not truth.
- Require an explicit decision for ambiguous or conflicting candidates.
- Keep outputs deterministic for identical inputs, profiles, and decisions.
- Avoid in-place edits of source material.

## Profiles

A new profile must include:

- a documented table shape and observation unit;
- field mappings and normalization boundaries;
- synthetic fixtures covering both ordinary and ambiguous cases;
- expected outputs and validation summaries;
- an explicit statement of what was actually tested.

Do not describe a profile as supporting a broader document family based on one source or one table design.

## Documentation

Update both `README.md` and `README.zh-CN.md` when user-visible behavior, commands, or scope changes. Record methodology changes in `docs/methodology.md` and newly discovered limits in `docs/limitations.md`.

## Pull-request checklist

- [ ] No real PDFs, page images, OCR dumps, extracted real data, credentials, logs, or local settings are included.
- [ ] Tests use synthetic or clearly redistributable material.
- [ ] Candidate, decision, apply, and validation boundaries remain auditable.
- [ ] Stable IDs and provenance remain intact.
- [ ] Tests and Skill validation pass.
- [ ] Documentation makes no unsupported accuracy or scope claims.
- [ ] Third-party licensing implications have been reviewed.

By submitting a contribution, you agree that it is licensed under Apache-2.0 and that you have the right to contribute it.
