# LifeAgent

LifeAgent currently hosts **SentinelDesk**, the latest implementation direction for the project.

SentinelDesk is a local-first, fail-loud portal sentinel for high-stakes deadlines. It does not try to be a horizontal job portal monitor. Its core promise is:

> If the monitor cannot verify the portal state, it must alert instead of silently assuming nothing changed.

## Current Project

The active implementation lives in:

```bash
cd sentinel-desk
```

Run the local demo:

```bash
python3 -m sentineldesk --home .demo demo record-prep
python3 -m sentineldesk --home .demo serve --port 8787
```

Run tests:

```bash
cd sentinel-desk
python3 -B -m unittest discover -s tests -v
```

## What Changed From The Old Plan

The previous **JobOps Guard** implementation was removed from the root of this folder because the plan pivoted away from generic job portal monitoring, JD review, form filling, and a broad CLI/web app pitch. Remaining job-specific demo fixtures were also removed from SentinelDesk.

The current plan keeps only the parts that matter for the newer direction:

- local browser/session boundary
- deterministic capture and diff
- session health detection
- fail-loud uncertainty alerts
- evidence bundles
- high-stakes vertical portal demos
- privacy-first public portfolio fixtures

## Privacy Boundary

Do not commit runtime state, real portal URLs, screenshots, DOM dumps, cookies, traces, or local database files. Public demos should use synthetic fixtures under `sentinel-desk/fixtures/portals/`.
