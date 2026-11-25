"""Bounded access to the optional independent assistant NLU service."""

import math

import requests
from flask import current_app

_KNOWN_INTENTS = {
    "check_stock", "get_invoice_status", "get_customer_balance", "create_draft_quote",
    "create_customer", "create_purchase_order", "guide",
}


def classify(message):
    endpoint = current_app.config.get("AI_NLU_URL")
    if not endpoint:
        return None
    try:
        response = requests.post(
            endpoint,
            json={"message": message},
            timeout=(0.2, 0.35),
            allow_redirects=False,
        )
        if response.status_code != 200:
            return None
        result = response.json()
        intent = result["intent"]
        confidence = float(result["confidence"])
        if intent not in _KNOWN_INTENTS or not math.isfinite(confidence) or not 0 <= confidence <= 1:
            return None
        entities = result.get("entities")
        references = entities.get("references", []) if isinstance(entities, dict) else []
        if not isinstance(references, list):
            references = []
        references = [
            reference for reference in references[:5]
            if isinstance(reference, str) and 0 < len(reference) <= 50 and reference in message
        ]
        return intent, confidence, references
    except (requests.RequestException, TypeError, ValueError, KeyError):
        return None
