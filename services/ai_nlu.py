"""Local NLU facade for the ERP assistant (Stage 3).

This module centralises the three Stage-3 concerns that the rest of the codebase
already implements in pieces:

* hybrid intent classification (deterministic interrogative/action guards +
  keyword/semantic scoring),
* entity extraction (relative dates, currencies, SKUs, phones, invoice/cheque
  numbers, multi-word names),
* bounded, expiring follow-up context with explicit reset.

Everything here is local-first and tenant-agnostic at the NLU layer; tenant and
permission enforcement happens downstream in ``services.ai_questions`` and
``routes.ai``.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from services.ai_normalize import normalize
from services.ai_planner import extract_entities as _planner_extract
from services.ai_questions import is_question as _is_question


# ---------------------------------------------------------------------------
# Intent classification
# ---------------------------------------------------------------------------

_QUESTION_WORDS = (
    "كم",
    "عدد",
    "إجمالي",
    "مجموع",
    "كيف",
    "ماذا",
    "ما هو",
    "هل ",
    "أفضل",
    "أي",
    "؟",
    "?",
    "how many",
    "what is",
    "total",
    "count",
    "status",
    "top",
    "average",
    "متوسط",
)

_ACTION_WORDS = (
    "أنشئ",
    "انشئ",
    "أضف",
    "اضف",
    "سجل",
    "أصدر",
    "اصدر",
    "احذف",
    "ألغ",
    "الغ",
    "عدل",
    "أرسل",
    "ارسل",
    "create",
    "add",
    "delete",
    "update",
    "post",
    "issue",
)

_READ_METRICS = {
    "sales": ("مبيعات", "sales", "invoice", "فاتورة"),
    "customers": ("عملاء", "customer", "زبون"),
    "products": ("منتج", "product", "صنف"),
    "inventory": ("مخزون", "stock", "inventory"),
    "expenses": ("مصروف", "expense"),
    "cheques": ("شيك", "cheque", "check"),
    "fiscal": (" فترة", "fiscal", "فترة مالية"),
    "receivables": ("ذمم", "receivable", "مستحق"),
    "vat": ("ضريب", "vat", "tax"),
    "cashflow": ("تدفق", "cash flow", "نقد"),
}


def classify_intent(message: str) -> tuple[str, float]:
    """Return (intent, confidence) for *message*.

    Intents are one of: ``question_read``, ``action_write``, ``guide``, ``unknown``.
    """
    text = (message or "").strip()
    if not text:
        return "unknown", 0.0
    norm = normalize(text)
    lowered = text.lower()
    is_q = _is_question(text) or any(
        w in text or w in norm or w in lowered for w in _QUESTION_WORDS
    )
    has_action = any(w in text or w in norm or w in lowered for w in _ACTION_WORDS)
    if is_q and not has_action:
        return "question_read", 0.9
    if has_action and not is_q:
        return "action_write", 0.9
    if has_action and is_q:
        # "how to create ..." style
        if any(w in lowered for w in ("how to", "كيف", "طريقة", "خطوات")):
            return "guide", 0.85
        return "action_write", 0.7
    return "unknown", 0.4


def detect_metric(message: str) -> str | None:
    norm = normalize(message or "")
    low = (message or "").lower()
    for metric, words in _READ_METRICS.items():
        if any(w in (message or "") or w in norm or w in low for w in words):
            return metric
    return None


# ---------------------------------------------------------------------------
# Entity extraction (enhanced)
# ---------------------------------------------------------------------------


def extract_entities(message: str) -> dict[str, Any]:
    base = _planner_extract(message or "")
    # normalise keys
    out = dict(base)
    out.setdefault("relative_dates", [])
    out.setdefault("currencies", [])
    out.setdefault("invoice_numbers", [])
    out.setdefault("cheque_numbers", [])
    # relative date ranges as concrete start/end when detectable
    out["date_ranges"] = _resolve_date_ranges(out.get("relative_dates", []))
    return out


def _resolve_date_ranges(relative: list[str]) -> list[dict[str, str]]:
    from datetime import date, timedelta

    today = date.today()
    tomorrow = today + timedelta(days=1)
    ranges = {
        "today": (today, tomorrow),
        "yesterday": (today - timedelta(days=1), today),
        "this_week": (today - timedelta(days=today.weekday()), tomorrow),
        "last_week": (
            today - timedelta(days=today.weekday() + 7),
            today - timedelta(days=today.weekday()),
        ),
        "this_month": (today.replace(day=1), tomorrow),
        "last_month": (
            (today.replace(day=1) - timedelta(days=1)).replace(day=1),
            today.replace(day=1),
        ),
        "this_year": (date(today.year, 1, 1), tomorrow),
        "last_year": (date(today.year - 1, 1, 1), date(today.year, 1, 1)),
    }
    result = []
    for key in relative or []:
        if key in ranges:
            start, end = ranges[key]
            result.append(
                {"key": key, "start": start.isoformat(), "end": end.isoformat()}
            )
    return result


# ---------------------------------------------------------------------------
# Follow-up context
# ---------------------------------------------------------------------------


@dataclass
class FollowUpContext:
    last_topic: str | None = None
    last_time_range: str | None = None
    last_entity_type: str | None = None
    last_entity_id: int | None = None
    expires_at: float = field(default_factory=lambda: time.time() + 600.0)
    ttl_seconds: float = 600.0

    def is_expired(self, now: float | None = None) -> bool:
        now = time.time() if now is None else now
        return now >= self.expires_at

    def touch(self, now: float | None = None) -> None:
        now = time.time() if now is None else now
        self.expires_at = now + self.ttl_seconds

    def reset(self) -> None:
        self.last_topic = None
        self.last_time_range = None
        self.last_entity_type = None
        self.last_entity_id = None

    def update(
        self, *, topic=None, time_range=None, entity_type=None, entity_id=None
    ) -> None:
        if topic is not None:
            self.last_topic = topic
        if time_range is not None:
            self.last_time_range = time_range
        if entity_type is not None:
            self.last_entity_type = entity_type
        if entity_id is not None:
            self.last_entity_id = entity_id
        self.touch()

    def resolve_follow_up(self, message: str) -> dict[str, Any]:
        if self.is_expired():
            self.reset()
            return {"resolved": False, "reason": "expired"}
        text = (message or "").strip().lower()
        reset_words = {"مسح", "clear", "reset", "إلغاء"}
        if text in reset_words:
            self.reset()
            return {"resolved": False, "reason": "reset"}
        result = {
            "resolved": True,
            "topic": self.last_topic,
            "time_range": self.last_time_range,
            "entity_type": self.last_entity_type,
            "entity_id": self.last_entity_id,
        }
        # inherit time range if a new relative period not explicitly given
        return result


_RESET_WORDS = {"مسح", "clear", "reset", "إلغاء"}


def is_reset_command(message: str) -> bool:
    return (message or "").strip().lower() in _RESET_WORDS
