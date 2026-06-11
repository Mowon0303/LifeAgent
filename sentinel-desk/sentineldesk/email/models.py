from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class EmailMessage:
    message_id: str
    thread_id: str
    sender: str
    subject: str
    received_at: str
    body_text: str
    attachment_texts: tuple[str, ...] = ()
    attachment_names: tuple[str, ...] = ()
    source_type: str = "email"
    trust_label: str = "email_unverified"

    @property
    def source_id(self) -> str:
        return f"{self.source_type}:{self.message_id}"

    @property
    def searchable_text(self) -> str:
        parts = [self.sender, self.subject, self.body_text, *self.attachment_texts]
        return "\n".join(part for part in parts if part)


@dataclass(frozen=True)
class EmailThread:
    thread_id: str
    messages: tuple[EmailMessage, ...] = ()

    @property
    def latest_message(self) -> EmailMessage | None:
        if not self.messages:
            return None
        return sorted(self.messages, key=lambda message: message.received_at)[-1]


@dataclass(frozen=True)
class EmailFact:
    kind: str
    value: str
    source_id: str
    source_type: str = "email"
    trust_label: str = "email_unverified"
    evidence: str = ""
    confidence: float = 0.0
    received_at: str = ""
    metadata: dict[str, str] = field(default_factory=dict)

    def to_citation(self) -> dict[str, str]:
        return {
            "source_id": self.source_id,
            "source_type": self.source_type,
            "trust_label": self.trust_label,
            "evidence": self.evidence,
            "received_at": self.received_at,
        }
