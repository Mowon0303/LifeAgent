# Email Extraction Eval Report

- Generated at: 2026-06-13T00:24:57+00:00
- Golden set: `evals/golden` (144 cases)
- Target under test: `sentineldesk.email.extract.extract_email_facts`
- High-confidence threshold: 0.75 (same boundary the assistant uses for `high` confidence answers)
- Labels are semantic ground truth for a life-admin assistant; expanded date forms, relative deadlines, non-dollar currencies, spelled-out dollar amounts, and expanded action verbs stay labeled even when extractor support is partial, so recall reflects true capability.

## Golden Set Composition

| Category | Cases |
| --- | --- |
| adversarial | 10 |
| bank_card | 14 |
| billing_utility | 15 |
| edge_cases | 18 |
| immigration_school | 16 |
| insurance_medical | 13 |
| lease_rent | 16 |
| negatives | 17 |
| subscription_services | 12 |
| tax_government | 13 |

## Overall Metrics

### Raw layer (every extracted fact)

| Kind | TP | FP | FN | Precision | Recall | F1 |
| --- | --- | --- | --- | --- | --- | --- |
| deadline | 122 | 0 | 0 | 1.000 | 1.000 | 1.000 |
| amount | 76 | 0 | 0 | 1.000 | 1.000 | 1.000 |
| action | 85 | 0 | 0 | 1.000 | 1.000 | 1.000 |

### High-confidence layer (confidence >= 0.75)

| Kind | TP | FP | FN | Precision | Recall | F1 |
| --- | --- | --- | --- | --- | --- | --- |
| deadline | 122 | 0 | 0 | 1.000 | 1.000 | 1.000 |
| amount | 76 | 0 | 0 | 1.000 | 1.000 | 1.000 |
| action | 0 | 0 | 114 | n/a | 0.000 | n/a |

Note: action facts carry a fixed confidence of 0.68, so the high-confidence layer contains no action predictions by construction.

## Confidence Calibration (deadline/amount)

Precision per confidence bucket. Retained deadline and amount facts are calibrated above the high-confidence threshold after false-positive filters run, so the low bucket is expected to be empty unless a future extractor adds intentionally uncertain retained facts.

| Kind | High bucket precision (n) | Low bucket precision (n) |
| --- | --- | --- |
| deadline | 1.000 (122) | n/a (0) |
| amount | 1.000 (76) | n/a (0) |

## Per-Category Metrics (raw layer)

| Category | Deadline P/R | Amount P/R | Action P/R |
| --- | --- | --- | --- |
| adversarial | 1.000 / 1.000 | 1.000 / 1.000 | n/a / n/a |
| bank_card | 1.000 / 1.000 | 1.000 / 1.000 | 1.000 / 1.000 |
| billing_utility | 1.000 / 1.000 | 1.000 / 1.000 | 1.000 / 1.000 |
| edge_cases | 1.000 / 1.000 | 1.000 / 1.000 | 1.000 / 1.000 |
| immigration_school | 1.000 / 1.000 | 1.000 / 1.000 | 1.000 / 1.000 |
| insurance_medical | 1.000 / 1.000 | 1.000 / 1.000 | 1.000 / 1.000 |
| lease_rent | 1.000 / 1.000 | 1.000 / 1.000 | 1.000 / 1.000 |
| negatives | n/a / n/a | n/a / n/a | n/a / n/a |
| subscription_services | 1.000 / 1.000 | 1.000 / 1.000 | 1.000 / 1.000 |
| tax_government | 1.000 / 1.000 | 1.000 / 1.000 | 1.000 / 1.000 |

## Failure Detail (raw layer)

Every case with at least one false positive or false negative.

| Case | Kind | False positives | False negatives |
| --- | --- | --- | --- |

## Reproduce

```bash
cd sentinel-desk
python3 -B -m sentineldesk eval email-extract --golden evals/golden --report-md docs/EVAL_REPORT.md
```
