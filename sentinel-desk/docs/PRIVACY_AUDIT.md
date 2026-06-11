# SentinelDesk Public Release Privacy Audit

Date: 2026-06-11

## Scope

Audit scope:

- project files under `sentinel-desk/`
- root LifeAgent README, changelog, and plan tracker
- runtime artifact patterns such as databases, screenshots, reports, evidence JSON, and ZIP packages
- text patterns for real URLs, local paths, emails, cookies, passwords, and secrets

## Current Result

Release artifact auditing is now executable through:

```bash
python3 -m sentineldesk privacy release-audit --path .
python3 -m sentineldesk privacy release-audit --path . --require-clean
```

The current local working tree is **not clean for direct public release packaging** because local development artifacts are present and correctly detected:

- `.agent-venv`
- `.demo`
- `sentineldesk.egg-info`
- Python `__pycache__/` directories

These artifacts are ignored by `.gitignore`, but they must be deleted or excluded before making a public ZIP/package from the local tree.

Use the release package command to exclude local artifacts without deleting the developer environment:

```bash
python3 -m sentineldesk privacy release-package --source . --output /tmp/sentineldesk.release.zip
```

To verify the package boundary, extract that ZIP into a temporary directory and run:

```bash
python3 -m sentineldesk privacy release-audit --path /tmp/extracted-sentineldesk --require-clean
```

The current implementation was verified by packaging the local tree to `/private/tmp/lifeagent-semantic-amount-filters-20260611.release.zip`, extracting it, and auditing the extracted tree with 118 scanned files and 0 release-artifact issues.

The redacted-output privacy audit remains separate:

```bash
python3 -m sentineldesk privacy audit --path <home>/artifacts --require-clean
```

It scans redacted reports and share packages for unredacted private data.

## Clean Release Criteria

A clean release tree must contain:

- no SQLite databases
- no screenshot image artifacts
- no redacted or raw evidence JSON artifacts
- no generated report HTML artifacts
- no share ZIP packages
- no Python bytecode cache files
- no local virtualenv or dependency build metadata
- no screen recording files

The remaining URL, email, path, password, and screenshot mentions in source text are expected synthetic or code/test references:

- `example.com`, `example.edu`, and `a@example.com` are test fixtures.
- `file://` appears in tests and documentation to verify redaction behavior.
- `/Users/example` appears only as a synthetic redaction test path.
- `password`, `cookie`, `screenshot`, and `sqlite` appear in privacy-boundary docs, extractor patterns, and schema/code references.
- localhost URLs are demo endpoints, not real portal data.

## Public Boundary

Before sharing:

- do not include `.demo/`
- do not include `.agent-venv/`
- do not include `~/.sentineldesk/`
- do not include Chrome profiles
- do not include `sentineldesk.egg-info/`
- do not include `__pycache__/`
- do not include `recordings/`
- do not include real portal URLs
- do not include cookies, DOM dumps, screenshots, local databases, traces, raw evidence, or local artifacts

Public demos should use only synthetic fixtures under `fixtures/portals/`.
