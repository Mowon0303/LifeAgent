"""Compiled regexes, cue word lists, and confidence constants used by the email
fact extractor. Separated from the extraction algorithm in ``extract.py`` so the
pattern dictionary can be read and tuned on its own.
"""

from __future__ import annotations

import re


AMOUNT_RE = re.compile(
    r"(?<!\w)(?:"
    r"[$€£¥￥]\s*[0-9][0-9,]*(?:\.[0-9]{1,2})?|"
    r"(?:USD|EUR|GBP|CNY|RMB)\s+[0-9][0-9,]*(?:\.[0-9]{1,2})?"
    r")\b",
    re.IGNORECASE,
)
SPELLED_NUMBER_WORDS = (
    "zero",
    "one",
    "two",
    "three",
    "four",
    "five",
    "six",
    "seven",
    "eight",
    "nine",
    "ten",
    "eleven",
    "twelve",
    "thirteen",
    "fourteen",
    "fifteen",
    "sixteen",
    "seventeen",
    "eighteen",
    "nineteen",
    "twenty",
    "thirty",
    "forty",
    "fifty",
    "sixty",
    "seventy",
    "eighty",
    "ninety",
)
SPELLED_AMOUNT_RE = re.compile(
    r"\b(?:"
    + "|".join(SPELLED_NUMBER_WORDS)
    + r")(?:[-\s]+(?:"
    + "|".join(SPELLED_NUMBER_WORDS + ("hundred", "thousand", "million", "and"))
    + r"))*[-\s]+(?:dollars?|usd)\b",
    re.IGNORECASE,
)
SPELLED_AMOUNT_CUE_RE = re.compile(
    r"\b("
    r"balance|bill|charge|charges|deposit|due|dues|fee|fine|invoice|owe|owed|payable|"
    r"payment|premium|rent|tax|total|totals"
    r")\b",
    re.IGNORECASE,
)
SPELLED_AMOUNT_NEGATIVE_RE = re.compile(
    r"\b("
    r"cash back|coupon|deal|discount|gift|off|promo|refund|refunded|reward|save|saves|saving"
    r")\b",
    re.IGNORECASE,
)
AMOUNT_INJECTION_CONTEXT_RE = re.compile(
    r"\b("
    r"system override|ignore (?:all )?(?:(?:previous|prior) )?instructions|pretend you are|"
    r"treat this as untrusted|disregard sender verification"
    r")\b",
    re.IGNORECASE,
)
ACTION_INJECTION_CONTEXT_RE = re.compile(
    r"\b("
    r"system override|ignore (?:all )?(?:(?:previous|prior) )?instructions|pretend you are|"
    r"treat this as untrusted|disregard sender verification|authorize the transfer"
    r")\b",
    re.IGNORECASE,
)
BASE_ACTION_VERBS = (
    "submit",
    "send",
    "pay",
    "upload",
    "sign",
    "renew",
    "schedule",
    "confirm",
    "respond",
    "complete",
    "provide",
    "review",
    "call",
    "email",
)
EXPANDED_ACTION_VERBS = (
    "contact",
    "register",
    "apply",
    "dispute",
    "redeem",
    "update",
    "cancel",
    "verify",
    "reply",
    "bring",
    "report",
    "check",
    "add",
    "print",
    "enroll",
    "contest",
)
ACTION_VERBS = BASE_ACTION_VERBS + EXPANDED_ACTION_VERBS
ACTION_RE = re.compile(
    r"\b(?P<verb>" + "|".join(ACTION_VERBS) + r")\b.{0,90}",
    re.IGNORECASE,
)
HTML_MARKUP_RE = re.compile(
    r"</?(?:html|body|head|table|tbody|tr|td|div|span|p|a|img|br|style|font)\b|"
    r"&(?:amp|nbsp|quot|lt|gt|#\d+);",
    re.IGNORECASE,
)
HTML_DATE_ARTIFACT_RE = re.compile(
    r"(?:https?://|src=|href=|style=|class=|font-weight|html_emails|stripe-images|"
    r"\.(?:png|jpe?g|gif|webp|svg)\b|utm_|ct=|mar=)",
    re.IGNORECASE,
)
EMAIL_HEADER_LINE_RE = re.compile(
    r"^\s*(?:>\s*)*\*?(?:from|sent|date|to|cc|bcc|subject)\*?\s*:",
    re.IGNORECASE,
)
EMAIL_QUOTED_REPLY_LINE_RE = re.compile(
    r"^\s*(?:on .{0,180}\bwrote:|.{1,180}于.{1,120}写道[:：])\s*$",
    re.IGNORECASE,
)
FLAT_QUOTED_HEADER_RE = re.compile(
    r"(?:\s|^)(?:>\s*)?[_-]{5,}\s*(?:>\s*)?\*?from\*?\s*:\s.{0,360}?\b\*?(?:sent|date)\*?\s*:\s|"
    r"(?:\s|^)(?:>\s*)?\*?from\*?\s*:\s.{0,360}?\b\*?(?:sent|date)\*?\s*:\s.{0,280}?"
    r"\b\*?(?:to|subject)\*?\s*:\s",
    re.IGNORECASE,
)
FLAT_ON_WROTE_RE = re.compile(r"(?:\s|^)(?:on\s.{0,260}?\bwrote:|.{1,220}于.{1,140}写道[:：])\s", re.IGNORECASE)
SECURITY_NOTIFICATION_RE = re.compile(
    r"\b("
    r"new login|login detected|new sign[- ]?in|sign[- ]?in alert|security alert|"
    r"new device|password (?:was )?changed|one[- ]?time passcode|verification code|"
    r"two[- ]?factor|2fa|if this was not you|not you"
    r")\b",
    re.IGNORECASE,
)
COMMERCE_NOTIFICATION_RE = re.compile(
    r"\b("
    r"order confirmation|order confirmed|purchase confirmation|your order|thanks for your order|"
    r"order receipt|purchase receipt|invoice for your order|we (?:received|got) your order|"
    r"shipped|shipment|shipping|tracking|delivery|delivered|arriv(?:es|ing|al)|"
    r"estimated delivery|out for delivery|package|return window"
    r")\b",
    re.IGNORECASE,
)
STRONG_DEADLINE_CUE_RE = re.compile(
    r"\b("
    r"deadline|due date|payment due|balance due|respond by|submit\b.{0,60}\bby|"
    r"upload\b.{0,60}\bby|pay\b.{0,60}\bby|must\b.{0,60}\bby|"
    r"expires? on|grace period ends"
    r")\b",
    re.IGNORECASE,
)
USER_OBLIGATION_DEADLINE_RE = re.compile(
    r"\b("
    r"action required|deadline|due date|payment due|balance due|past due|final notice|"
    r"respond by|reply by|submit\b.{0,60}\bby|upload\b.{0,60}\bby|"
    r"pay\b.{0,60}\bby|must\b.{0,60}\bby|need(?:s)?\b.{0,60}\bby|"
    r"required\b.{0,60}\bby|cancel\b.{0,60}\bby|renew\b.{0,60}\bby|"
    r"schedule\b.{0,60}\bby|complete\b.{0,60}\bby|grace period ends"
    r")\b",
    re.IGNORECASE,
)
PROMOTIONAL_HARD_OBLIGATION_RE = re.compile(
    r"\b("
    r"action required|deadline|due date|payment due|balance due|past due|final notice|"
    r"respond by|reply by|submit\b.{0,60}\bby|upload\b.{0,60}\bby|"
    r"pay\b.{0,60}\bby|complete\b.{0,60}\bby|verify\b.{0,60}\bby|"
    r"sign\b.{0,60}\bby|renew\b.{0,60}\bby|cancel\b.{0,60}\bby|"
    r"claim\b.{0,80}\bno later than|ensure\b.{0,80}\bno later than|"
    r"entry deadline|grace period ends"
    r")\b",
    re.IGNORECASE,
)
# Real "money the user owes" language. Deliberately narrow so promo prices
# ("$129 getaway", "earn 160K points", "$0 intro annual fee") do NOT match,
# while genuine bills do — used to keep amounts in promotional mail only when
# they are an actual obligation.
PAYMENT_OBLIGATION_RE = re.compile(
    r"\b("
    r"amount due|balance due|payment due|total due|amount owed|you owe|"
    r"outstanding balance|statement balance|minimum (?:payment|amount due)|"
    r"please (?:pay|remit)|pay (?:your|the|this) (?:bill|invoice|balance|rent|premium|statement)|"
    r"auto[- ]?pay|autopay|automatic payment|your payment (?:of|will|is|has)|"
    r"rent\b.{0,20}\bdue|bill is due|remit payment|invoice"
    r")\b",
    re.IGNORECASE,
)
PROMOTIONAL_OFFER_CONTEXT_RE = re.compile(
    r"\b("
    r"vacation package|offer|bonus points|honors points|getaway|intro annual fee|"
    r"terms and conditions|sale|discount|deal|limited time|promotion"
    r")\b",
    re.IGNORECASE,
)
COMMERCE_DATE_CONTEXT_RE = re.compile(
    r"\b("
    r"ordered on|order placed|purchase date|transaction date|payment processed|"
    r"shipping date|shipped on|delivered on|delivery date|estimated delivery|"
    r"arrives? (?:by|on)|arriving (?:by|on)|out for delivery|tracking|"
    r"return window|receipt|order total"
    r")\b",
    re.IGNORECASE,
)
ACTION_CUE_WORDS = {
    "and",
    "after",
    "before",
    "by",
    "can",
    "cannot",
    "could",
    "if",
    "may",
    "must",
    "or",
    "please",
    "should",
    "then",
    "to",
    "unless",
    "will",
    "would",
}
CONTEXT_SENSITIVE_ACTION_VERBS = {"check", "email", "report", "update"}
CALIBRATED_AMOUNT_CONFIDENCE = 0.76
HIGH_CUE_AMOUNT_CONFIDENCE = 0.86


