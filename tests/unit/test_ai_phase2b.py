"""Phase 2b: معالجات مقسمة + تنفيذ مباشر + permission_code + Groq منظم."""

from services.ai_commands import PERMISSION_MAP, permission_for_tool


def test_permission_map_covers_all_commands():
    expected = {
        "create_customer",
        "create_product",
        "create_sale",
        "record_payment",
        "create_expense",
        "create_supplier",
        "create_purchase",
        "create_cheque",
        "create_user",
    }
    assert set(PERMISSION_MAP) == expected
    assert permission_for_tool("create_customer") == "manage_customers"
    assert permission_for_tool("unknown") is None


def test_handlers_dispatch_importable():
    from services.ai_handlers import dispatch, dispatch_for_action
    from services.ai_planner import plan

    p = plan("كم رصيد العميل", user=None)
    # unauthenticated: denial (not crash), not clarification crash
    r = dispatch(p, user=None)
    assert "executed" in r
    # digit/menu messages bypass new path (legacy owns them)
    assert dispatch_for_action("1", user=None) is None
    assert dispatch_for_action("عودة", user=None) is None
    assert dispatch_for_action("نعم", user=None) is None


def test_groq_action_structured_no_direct_write():
    from services.ai_service import AIService

    out = AIService._execute_ai_action(
        '{"action": "create_customer", "data_needed": ["name"]}', user_id=1
    )
    assert out is not None and ("يحتاج" in out or "جاهز" in out or "تمام" in out)
    assert AIService._execute_ai_action("hello", user_id=1) is None


def test_guide_routes_exist():
    import pathlib

    owner = pathlib.Path("routes/owner.py").read_text(encoding="utf-8")
    assert (
        "/guide" in owner and "owner_required" in owner and "def owner_guide" in owner
    )
    assert pathlib.Path("templates/public/user_guide.html").exists()
    assert pathlib.Path("templates/owner/guide.html").exists()
    base = pathlib.Path("templates/base.html").read_text(encoding="utf-8")
    assert "public.user_guide" in base
    dash = pathlib.Path("templates/owner/dashboard.html").read_text(encoding="utf-8")
    assert "owner_guide" in dash or "دليل المالك" in dash


def test_sidebar_separates_owner_console_from_tenant_business():
    import pathlib

    base = pathlib.Path("templates/base.html").read_text(encoding="utf-8")
    # البزنس للمستأجر فقط
    assert "if not (current_user.is_owner" in base
    # كونسول المنصة للمالك
    assert "url_for('owner.dashboard')" in base
    assert "url_for('owner.tenants_list')" in base
    # مبدّل الشركة
    assert "owner_tenants" in base
    # اللسان العامة مسرودة (المساعد لكل مسجل)
    assert "ai.assistant_page" in base
    tb_apps = pathlib.Path("templates/base.html").read_text(encoding="utf-8")
    assert tb_apps.count("ai.config") >= 1
