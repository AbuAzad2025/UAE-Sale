"""Deterministic routing for explicit ERP commands and missing references."""

import re
from dataclasses import dataclass

from bot_core.agent import ToolCall
from bot_core.dialogue import Dialogue
from bot_core.gateway import MessageEvent, normalize
from bot_core.neural_nlu import Prediction, feature, tokenize
from services.ai_questions import is_sales_question

_PATTERNS = (
    ("get_customer_balance", re.compile(r"^(?:رصيد(?: العميل)?|customer balance)(?=$|[ :])")),
    ("check_stock", re.compile(r"^(?:مخزون(?: الصنف| المنتج)?|(?:check )?stock)(?=$|[ :])")),
    ("get_invoice_status", re.compile(
        r"^(?:حالة فاتورة|invoice status|(?:look up|check|show) (?:the )?(?:payment|status) (?:for|of) invoice)(?=$|[ :])"
    )),
    ("draft_customer", re.compile(r"^(?:اضف عميل|انشئ عميل|add customer)(?=$|[ :])")),
)
_RESET = {"cancel", "reset", "الغاء", "الغ", "اعادة ضبط"}
_PURCHASE = re.compile(
    r"^(?:(?:اريد |بدي )?(?:انشئ |انشاء |جهز )?(?:مسودة )?امر شراء|"
    r"(?:(?:start|draft|create)(?: a)? )?purchase order)[؟?]?$"
)
_NOTE = re.compile(r"^(?:ملاحظة عميل|add customer note)\s+#([0-9]{1,10})$")
_TRANSFER = {"نقل مخزون", "stock transfer"}
_TRANSFER_FIELDS = ("source", "target", "sku", "quantity")
_TRANSFER_PROMPTS = (
    "اكتب رمز المستودع المصدر.", "اكتب رمز المستودع الوجهة.",
    "اكتب رمز الصنف المراد نقله.", "اكتب الكمية المراد نقلها.",
)
_CLARIFICATION = re.compile(
    r"^(?:لم افهم|غير واضح|ماذا تقصد|ما المطلوب|وضح|مساعده|مش متاكد|لست متاكدا|help|what do you mean|"
    r"what should i (?:enter|send)|not sure|i don.t understand|please clarify)(?:$|[ .!?؟])"
)
_QUOTE = {"عرض سعر", "عرض اسعار", "عرض أسعار", "draft quote", "quote"}
_PROMPTS = {
    "get_customer_balance": "أرسل اسم العميل أو رقمه مسبوقًا بـ #.",
    "check_stock": "أرسل اسم الصنف أو رمزه.",
    "get_invoice_status": "أرسل رقم الفاتورة.",
    "draft_customer": "أرسل اسم العميل الذي تريد إضافته.",
}


@dataclass(frozen=True, slots=True)
class Decision:
    tool: str | None
    call: ToolCall | None
    prompt: str
    reset: bool = False
    confidence: float = 1.0
    direct_mutation: bool = False
    dialogue: Dialogue | None = None


def _decision(tool: str, value: str) -> Decision:
    field = "name" if tool == "draft_customer" else "reference"
    return Decision(tool, ToolCall(tool, {field: value}) if value else None, _PROMPTS[tool])


def _transfer_turn(text: str, prior: Dialogue | None) -> Decision:
    values = dict(prior.slots) if prior and prior.topic == "stock_transfer" else {}
    parts = [part.strip() for part in text.split("|")] if text.strip() else []
    if len(parts) == len(_TRANSFER_FIELDS) and all(parts):
        return Decision("stock_transfer", ToolCall("stock_transfer", dict(zip(_TRANSFER_FIELDS, parts))), "")
    missing = [field for field in _TRANSFER_FIELDS if field not in values]
    if parts and len(parts) <= len(missing) and all(0 < len(part) <= 50 for part in parts):
        values.update(zip(missing, parts))
        if len(values) == len(_TRANSFER_FIELDS):
            return Decision("stock_transfer", ToolCall("stock_transfer", values), "")
    return Decision("stock_transfer", None, _TRANSFER_PROMPTS[len(values)], dialogue=Dialogue("stock_transfer", values))


