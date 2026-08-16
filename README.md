# Historical Table Data Pipeline

[简体中文](README.zh-CN.md)

An auditable, profile-driven pipeline for reconciling independent OCR transcriptions of **scanned historical record tables** into research data.

> **Scope:** v0.1 includes only a completely fictional synthetic example. It makes no claim of validation on any real-world corpus, document family, or publication, and it does not promise 100% transcription accuracy.

The software preserves raw OCR alternatives, creates explicit review candidates, applies machine-readable decisions, and validates provenance before publication. Multi-source agreement is evidence—not ground truth.

## Why this repository exists

Historical table digitization often mixes OCR, one-off scripts, spreadsheet edits, and undocumented judgment. This project separates those concerns into a reproducible sequence:

Its central idea is to compare sufficiently independent transcriptions: disagreements are routed to review, while agreement lowers the chance of an undetected independent error under explicit statistical assumptions. Correlated OCR failures can erase that benefit, so source-image sampling is still required; see the [methodology](docs/methodology.md#statistical-intuition-not-a-guarantee).

`candidate -> decision -> apply -> validate`

It provides:

- a Python package and one `historical-table` CLI;
- a canonical JSONL contract for independently produced OCR;
- profile-driven parsing, alignment, normalization, and QA;
- explicit review artifacts instead of silent corrections;
- stable record/cell identity and source provenance;
- research-facing record, long-form price, and quality-summary outputs;
- one portable Agent Skill for Codex, Claude Code, and other Agent Skills hosts.

Real source PDFs, page images, OCR dumps, and extracted datasets are **not published by default**. The repository includes synthetic fixtures only.

## Status and evidence

This is an alpha research release. `profiles/example-records.yaml` and all files under `examples/synthetic/` are deliberately fictional. They test the software contracts and review loop; they are not evidence of empirical OCR accuracy or support for any real document family. Adapting a real source requires a new or revised profile, representative page inspection, source-image auditing, and documented validation.

## Installation

Python 3.11 or later is required.

```bash
python -m venv .venv
```

Activate it on Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
```

Or on macOS/Linux:

```bash
source .venv/bin/activate
```

Install the core package from the checkout:

```bash
python -m pip install --upgrade pip
python -m pip install .
```

Install only the optional features you need:

```bash
# Development tests, linting, and builds
python -m pip install ".[dev]"

# Local PDF rendering
python -m pip install ".[pdf]"

# Optional OpenAI-compatible network OCR adapter
python -m pip install ".[ocr]"

# PDF, OCR, and research/analytical extras
python -m pip install ".[all]"
```

These commands intentionally use a regular install. Some Windows/Python combinations do not resolve editable `.pth` files correctly when the checkout path contains non-ASCII characters. Re-run the install command after changing package source.

The core offline reconciliation path does not require an OCR API key.

## Synthetic quick start

Run the built-in, non-network demonstration:

```bash
historical-table demo --output runs/demo
```

The demo reconciles the bundled synthetic OCR sources, compiles the review ledger into canonical cell decisions, validates the result, and publishes synthetic records.

To inspect every stage, run the same fixture explicitly:

```bash
historical-table profile-validate profiles/example-records.yaml

historical-table reconcile \
  --profile profiles/example-records.yaml \
  --input examples/synthetic/ocr/engine-a.jsonl \
  --input examples/synthetic/ocr/engine-b.jsonl \
  --output runs/synthetic
```

`reconcile` appends a content-derived run ID. Copy the printed `run_directory` and replace `RUN_DIR_FROM_RECONCILE` below:

```bash
historical-table review-export RUN_DIR_FROM_RECONCILE \
  --output runs/synthetic-review

historical-table review-apply RUN_DIR_FROM_RECONCILE \
  --decisions examples/synthetic/decisions/reconciliation.jsonl \
  --profile profiles/example-records.yaml \
  --output runs/synthetic-applications \
  --default-reviewer synthetic-fixture \
  --default-decided-at 2000-01-01T00:00:00Z
```

`review-apply` also appends a content-derived application ID. Copy its printed `application_directory` and replace `APPLICATION_DIR_FROM_REVIEW_APPLY`:

```bash
historical-table validate APPLICATION_DIR_FROM_REVIEW_APPLY \
  --profile profiles/example-records.yaml \
  --report runs/synthetic-validation.json

historical-table publish APPLICATION_DIR_FROM_REVIEW_APPLY \
  --profile profiles/example-records.yaml \
  --output runs/synthetic-publication
```

`review-export` emits canonical cell-decision templates. The checked-in ledger uses higher-level workflow events for readability; the CLI compiles them to the same cell contract before applying them. Validation and publication block unresolved cells by default. Use `--allow-unresolved` only when publishing unresolved values is an explicit, documented choice.

Use each subcommand's `--help` for the installed version. The synthetic manifest and expected artifacts are under [`examples/synthetic`](examples/synthetic/).

## Workflow

| Stage | CLI command | Network | Main result |
| --- | --- | --- | --- |
| Check configuration | `profile-validate` | No | Validated profile |
| Render selected pages | `render` | No | Local page images |
| Optional hosted OCR | `ocr --allow-network` | Yes | Canonical OCR JSONL |
| Reconcile sources | `reconcile` | No | Agreement/conflict candidates |
| Prepare review | `review-export` | No | Candidate packets and decision template |
| Apply decisions | `review-apply` | No | Compiled decisions and reviewed consensus |
| Verify contracts | `validate` | No | Validation and QA results |
| Create research outputs | `publish` | No | Records, long-form prices, quality summary |

For offline use, generate OCR with any engines you choose and convert their output to the canonical JSONL contract. The `ocr` command is optional, supports an OpenAI-compatible adapter, and refuses network use without explicit `--allow-network`.

## Profiles and data model

- Start a new record-table profile from [`profiles/template.yaml`](profiles/template.yaml).
- Read the [profile guide](docs/profile-guide.md) before adapting a new source.
- Read the [data model](docs/data-model.md) before producing JSONL.
- Keep raw and standardized values separate.
- Store prices in a long table; do not create one pair of columns per currency.
- Preserve physical PDF page identity, printed page labels, table identity, and source-row identity separately.

A structurally valid profile is not evidence that an unrelated document layout is supported.

## Optional Agent Skill

[`skills/digitize-historical-tables`](skills/digitize-historical-tables/) contains one model-neutral Agent Skill. It calls the same `historical-table` CLI and enforces candidate → decision → apply → validate.

- For a Codex repository-scoped installation, copy the folder under `.agents/skills/`.
- For a Claude Code project-scoped installation, copy it under `.claude/skills/`.
- Other Agent Skills hosts can load the same `SKILL.md` according to their discovery rules.

The workflow itself contains no host-specific tools or paths. `agents/openai.yaml` adds optional OpenAI UI metadata without changing the portable instructions. See the [official OpenAI Skill documentation](https://learn.chatgpt.com/docs/build-skills) and [Claude Code Skill documentation](https://code.claude.com/docs/en/slash-commands) for host-specific discovery and installation behavior.

## Repository layout

```text
src/historical_table_pipeline/   Python package
profiles/                        Profile template and fictional example profile
examples/synthetic/              Redistributable, synthetic end-to-end fixtures
tests/                           Unit and integration checks
skills/digitize-historical-tables/  Optional Agent Skill
docs/                            Architecture, methodology, model, limits, guides
```

## Documentation

- [Architecture](docs/architecture.md)
- [Methodology](docs/methodology.md)
- [Data model](docs/data-model.md)
- [Profile guide](docs/profile-guide.md)
- [Limitations](docs/limitations.md)
- [Publication checklist](docs/publication-checklist.md)
- [Security policy](SECURITY.md)
- [Contributing](CONTRIBUTING.md)

## Data, rights, and privacy

Apache-2.0 covers this repository's software and original documentation. It does not grant rights to source publications, scans, OCR transcriptions, or user-produced datasets. Before processing or releasing material, assess copyright, database rights, access conditions, privacy, and OCR-provider terms.

Do not commit `.env` files, API keys, real documents, local agent settings, run directories, logs, or backups. If you use hosted OCR, document where pages are sent and obtain the necessary authorization.

## Citation and license

Use [`CITATION.cff`](CITATION.cff) and cite the exact release or commit, profile version, input identifiers and hashes, OCR sources, and review policy used. The software is licensed under [Apache-2.0](LICENSE); additional attribution and data-license boundaries are in [`NOTICE`](NOTICE).
