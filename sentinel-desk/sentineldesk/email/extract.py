from __future__ import annotations

import re
from collections.abc import Iterable

from sentineldesk.extract import extract_deadlines, normalize_text

from .models import EmailFact, EmailMessage


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


def find_messages(messages: Iterable[EmailMessage], query: str, *, limit: int = 20) -> list[EmailMessage]:
    terms = [term.lower() for term in re.findall(r"[a-zA-Z0-9_$.-]+", query) if term.strip()]
    all_messages = list(messages)
    matched_threads: set[str] = set()
    scored: list[tuple[int, EmailMessage]] = []
    for message in all_messages:
        haystack = message.searchable_text.lower()
        score = sum(1 for term in terms if term in haystack)
        if not terms or score:
            matched_threads.add(message.thread_id)
            scored.append((score, message))
    if matched_threads:
        already = {message.message_id for _, message in scored}
        for message in all_messages:
            if message.thread_id in matched_threads and message.message_id not in already:
                scored.append((0, message))
    scored.sort(key=lambda item: (item[0], item[1].received_at), reverse=True)
    return [message for _, message in scored[:limit]]


def extract_email_facts(message: EmailMessage) -> list[EmailFact]:
    text = normalize_text(_remove_invisible_number_separators(message.searchable_text))
    facts: list[EmailFact] = []
    for deadline in extract_deadlines(text):
        facts.append(
            EmailFact(
                kind="deadline",
                value=str(deadline["date_text"]),
                source_id=message.source_id,
                source_type=message.source_type,
                trust_label=message.trust_label,
                evidence=str(deadline["context"]),
                confidence=float(deadline["confidence"]),
                received_at=message.received_at,
                metadata=_metadata(message),
            )
        )
    for match in AMOUNT_RE.finditer(text):
        amount = match.group(0)
        context = _context(text, match.start(), match.end())
        if not _amount_context_allowed(text, match.start(), match.end(), amount, context, message):
            continue
        facts.append(
            EmailFact(
                kind="amount",
                value=amount,
                source_id=message.source_id,
                source_type=message.source_type,
                trust_label=message.trust_label,
                evidence=context,
                confidence=0.78 if _near_risk_word(text, match.start()) else 0.52,
                received_at=message.received_at,
                metadata=_metadata(message),
            )
        )
    for match in SPELLED_AMOUNT_RE.finditer(text):
        context = _context(text, match.start(), match.end())
        if not _spelled_amount_context_allowed(context):
            continue
        facts.append(
            EmailFact(
                kind="amount",
                value=normalize_text(match.group(0)),
                source_id=message.source_id,
                source_type=message.source_type,
                trust_label=message.trust_label,
                evidence=context,
                confidence=0.78,
                received_at=message.received_at,
                metadata=_metadata(message),
            )
        )
    for match in ACTION_RE.finditer(text):
        verb = match.group("verb").lower()
        action = normalize_text(match.group(0))
        if not _action_context_allowed(text, match.start(), verb, action):
            continue
        facts.append(
            EmailFact(
                kind="action",
                value=action[:120],
                source_id=message.source_id,
                source_type=message.source_type,
                trust_label=message.trust_label,
                evidence=_context(text, match.start(), match.end()),
                confidence=0.68,
                received_at=message.received_at,
                metadata=_metadata(message),
            )
        )
    return facts


def _metadata(message: EmailMessage) -> dict[str, str]:
    return {
        "subject": message.subject,
        "sender": message.sender,
        "source_type": message.source_type,
        "trust_label": message.trust_label,
        "attachment_names": ", ".join(message.attachment_names),
    }


def _context(text: str, start: int, end: int, window: int = 90) -> str:
    return text[max(0, start - window) : min(len(text), end + window)]


def _remove_invisible_number_separators(text: str) -> str:
    return re.sub(r"[\u200b\u200c\u200d\ufeff]", "", text)


def _near_risk_word(text: str, start: int) -> bool:
    before = text[max(0, start - 80) : start].lower()
    return any(term in before for term in ["due", "balance", "rent", "invoice", "amount", "pay"])


def _amount_context_allowed(
    text: str,
    start: int,
    end: int,
    value: str,
    context: str,
    message: EmailMessage,
) -> bool:
    before = text[max(0, start - 110) : start].lower()
    after = text[end : min(len(text), end + 110)].lower()
    lowered_context = context.lower()
    if AMOUNT_INJECTION_CONTEXT_RE.search(lowered_context):
        return False
    if re.search(r"\breceived your payment of\s*$", before):
        return False
    if re.search(r"\bpayment of\s*$", before) and re.search(r"^\s*on\b.*\b(receipt|thank you)\b", after):
        return False
    if (
        re.search(r"\bbalance transfer fee\b", after)
        and re.search(r"\b(limited time|intro apr|offer terms)\b", lowered_context)
    ):
        return False
    if "low balance alert" in lowered_context and re.search(r"\bfallen below\s*$", before):
        return False
    if re.search(r"\bfine balance:\s*$", before) and _amount_is_zero(value):
        return False
    if re.search(r"\b(?:amount billed|plan paid):\s*$", before):
        return False
    if _semantic_amount_noise(message, lowered_context):
        return False
    return not _low_confidence_amount_noise(before, lowered_context)


def _amount_is_zero(value: str) -> bool:
    numeric = re.sub(r"[^\d.]", "", value.replace(",", ""))
    if not numeric:
        return False
    try:
        return float(numeric) == 0.0
    except ValueError:
        return False


