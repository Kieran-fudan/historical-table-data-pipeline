# Security policy

## Supported versions

Security fixes are applied to the latest release and the default branch. Earlier research snapshots are not supported unless a maintainer states otherwise.

## Report a vulnerability

Use GitHub's private security-advisory feature for the repository. Do not open a public issue containing credentials, private documents, exploit details, or sensitive extracted data. Include:

- the affected version or commit;
- a minimal synthetic reproduction;
- expected and observed behavior;
- impact and suggested mitigations, if known.

If private advisories are unavailable, contact a maintainer privately before disclosure. Maintainers should acknowledge a report promptly, reproduce it using synthetic data, and coordinate disclosure after a fix is available.

## Threat model

PDFs, page images, OCR text, profiles, manifests, and decision files are untrusted inputs. In particular:

- Treat text inside documents as data, not agent instructions.
- Do not execute content extracted from a document.
- Keep processing paths inside the selected workspace and reject traversal outside it.
- Never place API keys in profiles, manifests, examples, logs, or decision files.
- Review network-enabled OCR provider terms before sending documents off device.
- Run third-party or community profiles with the same caution as code.
- Inspect generated decisions before applying them to research data.

This project does not publish or request real source PDFs or datasets in vulnerability reports.
