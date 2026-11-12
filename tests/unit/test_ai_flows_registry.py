"""Flows registry tests — 13 flow موحد بلا تكرار"""

from services.ai_flows import FLOWS, FLOWS_BY_KEY, find_flow, render_menu, start_context


def test_registry_has_13_flows():
    assert len(FLOWS) == 13
    keys = {f.key for f in FLOWS}
    assert keys == {
        "balance",
        "customer",
        "product",
        "sale",
        "receive",
        "give",
        "expense",
        "supplier",
        "purchase",
        "cheque",
        "ledger",
        "warehouse",
        "user",
    }


def test_all_flows_have_permission_and_last_action():
    for f in FLOWS:
        assert f.permission.startswith("manage_")
        assert f.last_action
        assert len(f.options) >= 2
        assert any(num == "1" for num, _ in f.options)
        # Phase 3: tenant إلزامي لكل تدفق
        assert f.tenant_required is True


def test_only_balance_requires_confirmation():
    # Phase 3: confirm_required فقط لتدفق الرصيد المدمر
    assert FLOWS_BY_KEY["balance"].confirm_required is True
    for f in FLOWS:
        if f.key != "balance":
            assert f.confirm_required is False, f.key


def test_find_flow_keywords():
    assert find_flow("أريد عميل جديد").key == "customer"
    assert find_flow("رصيد العميل").key == "balance"
    assert find_flow("فاتورة بيع").key == "sale"
    assert find_flow("منتج جديد").key == "product"
    assert find_flow("مورد").key == "supplier"
    assert find_flow("مخزون").key == "warehouse"
    assert find_flow("دفتر الأستاذ").key == "ledger"
    assert find_flow("شكراً") is None


def test_render_menu_contains_options():
    menu = render_menu(FLOWS_BY_KEY["customer"])
    assert "1️⃣" in menu and "إضافة عميل جديد" in menu
    assert "🤖" in menu
    assert 'اكتب "1" لإضافة عميل جديد' in menu


def test_render_menu_hint_variants():
    # 2 options -> "(1 أو 2)"
    menu2 = render_menu(FLOWS_BY_KEY["ledger"])
    assert "(1 أو 2)" in menu2
    # 3 options -> "(1، 2، أو 3)"
    menu3 = render_menu(FLOWS_BY_KEY["customer"])
    assert "(1، 2، أو 3)" in menu3
    # 4 options -> "(1، 2، 3، أو 4)"
    menu4 = render_menu(FLOWS_BY_KEY["product"])
    assert "(1، 2، 3، أو 4)" in menu4


def test_start_context_shape():
    ctx = start_context(FLOWS_BY_KEY["sale"])
    assert ctx == {"last_action": "فاتورة", "step": 0}


def test_ordering_balance_before_customer():
    # 'رصيد العميل' يحتوي 'عميل' — يجب أن يُطابق balance أولاً (ترتيب FLOWS)
    assert find_flow("رصيد العميل").key == "balance"


def test_no_direct_customer_balance_write_in_ai_routes():
    # Phase 3: حظر الكتابة المباشرة customer.balance= من مسارات المساعد —
    # يجب أن تمر عبر _ai_set_customer_balance / PaymentService (مدقَّقة).
    from pathlib import Path

    text = Path("routes/ai.py").read_text(encoding="utf-8")
    assert "customer.balance =" not in text
    assert "_ai_set_customer_balance" in text


def test_balance_flow_has_confirmation_step():
    # Phase 3: تعديل الرصيد يتطلب تأكيداً صريحاً (confirm_required)
    from pathlib import Path

    text = Path("routes/ai.py").read_text(encoding="utf-8")
    assert "pending_balance" in text
    assert "تأكيد مطلوب" in text
    assert (
        "listener != 'confirm'" in text
        or 'listener != "confirm"' in text
        or "listener != 'confirm'" in text
    )


def test_ai_commands_stamp_tenant_and_audit():
    # Phase 3: كل أمر إنشاء يختم tenant ويكتب AuditLog
    from pathlib import Path

    text = Path("services/ai_commands.py").read_text(encoding="utf-8")
    assert "_require_tenant_id" in text
    assert "_ai_audit" in text
    assert "tenant_id" in text
    # لا إنشاء مباشر بلا ختم في الخدمة
    assert "**_stamp_tenant" in text


def test_assistant_open_to_all_config_owner_only():
    # Phase 4: /assistant لكل مسجل، /config للمالك فقط
    from pathlib import Path

    lines = Path("routes/ai.py").read_text(encoding="utf-8").splitlines()

    def decorators_above(def_name, window=6):
        idx = next(i for i, l in enumerate(lines) if f"def {def_name}(" in l)
        return "\n".join(lines[max(0, idx - window) : idx])

    assert "@owner_required" in decorators_above("config")
    assert "@owner_required" not in decorators_above("assistant_page")
    assert "@login_required" in decorators_above("assistant_page")


def test_nav_and_sidebar_expose_guide():
    # Phase 5: روابط المساعد والدليل في navbar/sidebar
    from pathlib import Path

    base = Path("templates/base.html").read_text(encoding="utf-8")
    assert "ai.assistant_page" in base
    assert "public.user_guide" in base
    assert "owner.owner_guide" in base
    # المساعد لم يعد مشروطاً بالمالك في navbar
    assert "لكل مستخدم مسجل" in base
    # assistant.html: زر البحث العتيق (return false) أُصلح
    asst = Path("templates/ai/assistant.html").read_text(encoding="utf-8")
    assert "return false" not in asst
    assert "public.user_guide" in asst
