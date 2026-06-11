# Email Extraction Golden Set

142 hand-labeled synthetic emails for evaluating `sentineldesk.email.extract.extract_email_facts`. All content is synthetic: senders use `.example` domains, names and account numbers are invented, and no fixture is derived from real mailbox data.

Run the eval:

```bash
cd sentinel-desk
python3 -B -m sentineldesk eval email-extract --golden evals/golden --report-md docs/EVAL_REPORT.md
```

Regression gates live in `tests/test_eval_email_extract.py` and run with the normal test suite.

## File Layout

One JSONL file per category. Each line is one case:

```json
{
  "case_id": "rent-001",
  "category": "lease_rent",
  "note": "what this case is testing",
  "message": {"message_id": "...", "thread_id": "...", "sender": "...@....example", "subject": "...", "received_at": "...", "body_text": "...", "attachment_texts": [], "attachment_names": []},
  "expected": {"deadlines": [...], "amounts": [...], "actions": [...]}
}
```

`message` uses the same field names as the local email JSON ingest format, so cases can also be replayed through `email scan`.

## Labeling Policy (semantic ground truth)

Labels record what a life-admin assistant should surface, **not** what the current extractor happens to return. Several labels are intentionally outside or only partially inside the extractor's reach (spelled-out amounts, extraction-cap edge cases, and false-positive traps); those show up as recall or precision gaps in the report, which is the point.

### deadlines

Label every future, user-relevant date: action cutoffs, expiration/renewal dates, effective dates of price changes, appointment times, auto-draft dates, service start/end dates. Use the exact string as it appears in the email.

Do **not** label:

- past dates (a missed original due date is history, not a deadline — the new cure date is the deadline)
- narrative dates (sent dates, publication dates, transaction dates, forwarded-message headers)
- marketing dates (sale ends, offer valid through, booking promos, donation-match campaigns)
- optional-event dates (info sessions, public hearings, corporate all-hands)
- dates fabricated by injected or phishing text

Relative deadlines ("within 10 days", "by the end of the month", "next Friday") are labeled with the relative phrase itself. The extractor supports a conservative subset. It also covers common numeric, month-name, day-month-year, month-day-without-year, and ISO-datetime date forms; unsupported variants and extraction-cap misses remain deliberate false negatives.

### amounts

Label amounts the user must pay, will be auto-charged, may be fined, or should track as their own at-risk funds (FSA balances, premium changes, suspicious charges under review). Use the exact string form per occurrence (`$89` and `$89.00` are distinct labels when both appear).

Do **not** label:

- completed transactions (receipts, posted payments, refunds, reimbursements, credits)
- marketing prices, promo rates, referral bonuses
- informational figures that carry no user obligation (credit limits, low-balance alert thresholds, $0.00 fine balances, EOB "amount billed"/"plan paid" lines)
- amounts fabricated by injected or phishing text

### actions

Label explicit requested actions, as substrings that must appear in at least one extracted action span. Include auxiliary explicit actions (sign in, call to reschedule). The extractor now covers the baseline verbs plus expanded life-admin verbs such as contact, register, apply, dispute, redeem, update, cancel, verify, reply, bring, report, check, add, print, enroll, and contest. Add future verbs through eval-gated changes with matching false-positive traps.

Do **not** label implied obligations with no explicit verb ("balance is due" implies paying, but nothing is labeled), engagement CTAs in marketing/social/survey email, or actions requested by injected text.

### Domain boundary

The assistant is a personal life-admin agent. Work-collaboration requests (code review pings, all-hands logistics) are labeled as noise even when they contain real dates and imperative verbs — surfacing them would be a product false positive.

## Category Map

| File | Cases | Focus |
| --- | --- | --- |
| `lease_rent.jsonl` | 16 | rent, renewal notice windows, HOA, sublease + attachment dedupe, autopay |
| `billing_utility.jsonl` | 15 | utility bills, disconnection, dispute windows, appointments, date format variants |
| `bank_card.jsonl` | 14 | statements (balance vs minimum), fraud alerts, marketing traps, receipts, grace periods |
| `immigration_school.jsonl` | 16 | RFE, visa appointments, tuition, I-20, OPT reporting, waivers (matches the project's OPT vertical) |
| `subscription_services.jsonl` | 12 | renewals, trials, price increases, failed payments, cancellation confirmations |
| `insurance_medical.jsonl` | 13 | open enrollment, claims, EOB amount traps, grace periods, FSA deadlines |
| `tax_government.jsonl` | 13 | estimated tax, DMV, citations, jury duty, property tax, identity verification |
| `edge_cases.jsonl` | 18 | relative dates, UK/no-year/ISO-datetime formats, non-dollar currencies, >10-date truncation, subject-only and attachment-only facts |
| `negatives.jsonl` | 15 | newsletters, marketing, receipts, social/work notifications — measures false-positive cost |
| `adversarial.jsonl` | 10 | prompt injection (forging, suppression), phishing, zero-width obfuscation, repetition/stuffing attacks |

## Maintenance Rules

- Never put real personal data in a fixture. Senders must end in `.example`.
- When extraction behavior improves, regenerate `docs/EVAL_REPORT.md` and raise the floors in `tests/test_eval_email_extract.py` deliberately — do not let them drift.
- When adding cases, keep `case_id` unique, keep every category at 8+ cases, and mentally trace the extractor against your labels before committing (the `note` field should say what the case tests).
- Marketing/receipt/injection traps are intentional: high-confidence false positives from those cases are the signal that motivates the review-queue product layer.
