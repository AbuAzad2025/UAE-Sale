"""Local natural-language understanding for the queued ERP agent."""

import re
from dataclasses import dataclass

from bot_core.gateway import normalize

_TOKEN = re.compile(r"#[0-9]+|[a-z0-9]+(?:[-./][a-z0-9]+)+|[0-9]+|[^\W\d_]+|[^\w\s]")
_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_NUMBER = re.compile(r"[0-9]+(?:\.[0-9]+)?")
_CODE = re.compile(r"#[0-9]+|[a-z0-9]+(?:[-/][a-z0-9]+)+")
CURRENCIES = frozenset({"ils", "aed", "usd", "eur", "sar", "jod", "شيكل", "درهم", "دولار"})
_EQUIVALENT = {
    "purchasing": "purchase", "procurement": "purchase", "توريد": "شراء",
    "تحويل": "transfer", "نقل": "transfer", "انقل": "transfer",
    "مخزني": "المخزون", "مخزون": "المخزون", "warehouses": "warehouse",
    "تسعيرة": "quotation", "تسعيره": "quotation", "quote": "quotation",
}
_FINANCIAL_TERMS = {
    "تسعيرة": "quotation", "تسعيره": "quotation", "التسعيرة": "quotation", "التسعيره": "quotation",
    "ذمة": "receivable", "ذمه": "receivable", "الذمة": "receivable", "الذمه": "receivable",
    "ذمم": "receivable", "الذمم": "receivable", "مديونية": "receivable", "مديونيه": "receivable",
    "مشتريات": "purchase", "المشتريات": "purchase", "purchasing": "purchase",
    "مستحق": "outstanding", "المستحق": "outstanding", "مستحقة": "outstanding",
}


def tokenize(text: str) -> list[str]:
    return _TOKEN.findall(normalize(text))[:64]


def feature(token: str, version: int = 2) -> str:
    if _DATE.fullmatch(token):
        return "<date>"
    if _NUMBER.fullmatch(token):
        return "<number>"
    if _CODE.fullmatch(token):
        prefix = token.split("-", 1)[0]
        if version >= 2 and prefix in ("inv", "invoice", "sale", "s"):
            return "<invoice-code>"
        if version >= 2 and prefix in ("sku", "item", "part"):
            return "<stock-code>"
        return "<code>"
    if token in CURRENCIES:
        return "<currency>"
    if version >= 3 and token in _FINANCIAL_TERMS:
        return _FINANCIAL_TERMS[token]
    return _EQUIVALENT.get(token, token) if version >= 2 else token


def regex_entities(tokens: list[str]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for index, token in enumerate(tokens):
        if _DATE.fullmatch(token):
            key = "date"
        elif (_CODE.fullmatch(token) or _NUMBER.fullmatch(token)) and any(
            word in {"account", "حساب"} for word in tokens[max(0, index - 2):index]
        ):
            key = "account_code"
        elif _CODE.fullmatch(token):
            key = "reference"
        elif _NUMBER.fullmatch(token):
            key = "quantity"
        elif token in CURRENCIES:
            key = "currency"
        else:
            continue
        result.setdefault(key, []).append(token)
    return result


@dataclass(frozen=True, slots=True)
class Prediction:
    intent: str
    confidence: float
    probabilities: dict[str, float]
    entities: dict[str, list[str]]