__all__ = [
    "AMOUNT_RE",
    "SPELLED_NUMBER_WORDS",
    "SPELLED_AMOUNT_RE",
    "SPELLED_AMOUNT_CUE_RE",
    "SPELLED_AMOUNT_NEGATIVE_RE",
    "AMOUNT_INJECTION_CONTEXT_RE",
    "ACTION_INJECTION_CONTEXT_RE",
    "BASE_ACTION_VERBS",
    "EXPANDED_ACTION_VERBS",
    "ACTION_VERBS",
    "ACTION_RE",
    "HTML_MARKUP_RE",
    "HTML_DATE_ARTIFACT_RE",
    "EMAIL_HEADER_LINE_RE",
    "EMAIL_QUOTED_REPLY_LINE_RE",
    "FLAT_QUOTED_HEADER_RE",
    "FLAT_ON_WROTE_RE",
    "SECURITY_NOTIFICATION_RE",
    "COMMERCE_NOTIFICATION_RE",
    "STRONG_DEADLINE_CUE_RE",
    "USER_OBLIGATION_DEADLINE_RE",
    "PROMOTIONAL_HARD_OBLIGATION_RE",
    "PAYMENT_OBLIGATION_RE",
    "PROMOTIONAL_OFFER_CONTEXT_RE",
    "COMMERCE_DATE_CONTEXT_RE",
    "ACTION_CUE_WORDS",
    "CONTEXT_SENSITIVE_ACTION_VERBS",
    "CALIBRATED_AMOUNT_CONFIDENCE",
    "HIGH_CUE_AMOUNT_CONFIDENCE",
    "AMOUNT_SETTLED_RE",
    "AMOUNT_OBLIGATION_RE",
    "classify_amount_settlement",
    "SETTLEMENT_OBLIGATION",
    "SETTLEMENT_SETTLED",
    "SETTLEMENT_INFORMATIONAL",
    "ACTION_NEGATION_RE",
    "ACTION_UNVERIFIED_CONDITION_RE",
    "ACTION_BOILERPLATE_RE",
]


