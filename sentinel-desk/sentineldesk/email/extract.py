from __future__ import annotations

import re
from collections.abc import Callable, Iterable

from sentineldesk.extract import extract_deadlines, normalize_text, visible_text

from .models import EmailFact, EmailMessage


from .extract_patterns import *  # noqa: F401,F403 -- shared extraction patterns/constants


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


DeadlineGate = Callable[[EmailMessage, dict[str, object]], bool]


def extract_email_facts(message: EmailMessage, *, deadline_gate: DeadlineGate | None = None) -> list[EmailFact]:
    text = _message_fact_text(message)
    facts: list[EmailFact] = []
    for deadline in extract_deadlines(text):
        if not _deadline_context_allowed_for_message(message, deadline):
            continue
        if deadline_gate is not None and not deadline_gate(message, deadline):
            continue
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
                confidence=_amount_confidence(text, match.start()),
                received_at=message.received_at,
                metadata=_metadata(message),
            )
        )
    for match in SPELLED_AMOUNT_RE.finditer(text):
        context = _context(text, match.start(), match.end())
        if not _spelled_amount_context_allowed(context):
            continue
        if _promotional_message_without_payment_obligation(message, context):
            continue
        facts.append(
            EmailFact(
                kind="amount",
                value=normalize_text(match.group(0)),
                source_id=message.source_id,
                source_type=message.source_type,
                trust_label=message.trust_label,
                evidence=context,
                confidence=HIGH_CUE_AMOUNT_CONFIDENCE,
                received_at=message.received_at,
                metadata=_metadata(message),
            )
        )
    suppress_promo_actions = _promotional_message_without_user_action(message)
    for match in ACTION_RE.finditer(text):
        if suppress_promo_actions:
            break
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


def _message_fact_text(message: EmailMessage) -> str:
    body_text = _fact_body_text(message.body_text)
    attachment_texts = [_visible_message_text(str(item)) for item in message.attachment_texts]
    return normalize_text(
        _remove_invisible_number_separators(
            "\n".join(part for part in [message.sender, message.subject, body_text, *attachment_texts] if part)
        )
    )


def _subject_body_text(message: EmailMessage) -> str:
    return normalize_text(
        _remove_invisible_number_separators(
            "\n".join(part for part in [message.subject, _fact_body_text(message.body_text)] if part)
        )
    )


def _fact_body_text(raw: str) -> str:
    return _strip_quoted_reply_text(_visible_message_text(raw))


def _visible_message_text(raw: str) -> str:
    text = str(raw or "")
    if not text:
        return ""
    if not HTML_MARKUP_RE.search(text):
        return text
    _, parsed = visible_text(text)
    return parsed


def _strip_quoted_reply_text(text: str) -> str:
    line_cleaned = _strip_quoted_reply_lines(str(text or ""))
    return _strip_flat_quoted_headers(line_cleaned).strip()


def _strip_quoted_reply_lines(text: str) -> str:
    lines = text.splitlines()
    if len(lines) <= 1:
        return text
    kept: list[str] = []
    for index, line in enumerate(lines):
        if EMAIL_QUOTED_REPLY_LINE_RE.match(line):
            break
        if _quoted_header_block_starts(lines, index):
            break
        kept.append(line)
    return "\n".join(kept)


def _quoted_header_block_starts(lines: list[str], index: int) -> bool:
    line = lines[index]
    if not EMAIL_HEADER_LINE_RE.match(line):
        return False
    window = lines[index : min(len(lines), index + 5)]
    header_count = sum(1 for item in window if EMAIL_HEADER_LINE_RE.match(item))
    if header_count < 2:
        return False
    if index == 0:
        return True
    previous = "\n".join(lines[max(0, index - 2) : index]).strip()
    return bool(not previous or re.search(r"(?:^|\n)\s*(?:>\s*)*(?:[_=-]{5,}|-{5,})\s*$", previous))