def decide(event: MessageEvent, prior: Dialogue | None) -> Decision:
    if event.normalized in _RESET:
        return Decision(None, None, "ألغيت خطوة المحادثة الحالية.", reset=True)
    note_parts = re.split(r"[:：]", event.raw_input, maxsplit=1)
    note = _NOTE.fullmatch(normalize(note_parts[0]))
    if note and len(note_parts) == 2:
        return Decision(
            "add_customer_note",
            ToolCall("add_customer_note", {"customer_id": int(note[1]), "note": note_parts[1].strip()}),
            "", direct_mutation=True,
        )
    if normalize(note_parts[0]) in _TRANSFER:
        return _transfer_turn(note_parts[1] if len(note_parts) == 2 else "", prior)
    if normalize(note_parts[0]) in _QUOTE:
        prompt = "أرسل «عرض سعر: العميل | رمز الصنف | الكمية | رمز المستودع | العملة»."
        details = note_parts[1].strip() if len(note_parts) == 2 else ""
        call = ToolCall("draft_quote", {"details": details}) if details else None
        return Decision("draft_quote", call, prompt)
    if _PURCHASE.fullmatch(event.normalized):
        return Decision("purchase_order", ToolCall("purchase_order", {}), "")
    # Match the normalized command while keeping the caller's spelling of its argument.
    for tool, pattern in _PATTERNS:
        match = pattern.match(event.normalized)
        if match:
            normalized_argument = event.normalized[match.end():].lstrip(" :")
            words = normalized_argument.split()
            raw_words = event.raw_input.strip().split()
            head, colon, tail = event.raw_input.partition(":")
            if colon and normalize(head) == match.group():
                value = tail.strip()
            else:
                value = " ".join(raw_words[-len(words):]).lstrip(" :") if words else ""
            if value and normalize(value) != normalized_argument:
                value = normalized_argument
            return _decision(tool, value)
    if is_sales_question(event.raw_input, "sales" if prior and prior.topic == "sales_report" else None):
        return Decision("sales_report", ToolCall("sales_report", {"question": event.raw_input}), "")
    if prior and prior.topic in {"purchase_order", "stock_transfer", "confirmation"} and (
        _CLARIFICATION.match(event.normalized) or event.normalized.endswith(("?", "؟"))
    ):
        if prior.topic == "purchase_order":
            from services.assistant_purchases import STEPS

            prompt = STEPS[prior.slots["step"]]
        elif prior.topic == "stock_transfer":
            prompt = _TRANSFER_PROMPTS[len(prior.slots)]
        else:
            prompt = "راجع المعاينة المعلّقة واستخدم زر التأكيد لإكمالها، أو اكتب «إلغاء»."
        return Decision(prior.topic if prior.topic != "confirmation" else None, None, prompt, dialogue=prior)
    if prior and prior.topic == "purchase_order":
        return Decision("purchase_order", ToolCall("purchase_order", {"answer": event.raw_input.strip()}), "")
    if prior and prior.topic == "stock_transfer":
        return _transfer_turn(event.raw_input, prior)
    if prior and prior.topic in _PROMPTS:
        return _decision(prior.topic, event.raw_input.strip())
    return Decision(None, None, "حدّد المطلوب: رصيد عميل، مخزون صنف، حالة فاتورة، إضافة عميل، أو أمر شراء.", confidence=0.0)


def from_prediction(
    prediction: Prediction, threshold: float, fallback: Decision, *, message: str = "",
) -> Decision:
    tool = prediction.intent
    if prediction.confidence < threshold:
        return Decision(None, None, fallback.prompt, confidence=prediction.confidence)
    if tool == "purchase_order":
        return Decision(tool, ToolCall(tool, {}), "", confidence=prediction.confidence)
    if tool == "sales_report" and message:
        return Decision(tool, ToolCall(tool, {"question": message}), "", confidence=prediction.confidence)
    if tool == "stock_transfer":
        return Decision(None, None, "أرسل «نقل مخزون: المصدر | الوجهة | رمز الصنف | الكمية».",
                        confidence=prediction.confidence)
    if tool == "draft_quote":
        return Decision(None, None, "أرسل «عرض سعر: العميل | الصنف | الكمية | المستودع | العملة».",
                        confidence=prediction.confidence)
    if tool not in _PROMPTS:
        return Decision(None, None, fallback.prompt, confidence=prediction.confidence)
    # A classifier may suggest a draft, but the actor must identify the record in the next turn.
    if tool == "draft_customer":
        return Decision(tool, None, _PROMPTS[tool], confidence=prediction.confidence)
    kind = "customer" if tool == "get_customer_balance" else "reference"
    values = prediction.entities.get(kind, [])
    code_type = {"get_invoice_status": "<invoice-code>", "check_stock": "<stock-code>"}.get(tool)
    if code_type and message:
        explicit_codes = list(dict.fromkeys(token for token in tokenize(message) if feature(token) == code_type))
        if explicit_codes:
            values = explicit_codes
    call = ToolCall(tool, {"reference": values[0]}) if len(values) == 1 else None
    return Decision(tool, call, _PROMPTS[tool], confidence=prediction.confidence)
