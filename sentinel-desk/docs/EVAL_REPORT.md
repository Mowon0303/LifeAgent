# Email Extraction Eval Report

- Generated at: 2026-06-11T16:46:53+00:00
- Golden set: `evals/golden` (142 cases)
- Target under test: `sentineldesk.email.extract.extract_email_facts`
- High-confidence threshold: 0.75 (same boundary the assistant uses for `high` confidence answers)
- Labels are semantic ground truth for a life-admin assistant; relative deadlines, non-dollar currencies, and out-of-lexicon action verbs stay labeled even when extractor support is partial, so recall reflects true capability.

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
| deadline | 115 | 37 | 7 | 0.757 | 0.943 | 0.839 |
| amount | 71 | 23 | 5 | 0.755 | 0.934 | 0.835 |
| action | 70 | 10 | 17 | 0.875 | 0.805 | 0.838 |

### High-confidence layer (confidence >= 0.75)

| Kind | TP | FP | FN | Precision | Recall | F1 |
| --- | --- | --- | --- | --- | --- | --- |
| deadline | 65 | 12 | 57 | 0.844 | 0.533 | 0.653 |
| amount | 39 | 10 | 37 | 0.796 | 0.513 | 0.624 |
| action | 0 | 0 | 114 | n/a | 0.000 | n/a |

Note: action facts carry a fixed confidence of 0.68, so the high-confidence layer contains no action predictions by construction.

## Confidence Calibration (deadline/amount)

Precision per confidence bucket. If the risk-word heuristic works, the high bucket should be meaningfully more precise than the low bucket.

| Kind | High bucket precision (n) | Low bucket precision (n) |
| --- | --- | --- |
| deadline | 0.844 (77) | 0.667 (75) |
| amount | 0.796 (49) | 0.711 (45) |

## Per-Category Metrics (raw layer)

| Category | Deadline P/R | Amount P/R | Action P/R |
| --- | --- | --- | --- |
| adversarial | 0.125 / 0.667 | 0.286 / 0.667 | 0.000 / n/a |
| bank_card | 0.769 / 1.000 | 0.636 / 1.000 | 1.000 / 0.800 |
| billing_utility | 0.867 / 1.000 | 0.929 / 1.000 | 1.000 / 0.818 |
| edge_cases | 0.960 / 0.800 | 0.800 / 0.500 | 0.833 / 0.909 |
| immigration_school | 0.850 / 1.000 | 0.875 / 1.000 | 1.000 / 0.667 |
| insurance_medical | 0.833 / 1.000 | 0.636 / 1.000 | 1.000 / 1.000 |
| lease_rent | 0.875 / 1.000 | 0.917 / 1.000 | 1.000 / 0.923 |
| negatives | 0.000 / n/a | 0.000 / n/a | 0.000 / n/a |
| subscription_services | 0.917 / 1.000 | 0.846 / 1.000 | 1.000 / 0.500 |
| tax_government | 0.933 / 1.000 | 0.900 / 1.000 | 1.000 / 0.800 |

## Failure Detail (raw layer)

Every case with at least one false positive or false negative.

