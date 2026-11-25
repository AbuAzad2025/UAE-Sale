"""Typed input for the assistant's durable message queue."""

import re
import unicodedata
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from bot_core.security import Actor

_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
_LETTERS = str.maketrans("أإآٱى", "ااااي")
_NOISE = re.compile(r"[\u064b-\u065f\u0670\u0640\u200b-\u200f\u202a-\u202e\u2066-\u2069\ufeff]")


def normalize(text: str) -> str:
    """Normalize script and whitespace while preserving part numbers and decimals."""
    text = unicodedata.normalize("NFKC", text).translate(_DIGITS).translate(_LETTERS)
    return " ".join(_NOISE.sub("", text).casefold().split())


@dataclass(frozen=True, slots=True)
class MessageEvent:
    id: str
    actor: Actor
    raw_input: str
    normalized: str
    command: dict[str, Any] | None = None

    @classmethod
    def receive(
        cls, key: str | None, text: object, actor: Actor, *, command: dict[str, Any] | None = None,
    ) -> "MessageEvent":
        try:
            identifier = UUID(key or "")
        except ValueError as error:
            raise ValueError("Idempotency-Key must be a UUID v4.") from error
        if identifier.version != 4:
            raise ValueError("Idempotency-Key must be a UUID v4.")
        if not isinstance(text, str) or not 0 < len(text) <= 4000:
            raise ValueError("Message must contain 1–4000 characters.")
        normalized = normalize(text)
        if not normalized:
            raise ValueError("Message must contain visible text.")
        return cls(str(identifier), actor, text, normalized, command)