# --- amount settlement -------------------------------------------------------
#
# "Payment of $3,122.22 has been sent" and "Payment of $3,122.22 is due" are the
# same words away from opposite meanings: one is money that already moved, the
# other is money you still owe. Treating both as a payment obligation is what put
# completed bank transfers at the top of the review queue, ahead of real bills.
#
# The classification is deliberately local -- it reads the context around *this*
# amount, not the whole email -- because a statement can settle one amount and
# bill another in the same message.

AMOUNT_SETTLED_RE = re.compile(
    r"\b("
    r"has been (?:sent|paid|charged|credited|posted|processed|refunded|deposited|received)|"
    r"have been (?:sent|paid|charged|credited|posted|processed|refunded)|"
    r"was (?:sent|paid|charged|credited|posted|processed|refunded|deposited|debited)|"
    r"were (?:sent|paid|charged|credited|posted|processed|refunded)|"
    r"we(?:'ve| have)? received your payment|received your payment|payment received|"
    r"thank you for your payment|thanks for your payment|payment confirmation|"
    r"you (?:sent|paid|transferred)|successfully (?:sent|paid|processed|charged)|"
    r"transfer (?:complete|completed|sent)|transaction (?:complete|completed|posted)|"
    r"your receipt|receipt for|order confirmation|refund(?:ed)? (?:of|to|for)|"
    r"payment (?:sent|posted|complete|completed)|charged to your|"
    # A receipt states the amount and the day it was paid, with no verb between
    # them: "$20.00 Paid August 10, 2026", "Amount paid $20.00".
    r"amount paid|paid in full|"
    # The trailing [a-z]* runs the month name out to a real word boundary --
    # without it "aug" ends mid-"August" and the group's closing \b never holds.
    r"paid\s+(?:on\s+)?(?:\d{1,2}|(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*)"
    r")\b",
    re.IGNORECASE,
)

