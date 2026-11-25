"""Independent HTTP inference worker for Arabic and English ERP intents."""

from hashlib import blake2b
import os
import re

import numpy as np
from flask import Flask, jsonify, request

from services.ai_normalize import normalize

EXAMPLES = {
    "check_stock": (
        "كم باقي من الصنف", "كم الكمية المتوفرة من القطعة", "هل الصنف متوفر في المخزون",
        "مخزون بند المستودع", "check stock for item", "how many units are in stock",
    ),
    "get_invoice_status": (
        "وين وصلت فاتورة رقم", "هل الفاتورة مدفوعة", "اريد معرفة حالة الفاتورة",
        "هل تم اعتماد فاتورة البيع", "is my invoice paid", "check invoice status",
    ),
    "get_customer_balance": (
        "كم بذمة الزبون", "أريد معرفة رصيد العميل", "ما رصيد حساب شركة النور",
        "شو رصيد الزبون", "customer balance lookup", "what does the customer owe",
    ),
    "create_draft_quote": (
        "أريد إعداد عرض سعر", "جهز تسعيرة للعميل", "أنشئ مسودة عرض أسعار",
        "بدي اعمل عرض سعر للزبون", "prepare a quotation draft", "create a price quote",
    ),
    "create_customer": (
        "أضف عميلا جديدا", "بدي أسجل زبون جديد", "أريد فتح ملف عميل",
        "إنشاء حساب لعميل جديد", "register a new customer", "add new customer",
    ),
    "create_purchase_order": (
        "أريد إنشاء أمر شراء", "جهز مسودة أمر شراء", "بدي اطلب من المورد",
        "فتح أمر توريد", "start a purchase order", "draft an order for supplier",
    ),
    "guide": (
        "مرحبا كيف الحال", "كيف أستخدم النظام", "كيف أطبع من الشاشة",
        "شرح الواجهة", "hello what can you do", "show me the manual",
    ),
}

_REFERENCE = re.compile(r"(?<!\w)#\d{1,9}\b|\b[A-Za-z][A-Za-z0-9]*(?:[-/][A-Za-z0-9]+)+\b")
_NUMERIC_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_QUANTITY = re.compile(r"\b(?:كمية|quantity)\s*[:：]?\s*(\d{1,9}(?:[.٫]\d{1,3})?)\b", re.I)
_EXPLICIT_NAME = re.compile(
    r"(?:باسم|اسمه|اسم العميل|customer name)\s*[:：]?\s*([^،,\n|]+)",
    re.I,
)

FEATURE_COUNT = 512


def _features(text):
    normalized = normalize(_REFERENCE.sub(" ", text))
    vector = np.zeros(FEATURE_COUNT, dtype=np.float32)
    for token in normalized.split():
        padded = f"^{token}$"
        for size in (2, 3, 4):
            for start in range(len(padded) - size + 1):
                fragment = padded[start:start + size]
                digest = blake2b(fragment.encode(), digest_size=2).digest()
                vector[int.from_bytes(digest, "little") % FEATURE_COUNT] = 1
    length = np.linalg.norm(vector)
    return vector / length if length else vector


def _softmax(values):
    exponentials = np.exp(values - values.max(axis=-1, keepdims=True))
    return exponentials / exponentials.sum(axis=-1, keepdims=True)


class IntentClassifier:
    """A character n-gram network with one learned hidden layer."""

    def __init__(self):
        self.labels = tuple(EXAMPLES)
        examples = [_features(text) for phrases in EXAMPLES.values() for text in phrases]
        targets = [index for index, phrases in enumerate(EXAMPLES.values()) for _ in phrases]
        inputs = np.asarray(examples)
        expected = np.eye(len(self.labels), dtype=np.float32)[targets]
        random = np.random.default_rng(17)
        self.hidden = random.normal(0, 0.06, (FEATURE_COUNT, 24)).astype(np.float32)
        self.output = random.normal(0, 0.06, (24, len(self.labels))).astype(np.float32)
        for _ in range(260):
            activations = np.tanh(inputs @ self.hidden)
            residual = (_softmax(activations @ self.output) - expected) / len(inputs)
            hidden_gradient = inputs.T @ ((residual @ self.output.T) * (1 - activations ** 2))
            self.output -= 0.55 * (activations.T @ residual)
            self.hidden -= 0.55 * hidden_gradient

    def _classify(self, text):
        scores = _softmax(np.tanh(_features(text) @ self.hidden) @ self.output)
        best = int(scores.argmax())
        return self.labels[best], float(scores[best])

    def predict(self, text):
        clauses = re.split(r"[،,؛;|\n]", text, maxsplit=1)
        if len(clauses) == 2:
            command, details = clauses
            if any(extract_entities(details).values()):
                intent, confidence = self._classify(command)
                if intent != "guide" and confidence >= 0.65:
                    return intent, confidence
        return self._classify(text)


def extract_entities(message):
    """Extract bounded candidates for the ERP web process to validate."""
    return {
        "references": _REFERENCE.findall(message)[:5],
        "dates": _NUMERIC_DATE.findall(message)[:5],
        "quantities": _QUANTITY.findall(message)[:5],
        "names": [name.strip()[:200] for name in _EXPLICIT_NAME.findall(message)[:2]],
    }


def create_app():
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 32768
    classifier = IntentClassifier()

    @app.post("/interpret")
    def interpret():
        body = request.get_json(silent=True)
        message = body.get("message") if isinstance(body, dict) else None
        if not isinstance(message, str) or not 0 < len(message) <= 4000:
            return jsonify(error="Invalid input"), 400
        intent, confidence = classifier.predict(message)
        return jsonify(intent=intent, confidence=confidence, entities=extract_entities(message))

    return app


if __name__ == "__main__":
    create_app().run(
        host=os.environ.get("AI_NLU_HOST", "127.0.0.1"),
        port=int(os.environ.get("AI_NLU_PORT", "8011")),
        debug=False,
    )
