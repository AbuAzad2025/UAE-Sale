"""The assistant must answer questions from live tenant data, not show menus."""
import os

os.environ.setdefault("PYTHONIOENCODING", "utf-8")

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.ai_planner import plan
from services.ai_questions import answer, is_question


def test_question_detection():
    assert is_question("كم عدد المبيعات اليوم؟")
    assert is_question("how many customers?")
    assert not is_question("أنشئ فاتورة بيع للعميل أحمد")


def test_business_insights_are_localised_in_english():
    src = open(
        os.path.join(ROOT, "routes", "ai.py"), encoding="utf-8"
    ).read()
    assert '"تنبيه المخزون": "Inventory alert"' in src
    assert '"متابعة المدفوعات": "Payment follow-up"' in src


def test_sales_question_is_planned_as_read_tool():
    p = plan("كم عدد المبيعات اليوم؟")
    assert p.tool == "sales_summary"
    assert p.intent == "sales_analysis"
    assert p.source == "question"
    assert p.missing_fields == []


def test_inventory_question_is_not_a_creation_action():
    p = plan("ما حالة المخزون؟")
    assert p.tool == "inventory_status"
    assert p.needs_confirm is False


def test_grounded_fiscal_answer(db, owner_user):
    result = answer("ما حالة الفترات المالية؟", owner_user)
    assert result is not None
    assert "الفترات المالية" in result
    assert "مخزون" not in result


def test_grounded_answer_needs_permission(db):
    denied = answer("كم عدد المبيعات اليوم؟", None)
    assert "صلاحية" in denied
    assert "create" not in denied.lower()


def test_grounded_sales_answer_uses_live_data(db, owner_user):
    result = answer("كم عدد المبيعات اليوم؟", owner_user)
    assert result is not None
    assert "المبيعات اليوم" in result
    assert "فاتورة" in result
    assert "شركتك" in result
