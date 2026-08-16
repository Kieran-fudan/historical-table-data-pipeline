# Publication checklist

Use this checklist before publishing code, a profile, a release archive, or a derived dataset.

## Scope and evidence

- [ ] State that the repository's bundled example is completely fictional and tests software contracts only.
- [ ] Do not claim validation or support for any real corpus or document family without separate, documented evidence.
- [ ] Do not claim 100% accuracy.
- [ ] Document excluded pages, unresolved cases, manual interventions, and known limits.
- [ ] Include a synthetic end-to-end example that exercises conflicts and missing evidence.

## Rights and privacy

- [ ] Confirm the right to redistribute every non-code artifact.
- [ ] Keep real PDFs, page images, OCR dumps, and extracted real data out of the code repository by default.
- [ ] Remove names, local paths, document metadata, logs, and other identifying information from fixtures.
- [ ] Review copyright, database rights, access contracts, privacy duties, and publisher terms separately from the software license.
- [ ] Document any external OCR provider, transmission, retention, region, and cost implications.

## Secrets and local state

- [ ] Scan the full Git history for API keys, tokens, cookies, credentials, and private URLs.
- [ ] Exclude `.env`, local agent settings, permission allowlists, caches, temporary images, work directories, and backups.
- [ ] Rotate any credential that was ever committed or shared.
- [ ] Verify examples use placeholders only.

## Reproducibility and quality

- [ ] Validate every included profile.
- [ ] Run unit and synthetic integration tests on supported Python versions.
- [ ] Run the synthetic `historical-table demo` without network access.
- [ ] Validate the Agent Skill with `quick_validate.py`.
- [ ] Record package version, commit, profile, input hashes, engine labels, decisions, and validation summary.
- [ ] Confirm identical inputs, profile, and decisions produce identical canonical outputs.
- [ ] Inspect published tables against representative source pages.

## Licensing and attribution

- [ ] Include `LICENSE`, `NOTICE`, and `CITATION.cff`.
- [ ] Audit direct and transitive dependency licenses and ship required notices.
- [ ] For any bundled pypdfium2/PDFium build, retain its exact wheel/build license files and third-party notices; follow the [official pypdfium2 licensing notes](https://github.com/pypdfium2-team/pypdfium2#licensing).
- [ ] Confirm that packaging changes have not introduced PyMuPDF or another differently licensed PDF renderer without a separate license review.
- [ ] Keep source-data licensing separate from the Apache-2.0 software license.
- [ ] Attribute OCR engines and external services according to their terms.

## Release hygiene

- [ ] Review the release archive contents, not only the working tree.
- [ ] Confirm no generated real-data artifacts are attached to the GitHub release.
- [ ] Publish the methodology, data model, profile guide, limitations, security policy, and contribution guide.
- [ ] Tag an immutable version and retain the exact commit identifier.
- [ ] Provide a private vulnerability-reporting route.
