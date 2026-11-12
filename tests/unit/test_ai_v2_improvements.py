"""اختبارات تحسينات v2: normalize + planner + tools registry."""


def test_normalize_arabic_numbers_and_words():
    from services.ai_normalize import normalize, tokenize

    assert normalize("١٢٣") == "123"
    # أرقام حروفاً
    assert "1000" in normalize("رصيد العميل ألف درهم")
    assert "500" in normalize("دفعة خمسمئة درهم")
    # أليف / ة / ى
    n = normalize("إنشاء الفاتورة الجديدة")
    assert "فاتوره" in normalize("فاتورة")
    toks = tokenize("فاتوره جديده")
    assert "فاتورة" in toks or "فاتوره" in toks
    toks2 = tokenize("زبون جديد")
    assert "عميل" in toks2 or "customer" in toks2


def test_planner_extracts_customer_and_amount():
    from services.ai_planner import extract_entities, plan

    ents = extract_entities("استلام 500 درهم من عميل أحمد")
    assert ents["amounts"]
    assert ents["names"]
    p = plan("استلام 500 درهم من عميل أحمد")
    assert p.tool == "record_payment"
    assert p.params.get("amount") == 500
    assert p.params.get("customer_name") == "أحمد"


def test_planner_amount_word_numbers():
    from services.ai_planner import plan

    p = plan("رصيد العميل أحمد ألف درهم")
    assert p.tool == "set_customer_balance"
    assert p.params.get("new_balance") == 1000


def test_planner_missing_fields_balance():
    from services.ai_planner import plan

    p = plan("كم رصيد العميل")
    assert p.tool == "set_customer_balance"
    assert "customer_name" in p.missing_fields
    assert "new_balance" in p.missing_fields
    assert p.needs_confirm is True


def test_tools_registry_describes():
    from services.ai_tools import TOOLS_BY_NAME, describe_tools

    assert TOOLS_BY_NAME["set_customer_balance"].destructive is True
    assert TOOLS_BY_NAME["get_customer_balance"].destructive is False
    desc = describe_tools()
    assert "create_customer" in desc
    assert "set_customer_balance" in desc


def test_eval_passes_threshold():
    from services.ai_eval import run_eval

    r = run_eval()
    assert r["intent_accuracy"] >= 0.85, f"intent {r['intent_accuracy']}"
    assert r["tool_accuracy"] >= 0.85, f"tool {r['tool_accuracy']}"