def _strip_flat_quoted_headers(text: str) -> str:
    cut = len(text)
    for pattern in (FLAT_ON_WROTE_RE, FLAT_QUOTED_HEADER_RE):
        match = pattern.search(text)
        if match:
            cut = min(cut, match.start())
    return text[:cut]


def _deadline_context_allowed_for_message(message: EmailMessage, deadline: dict[str, object]) -> bool:
    context = str(deadline.get("context") or "")
    if _deadline_looks_like_html_artifact(context):
        return False
    if _security_notification_without_deadline(message):
        return False
    if _commerce_notification_without_user_deadline(message, context):
        return False
    if _promotional_message_without_user_deadline(message, deadline):
        return False
    return True


def _promotional_message_without_user_deadline(message: EmailMessage, deadline: dict[str, object]) -> bool:
    """Veto deadlines from mail Gmail itself routed outside Primary (or
    list/bulk mail) unless the candidate date carries an explicit user
    obligation. A creator post, newsletter, update, or marketing blast that
    merely *mentions* a date is not a deadline."""
    if message.gmail_category not in {"promotions", "social", "forums", "updates"} and not message.is_bulk:
        return False
    context = normalize_text(" ".join([message.subject, str(deadline.get("context") or "")]))
    if (
        message.gmail_category == "promotions"
        and PROMOTIONAL_OFFER_CONTEXT_RE.search(context)
        and not PROMOTIONAL_HARD_OBLIGATION_RE.search(context)
    ):
        return True
    return not USER_OBLIGATION_DEADLINE_RE.search(context)


def _promotional_message_without_payment_obligation(message: EmailMessage, context: str) -> bool:
    """Drop dollar amounts from Promotions/Social/Forums mail unless the text
    around them is a real bill. A "$129 getaway", "50,000 points", or "$0 intro
    annual fee" is a marketing figure, not money the user owes — symmetric with
    the deadline gate so promo mail stops minting fake obligations."""
    if message.gmail_category not in {"promotions", "social", "forums"}:
        return False
    combined = normalize_text(" ".join([message.subject, context]))
    return not PAYMENT_OBLIGATION_RE.search(combined)


def _promotional_message_without_user_action(message: EmailMessage) -> bool:
    """Drop imperative-verb "actions" from Promotions/Social/Forums mail unless
    the message states a real obligation. "Redeem your points", "shop now",
    "enjoy the offer" are calls to buy, not tasks the user owes."""
    if message.gmail_category not in {"promotions", "social", "forums"}:
        return False
    subject_body = normalize_text(_subject_body_text(message))
    return not (USER_OBLIGATION_DEADLINE_RE.search(subject_body) or PAYMENT_OBLIGATION_RE.search(subject_body))


def _deadline_looks_like_html_artifact(context: str) -> bool:
    return bool(HTML_DATE_ARTIFACT_RE.search(context))


def _security_notification_without_deadline(message: EmailMessage) -> bool:
    subject_body = _subject_body_text(message)
    if not SECURITY_NOTIFICATION_RE.search(subject_body):
        return False
    return not STRONG_DEADLINE_CUE_RE.search(subject_body)


def _commerce_notification_without_user_deadline(message: EmailMessage, context: str) -> bool:
    subject_body = _subject_body_text(message)
    combined = normalize_text(" ".join([subject_body, context]))
    if not COMMERCE_NOTIFICATION_RE.search(combined):
        return False
    if USER_OBLIGATION_DEADLINE_RE.search(combined):
        return False
    return bool(COMMERCE_DATE_CONTEXT_RE.search(combined) or COMMERCE_NOTIFICATION_RE.search(subject_body))


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


def _amount_confidence(text: str, start: int) -> float:
    return HIGH_CUE_AMOUNT_CONFIDENCE if _near_risk_word(text, start) else CALIBRATED_AMOUNT_CONFIDENCE


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
    if _promotional_message_without_payment_obligation(message, context):
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
