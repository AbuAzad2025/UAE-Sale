"""Rank a short read against local examples and the authenticated focus."""

import re
from dataclasses import dataclass

from bot_core.context import EntityReference, InteractionContext
from bot_core.gateway import normalize
from bot_core.neural_nlu.retrieval import scored_matches

_FOCUS = {
    "get_customer_balance": "customer",
    "get_latest_customer_invoice": "invoice",
    "get_invoice_status": "invoice",
    "check_invoice_stock": "product",
    "get_invoice_customer_balance": "customer",
    "check_stock": "product",
}
_EXAMPLES = {
    "get_latest_customer_invoice": (
        "ما آخر فاتورة له", "ما هي أحدث فاتورة لهذا العميل", "شو آخر فاتورة للعميل", "ورجيني آخر فاتورة إله",
        "آخر فاتورة للزبون", "آخر فاتورة له", "آخر فاتوره إلها", "متى كانت آخر فاتورة له",
        "show their latest invoice", "what is this customer's last invoice",
    ),
    "get_invoice_status": (
        "كم بقي عليها", "كم باقي على الفاتورة", "شو ضل عليها", "هل هي مدفوعة", "هل تسددت",
        "كم المستحق عليها", "كم باقي منها", "كم بقي", "قديش ضل عليها", "هل الفاتورة مسددة", "شو حالة دفعها",
        "how much is left on it", "is it paid", "outstanding balance on this invoice",
    ),
    "get_customer_balance": (
        "كم رصيده", "وكم رصيده", "شو رصيدها", "كم بذمته", "قديش عليه", "كم بقي عليه",
        "كم بقي", "قيمة مديونيته", "what is their balance", "how much does this customer owe",
    ),
    "get_invoice_customer_balance": (
        "كم رصيد عميلها", "ما رصيد العميل على هذه الفاتورة", "وكم رصيد صاحب الفاتورة",
        "شو رصيد الزبون اللي بالفاتورة", "what is the balance of the customer on this invoice",
    ),
    "check_invoice_stock": (
        "هل الصنف في الفاتورة متوفر", "مخزون الأصناف اللي فيها", "هل الصنف الموجود فيها متوفر",
        "كم بقي منه في المخزون", "شو مخزون الصنف اللي فيها", "هل منتجات الفاتورة متوفرة",
        "شو وضع مخزون أصنافها", "check stock for the item on this invoice",
    ),
    "check_stock": (
        "هل هو متوفر", "هل هي متوفرة", "هو متوفر", "بعده موجود", "قديش ضل منه", "كم بقي منه",
        "كم بقي", "كم الموجود منه", "is it available", "how much is left in stock",
    ),
}
_REFERENCE_TYPE = {
    **_FOCUS, "get_latest_customer_invoice": "customer", "check_invoice_stock": "invoice",
    "get_invoice_customer_balance": "invoice",
}
_EXPLICIT_SUBJECT = {
    "customer": re.compile(r"\b(?:العميل|عميل|الزبون|زبون|customer)\b"),
    "invoice": re.compile(r"\b(?:الفاتوره|فاتوره|invoice)\b"),
    "product": re.compile(r"\b(?:الصنف|صنف|المنتج|منتج|item|product)\b"),
}
_MUTATION_OR_GUIDE = re.compile(
    r"(?:^|\s)(?:اضف|اعدل|عدل|احذف|الغي|الغ|سجل|اصدر|جهز|انشئ|انشي|انقل|ادفع|ادفعها|سدد|سددها|"
    r"رحل|نفذ|كيفيه|طريقه|خطوات|pay|post|delete|add|create|cancel|update|how to)(?:$|\s)"
)
_REFERENCE_WORD = re.compile(r"\b(?:invoice|customer|product|الفاتوره|العميل|الصنف)\b")
_EXTERNAL_REFERENCE = re.compile(r"#\d+|\b[a-z0-9]+(?:[-./][a-z0-9]+)+\b")
_CONNECTORS = frozenset({"و", "طيب", "تمام", "يعني", "لو", "سمحت", "and", "please", "now"})


def _text(message: str) -> str:
    return re.sub(r"[^\w\s]", " ", normalize(message).replace("ة", "ه")).strip()


_PROBES = tuple((tool, _text(example)) for tool, examples in _EXAMPLES.items() for example in examples)
_VOCAB = {tool: frozenset(word for example in examples for word in _text(example).split())
          for tool, examples in _EXAMPLES.items()}


@dataclass(frozen=True, slots=True)
class FollowUp:
    tool: str
    confidence: float
    references: tuple[EntityReference, ...]


def resolve_follow_up(message: str, context: InteractionContext) -> FollowUp | None:
    text = _text(message)
    if not text or len(text.split()) > 12 or _EXTERNAL_REFERENCE.search(normalize(message)):
        return None
    if _MUTATION_OR_GUIDE.search(text):
        return None

    focus = _FOCUS.get(context.conversation.last_tool)
    words = set(text.split()) - _CONNECTORS
    matches = {}
    for score, tool in scored_matches(text, _PROBES, threshold=0.49):
        vocabulary = _VOCAB[tool]
        if any(word not in vocabulary and word.removeprefix("و") not in vocabulary for word in words):
            continue
        kind = _REFERENCE_TYPE[tool]
        explicit = bool(_EXPLICIT_SUBJECT[kind].search(text))
        if kind != focus and not explicit and (focus is not None or not _REFERENCE_WORD.search(text)):
            continue
        matches.setdefault(tool, min(1.0, score + (0.08 if kind == focus else 0)))
    if not matches:
        return None
    ranked = sorted(matches, key=matches.get, reverse=True)
    tool = ranked[0]
    confidence = matches[tool]
    if len(ranked) > 1 and confidence - matches[ranked[1]] < 0.10:
        return None
    kind = _REFERENCE_TYPE[tool]
    references = tuple(reference for reference in context.conversation.references if reference.kind == kind)
    return FollowUp(tool, confidence, references)