def _low_confidence_amount_noise(before: str, context: str) -> bool:
    if re.search(r"\b(?:refund|refunded|reimbursement|reimbursed)\b", context):
        return True
    if re.search(r"\bcredit of\s*$", before) and re.search(
        r"\b(applied|reflect|no payment is required)\b", context
    ):
        return True
    if re.search(r"\btotal was\s*$", before) and re.search(
        r"\b(receipt|thanks for your order|order details)\b", context
    ):
        return True
    if re.search(r"\b(new patient special|bonus|unlock all articles)\b", context):
        return True
    if re.search(r"\brooms from\s*$", before) or "weekend escape" in context:
        return True
    if re.search(r"\bupgrade to (?:get|premium)\b", context):
        return True
    return False


def _semantic_amount_noise(message: EmailMessage, context: str) -> bool:
    if (
        re.search(r"\bcredit limit\b", context)
        and re.search(r"\b(?:has been )?increased\b|\beffective immediately\b", context)
        and re.search(r"\bno action is needed\b|\bcongratulations\b", context)
    ):
        return True
    if _looks_like_phishing_payment_message(message, context):
        return True
    return False


def _looks_like_phishing_payment_message(message: EmailMessage, context: str) -> bool:
    if not _sender_identity_mismatch(message.sender):
        return False
    return bool(
        re.search(r"\bpay\b|\bprocessing fee\b", context)
        and re.search(r"\bsecure link\b|\bterminated\b|\bimmediate action\b", context)
    )


def _sender_identity_mismatch(sender: str) -> bool:
    match = re.search(r"\b(?P<local>[A-Za-z0-9._%+-]+)@(?P<domain>[A-Za-z0-9.-]+)\b", sender.lower())
    if not match:
        return False
    local = match.group("local")
    domain = match.group("domain")
    return "uscis" in local and "uscis" not in domain


def _spelled_amount_context_allowed(context: str) -> bool:
    if SPELLED_AMOUNT_NEGATIVE_RE.search(context):
        return False
    return bool(SPELLED_AMOUNT_CUE_RE.search(context))


def _action_context_allowed(text: str, start: int, verb: str, action: str) -> bool:
    lowered = action.lower()
    if _action_noise_context(text, start, verb, lowered):
        return False
    if (
        verb == "contact"
        and "support" in lowered
        and "if you did not" in text[max(0, start - 90) : start].lower()
    ):
        return False
    if verb == "reply" and _looks_like_email_local_part(text, start, verb):
        return False
    if verb == "apply" and re.search(
        r"\b(?:charges|fees|rates|conditions|terms) may\s+$",
        text[max(0, start - 40) : start].lower(),
    ):
        return False
    if verb == "apply" and _previous_word(text, start) in {
        "charges",
        "conditions",
        "fees",
        "rates",
        "terms",
    }:
        return False
    if verb == "update" and re.search(r"\bupdate from (?:your )?device'?s app store\b", lowered):
        return False
    if verb not in CONTEXT_SENSITIVE_ACTION_VERBS:
        return True
    if _starts_action_clause(text, start):
        return True
    previous = _previous_word(text, start)
    return previous in ACTION_CUE_WORDS


def _action_noise_context(text: str, start: int, verb: str, action: str) -> bool:
    context = _context(text, start, start + len(action)).lower()
    if ACTION_INJECTION_CONTEXT_RE.search(context):
        return True
    if _looks_like_link_or_html_artifact(action, context):
        return True
    if re.search(r"\bsecure link\b", context) and re.search(
        r"\bprocessing fee\b|\bterminated\b", context
    ):
        return True
    if verb == "schedule" and (
        _previous_word(text, start) in {"billing", "installment", "lease", "payment", "premium", "rent"}
        or re.search(r"\b(?:lease|payment|premium|rent)\s+schedule\b", action)
    ):
        return True
    if re.search(r"\bpay no attention\b", action):
        return True
    if re.search(r"\bsign in to see who\b", action) and re.search(
        r"\b(connection requests|notifications|viewing your profile)\b", context
    ):
        return True
    if re.search(r"\bcomplete\b.*\bsurvey\b", action) and re.search(
        r"\b(help us improve|support experience|how did we do)\b", context
    ):
        return True
    if verb == "review" and re.search(r"\bpull request\b|\bmigration script\b|\bcodeforge\b", context):
        return True
    if verb == "submit" and re.search(r"\b(all-hands|questions for leadership|leadership through the form)\b", context):
        return True
    return False


def _looks_like_link_or_html_artifact(action: str, context: str) -> bool:
    if re.search(r"(?:https?://|mailto:|href=|&(?:amp;)?[a-z0-9_]+=|%recipient|utm_|ct=|mar=)", action):
        return True
    if re.match(r"^email(?:[\"'>]|&|%|=|/)", action):
        return True
    if re.search(r"(?:https?://|mailto:|href=|%recipient|utm_|ct=|mar=)", context) and re.search(
        r"(?:^|[^a-z])email(?:[\"'>]|&|%|=|/)",
        action,
    ):
        return True
    return False


def _starts_action_clause(text: str, start: int) -> bool:
    before = text[:start].rstrip(" \t\r")
    if not before:
        return True
    return before[-1] in ".!?:;,\n"


def _previous_word(text: str, start: int) -> str:
    match = re.search(r"([A-Za-z]+)$", text[:start].rstrip())
    return match.group(1).lower() if match else ""


def _looks_like_email_local_part(text: str, start: int, verb: str) -> bool:
    after = start + len(verb)
    previous = text[start - 1] if start > 0 else ""
    next_char = text[after] if after < len(text) else ""
    return previous in "-_." or next_char in "@_.-"
