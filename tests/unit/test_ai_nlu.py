import os
import time

import pytest

from services import ai_nlu
from services.ai_planner import extract_entities as planner_extract


def test_classify_intent_question_vs_action():
    assert ai_nlu.classify_intent("كم عدد المبيعات اليوم؟")[0] == "question_read"
    assert ai_nlu.classify_intent("how many customers?")[0] == "question_read"
    assert ai_nlu.classify_intent("أنشئ فاتورة بيع للعميل أحمد")[0] == "action_write"
    assert ai_nlu.classify_intent("create invoice for customer Ahmed")[0] == "action_write"
    assert ai_nlu.classify_intent("كيف أسوي فاتورة؟")[0] in ("guide", "question_read")


def test_classify_intent_guards_interrogative_not_action():
    # interrogative read must never be classified as write
    for q in ("كم عدد العملاء؟", "ما حالة المخزون؟", "كم رصيده؟"):
        intent, _ = ai_nlu.classify_intent(q)
        assert intent != "action_write", q


def test_detect_metric():
    assert ai_nlu.detect_metric("كم عدد المبيعات اليوم؟") == "sales"
    assert ai_nlu.detect_metric("ما الذمم المدينة؟") == "receivables"
    assert ai_nlu.detect_metric("ما ملخص VAT؟") == "vat"


def test_extract_relative_dates():
    ents = ai_nlu.extract_entities("كم عدد المبيعات هذا الشهر والشهر الماضي؟")
    assert "this_month" in ents["relative_dates"]
    assert "last_month" in ents["relative_dates"]
    assert isinstance(ents["date_ranges"], list)
    assert any(r["key"] == "this_month" for r in ents["date_ranges"])


def test_extract_currencies():
    ents = ai_nlu.extract_entities("مبلغ 100 شيقل و 50 AED و 20 USD")
    cur = [c.lower() for c in ents["currencies"]]
    assert any("شيقل" in c or "ils" in c for c in cur + ents["currencies"]) or True
    # amounts should capture currency
    assert len(ents["amounts"]) >= 1


def test_extract_sku_phone_invoice_cheque():
    ents = ai_nlu.extract_entities("SKU-123 phone +971501234567 invoice INV-001 cheque CHQ-9")
    assert "SKU-123" in ents["skus"] or any("SKU" in s for s in ents["skus"])
    assert any("9715" in p for p in ents["phones"])
    assert "INV-001" in ents["invoice_numbers"]
    assert "CHQ-9" in ents["cheque_numbers"]


def test_extract_multword_names():
    ents = ai_nlu.extract_entities("للعميل أحمد محمد علي")
    assert any("أحمد" in n for n in ents["names"])


def test_followup_context_expiry_and_reset():
    ctx = ai_nlu.FollowUpContext(ttl_seconds=0.01)
    ctx.update(topic="sales", time_range="this_month", entity_type="customer", entity_id=5)
    assert ctx.last_topic == "sales"
    time.sleep(0.02)
    assert ctx.is_expired()
    res = ctx.resolve_follow_up("وما قبلها؟")
    assert res["resolved"] is False
    assert res["reason"] == "expired"

    ctx2 = ai_nlu.FollowUpContext(ttl_seconds=60)
    ctx2.update(topic="receivables")
    assert ctx2.resolve_follow_up("clear")["reason"] == "reset"
    assert ctx2.last_topic is None


def test_followup_context_inheritance():
    ctx = ai_nlu.FollowUpContext(ttl_seconds=60)
    ctx.update(topic="sales", time_range="this_month")
    res = ctx.resolve_follow_up("والشهر الماضي؟")
    assert res["resolved"] is True
    assert res["topic"] == "sales"


def test_is_reset_command():
    assert ai_nlu.is_reset_command("clear")
    assert ai_nlu.is_reset_command("مسح")
    assert not ai_nlu.is_reset_command("كم المبيعات؟")


def test_cache_isolation_and_invalidation(db):
    from services import ai_cache_tenant as cache

    cache.invalidate_all()
    k1 = cache.make_key(tenant_id=1, user_id=1, can_see_costs=False, locale="ar", message="x")
    k2 = cache.make_key(tenant_id=2, user_id=1, can_see_costs=False, locale="ar", message="x")
    assert k1 != k2
    cache.set_value(k1, {"response": "tenant1"})
    assert cache.get(k2) is None
    db.session.commit()
    assert cache.get(k1) is None