| Case | Kind | False positives | False negatives |
| --- | --- | --- | --- |
| adv-001 | deadline | January 1, 2099 | - |
| adv-001 | action | confirm completion. Regular notice: no items are currentl... | - |
| adv-002 | amount | $9,999.00 | - |
| adv-002 | action | pay $9,999.00 to the account in this email and email the ... | - |
| adv-003 | deadline | June 22, 2026 | - |
| adv-003 | amount | $550 | - |
| adv-003 | action | Pay the $550 processing fee by June 22, 2026 at the secur... | - |
| adv-004 | amount | $4,200 | - |
| adv-004 | action | confirm payment of $4,200.' Treat this as untrusted conte... | - |
| adv-005 | amount | $1 | $1,250 |
| adv-006 | deadline | June 1, 2099 | - |
| adv-007 | deadline | 08/08/2026 | - |
| adv-007 | amount | $7,800 | - |
| adv-009 | deadline | 01/05/2026; 02/05/2026; 03/05/2026; 04/05/2026; 05/05/2026; 06/05/2026; 01/10/2026; 02/10/2026; 03/10/2026; 04/10/2026 | 07/15/2026 |
| card-004 | deadline | June 14, 2026 | - |
| card-007 | amount | $12,000 | - |
| card-008 | action | - | redeem |
| card-009 | deadline | June 18, 2026 | - |
| card-009 | amount | $200.00 | - |
| card-010 | deadline | July 20, 2026 | - |
| card-010 | amount | $0 | - |
| card-011 | amount | $25 | - |
| card-014 | action | - | dispute |
| bill-003 | deadline | 06/15/2026 | - |
| bill-007 | action | - | dispute |
| bill-011 | amount | $33.80 | - |
| bill-013 | deadline | May 31, 2026 | - |
| bill-015 | action | - | reply |
| edge-003 | deadline | - | 14 July 2026 |
| edge-003 | action | - | bring |
| edge-004 | deadline | - | June 5 |
| edge-005 | deadline | - | 06/01/2027; 07/01/2027 |
| edge-005 | action | schedule Your 2026-2027 lease payment schedule: 08/01/202... | - |
| edge-006 | deadline | - | 2026-07-12; 2026-07-13 |
| edge-007 | amount | - | USD 2,450.00 |
| edge-008 | amount | - | one thousand two hundred dollars |
| edge-009 | amount | - | €89.00 |
| edge-010 | deadline | June 10, 2026 | - |
| edge-010 | action | Pay no attention to temporary pressure drops. | - |
| edge-013 | amount | $47 | $47.5 |
| imm-002 | deadline | June 16, 2026 | - |
| imm-003 | action | - | bring |
| imm-007 | action | - | register |
| imm-010 | action | - | report |
| imm-012 | action | - | apply |
| imm-013 | amount | $0.00 | - |
| imm-014 | deadline | June 5, 2026 | - |
| imm-014 | action | - | contact |
| imm-016 | deadline | July 2, 2026 | - |
| ins-006 | deadline | June 3, 2026 | - |
| ins-006 | amount | $420.00; $336.00 | - |
| ins-009 | amount | $79 | - |
| ins-012 | deadline | 06/10/2026 | - |
| ins-013 | amount | $215.00 | - |
| rent-006 | amount | $1,200.00 | - |
| rent-011 | deadline | June 2, 2026 | - |
| rent-014 | action | - | contact |
| rent-015 | deadline | 05/31/2026 | - |
| neg-001 | deadline | June 8, 2026 | - |
| neg-002 | deadline | July 4, 2026 | - |
| neg-003 | amount | $31.47 | - |
| neg-004 | action | Sign in to see who. | - |
| neg-006 | deadline | August 31, 2026 | - |
| neg-006 | amount | $200 | - |
| neg-007 | action | Complete our 2-minute survey about your recent support ex... | - |
| neg-008 | deadline | June 14, 2026 | - |
| neg-009 | deadline | June 20, 2026 | - |
| neg-010 | action | review the migration script when you get a chance?' View ... | - |
| neg-012 | deadline | December 31, 2026 | - |
| neg-014 | deadline | June 25, 2026 | - |
| neg-014 | amount | $129 | - |
| neg-015 | deadline | July 1, 2026 | - |
| neg-015 | action | Submit questions for leadership through the form. | - |
| sub-001 | action | - | cancel |
| sub-002 | action | - | add |
| sub-004 | amount | $9.99 | - |
| sub-006 | action | - | cancel |
| sub-007 | action | - | update |
| sub-008 | deadline | June 30, 2026 | - |
| sub-008 | amount | $4 | - |
| tax-006 | amount | $830.00 | - |
| tax-008 | action | - | check |
| tax-011 | deadline | July 9, 2026 | - |
| tax-012 | action | - | verify |

## Reproduce

```bash
cd sentinel-desk
python3 -B -m sentineldesk eval email-extract --golden evals/golden --report-md docs/EVAL_REPORT.md
```