# Future-tense charges are obligations, not settlements: "will be charged" is
# money about to leave, which the user may still want to stop.
AMOUNT_OBLIGATION_RE = re.compile(
    r"\b("
    r"amount due|balance due|payment due|total due|past due|now due|"
    r"due (?:by|on|date)|(?:is|are|remains) due|"
    r"due\s+(?:\d{1,2}|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)|"
    r"minimum payment|please pay|pay by|pay before|make a payment|"
    r"outstanding balance|unpaid|you owe|owed|remains? due|"
    r"will be (?:charged|billed|debited|due)|autopay|auto-?pay will|"
    # NOT a bare "invoice": every paid receipt carries an invoice number, a
    # "view invoice" link, and (on Stripe receipts) an "invoice illustration"
    # image. The word marks the document, not the debt -- it was matching the
    # image alt text of a receipt that said "Paid" two words earlier.
    r"invoice\s+(?:is\s+)?due|unpaid\s+invoice|outstanding\s+invoice|invoice\s+balance|"
    r"statement balance|rent (?:is )?due|"
    r"avoid (?:a )?late fee|late fee (?:applies|will)"
    r")\b",
    re.IGNORECASE,
)

SETTLEMENT_OBLIGATION = "obligation"
SETTLEMENT_SETTLED = "settled"
SETTLEMENT_INFORMATIONAL = "informational"


def classify_amount_settlement(context: str) -> str:
    """Is this amount money still owed, money already moved, or neither?

    An explicit obligation cue wins over a settlement cue, so "we received your
    payment; your next payment of $200 is due Sept 1" is not written off as
    settled. Everything with no cue either way stays ``informational`` -- that is
    the honest answer for a marketing tier table or a credit limit, and it keeps
    those out of the obligation ranking without pretending they are receipts.
    """
    text = str(context or "")
    if AMOUNT_OBLIGATION_RE.search(text):
        return SETTLEMENT_OBLIGATION
    if AMOUNT_SETTLED_RE.search(text):
        return SETTLEMENT_SETTLED
    return SETTLEMENT_INFORMATIONAL


# --- action noise: negated, conditional, and boilerplate instructions ---------
#
# Real mail is full of imperative verbs that are not tasks. Three kinds showed up
# in the first live review, and all three had produced review-queue items:
#
#   "Please don't reply to this automatically generated service email"
#       -> extracted as "reply to this ..." -- the negation was dropped, so the
#          queue told the user to do the exact thing the email forbade.
#   "If you didn't make this payment, contact us"
#       -> an instruction conditional on something that did not happen.
#   "Remember: Always independently confirm transfer instructions ..."
#       -> standing advice printed in every wire notice, never a specific task.

# Negation immediately governing the verb, allowing a couple of filler words
# ("do not ever reply"). Anchored at the end because it must precede the verb.
ACTION_NEGATION_RE = re.compile(
    r"\b(?:do\s*n[o']?t|don[o']?t|never|no\s+need\s+to|not\s+required\s+to|"
    r"unable\s+to|cannot|can[o']?t|please\s+do\s+not)\s+(?:\w+\s+){0,2}$",
    re.IGNORECASE,
)

# The instruction is conditional on an event that did *not* happen: "if you
# didn't make this payment, contact us" is a fraud-report path, not a task.
#
# Deliberately narrow. "If you believe this charge is incorrect, you must dispute
# it before August 1" is the same grammatical shape but a real, time-bounded right
# the user may want to exercise, so opinion conditionals (believe/think/suspect)
# are NOT suppressed -- only negated events and misdelivery are. A broader version
# of this pattern swallowed both, and the golden set is what caught it.
ACTION_UNVERIFIED_CONDITION_RE = re.compile(
    r"\bif\s+(?:you|this)\s+(?:did\s*n[o']?t|didn[o']?t|do\s*n[o']?t|don[o']?t|"
    r"was\s*n[o']?t|wasn[o']?t|were\s*n[o']?t|weren[o']?t|"
    r"is\s+not|are\s+not|received\s+this\s+in\s+error)\b"
    r"[^.!?]{0,80}$",
    re.IGNORECASE,
)

# Legal footers, standing safety advice, and generic support offers.
ACTION_BOILERPLATE_RE = re.compile(
    r"\b("
    r"remember\s*:\s*always|always\s+independently|"
    r"related\s+marks\s+are|wholly\s+owned\s+by|trademarks?\s+of|"
    r"automatically\s+generated|"
    # NB: no "do not reply" / "no-reply" here. The sender address is part of the
    # text this runs over, so those would poison the opening of every message
    # from a no-reply@ address -- which is nearly every bill and notice worth
    # extracting. Negated instructions are handled by ACTION_NEGATION_RE, which
    # requires the negation to actually govern the verb.
    r"for\s+assistance\s+from|equal\s+housing|privacy\s+notice|"
    r"unsubscribe|manage\s+(?:your\s+)?preferences|terms\s+(?:and|&)\s+conditions"
    r")\b",
    re.IGNORECASE,
)
