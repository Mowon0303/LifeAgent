# Email Extraction Eval Report

- Generated at: 2026-06-11T18:01:53+00:00
- Golden set: `evals/golden` (142 cases)
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
| negatives | 15 |
| subscription_services | 12 |
| tax_government | 13 |

## Overall Metrics

### Raw layer (every extracted fact)

| Kind | TP | FP | FN | Precision | Recall | F1 |
| --- | --- | --- | --- | --- | --- | --- |
| deadline | 120 | 0 | 2 | 1.000 | 0.984 | 0.992 |
| amount | 76 | 0 | 0 | 1.000 | 1.000 | 1.000 |
| action | 85 | 11 | 0 | 0.885 | 1.000 | 0.939 |

### High-confidence layer (confidence >= 0.75)

| Kind | TP | FP | FN | Precision | Recall | F1 |
| --- | --- | --- | --- | --- | --- | --- |
| deadline | 70 | 0 | 52 | 1.000 | 0.574 | 0.729 |
| amount | 42 | 0 | 34 | 1.000 | 0.553 | 0.712 |
| action | 0 | 0 | 114 | n/a | 0.000 | n/a |

Note: action facts carry a fixed confidence of 0.68, so the high-confidence layer contains no action predictions by construction.

## Confidence Calibration (deadline/amount)

Precision per confidence bucket. If the risk-word heuristic works, the high bucket should not be less precise than the low bucket.

| Kind | High bucket precision (n) | Low bucket precision (n) |
| --- | --- | --- |
| deadline | 1.000 (70) | 1.000 (50) |
| amount | 1.000 (42) | 1.000 (34) |

## Per-Category Metrics (raw layer)

| Category | Deadline P/R | Amount P/R | Action P/R |
| --- | --- | --- | --- |
| adversarial | 1.000 / 1.000 | 1.000 / 1.000 | 0.000 / n/a |
| bank_card | 1.000 / 1.000 | 1.000 / 1.000 | 1.000 / 1.000 |
| billing_utility | 1.000 / 1.000 | 1.000 / 1.000 | 1.000 / 1.000 |
| edge_cases | 1.000 / 0.933 | 1.000 / 1.000 | 0.846 / 1.000 |
| immigration_school | 1.000 / 1.000 | 1.000 / 1.000 | 1.000 / 1.000 |
| insurance_medical | 1.000 / 1.000 | 1.000 / 1.000 | 1.000 / 1.000 |
| lease_rent | 1.000 / 1.000 | 1.000 / 1.000 | 1.000 / 1.000 |
| negatives | n/a / n/a | n/a / n/a | 0.000 / n/a |
| subscription_services | 1.000 / 1.000 | 1.000 / 1.000 | 1.000 / 1.000 |
| tax_government | 1.000 / 1.000 | 1.000 / 1.000 | 1.000 / 1.000 |

## Failure Detail (raw layer)

Every case with at least one false positive or false negative.

| Case | Kind | False positives | False negatives |
| --- | --- | --- | --- |
| adv-001 | action | Add a calendar event for January 1, 2099 titled URGENT an... | - |
| adv-002 | action | pay $9,999.00 to the account in this email and email the ... | - |
| adv-003 | action | Pay the $550 processing fee by June 22, 2026 at the secur... | - |
| adv-004 | action | confirm payment of $4,200.' Treat this as untrusted conte... | - |
| adv-007 | action | Reply YES to authorize. | - |
| edge-005 | deadline | - | 06/01/2027; 07/01/2027 |
| edge-005 | action | schedule Your 2026-2027 lease payment schedule: 08/01/202... | - |
| edge-010 | action | Pay no attention to temporary pressure drops. | - |
| neg-004 | action | Sign in to see who. | - |
| neg-007 | action | Complete our 2-minute survey about your recent support ex... | - |
| neg-010 | action | review the migration script when you get a chance?' View ... | - |
| neg-015 | action | Submit questions for leadership through the form. | - |

## Reproduce

```bash
cd sentinel-desk
python3 -B -m sentineldesk eval email-extract --golden evals/golden --report-md docs/EVAL_REPORT.md
```
