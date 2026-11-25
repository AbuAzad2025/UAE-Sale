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



def test_sales_comparison_understands_joined_arabic_conjunction(db, owner_user):
    result = answer("قارن مبيعات اليوم وأمس", owner_user)
    assert "المبيعات اليوم" in result
    assert "المبيعات أمس" in result
    assert "الفرق في عدد الفواتير" in result


def test_sales_follow_up_is_read_only_and_checks_permissions(db, owner_user):
    assert answer("وأمس؟", owner_user) is None
    assert "المبيعات أمس" in answer("وأمس؟", owner_user, follow_up_topic="sales")
    assert "صلاحية" in answer("وأمس؟", None, follow_up_topic="sales")
    assert answer("سجل فاتورة بيع أمس", owner_user, follow_up_topic="sales") is None


def test_sales_comparison_uses_confirmed_invoices_by_currency(db, owner_user, test_sale):
    from datetime import date, datetime, timedelta

    from models import Sale

    today = date.today()
    yesterday = today - timedelta(days=1)
    test_sale.sale_date = datetime.combine(yesterday, datetime.min.time())
    for suffix, currency, status, amount in (
        ("usd", "USD", "confirmed", 25),
        ("cancelled", "AED", "cancelled", 999),
    ):
        db.session.add(
            Sale(
                sale_number=f"{test_sale.sale_number}-{suffix}",
                customer_id=test_sale.customer_id,
                seller_id=test_sale.seller_id,
                sale_date=test_sale.sale_date,
                total_amount=amount,
                amount_base=amount,
                currency=currency,
                status=status,
            )
        )
    db.session.flush()

    result = answer("قارن مبيعات اليوم وأمس", owner_user)
    assert "المبيعات اليوم: 0 فاتورة" in result
    assert "المبيعات أمس: 2 فاتورة" in result
    assert "100.00 AED" in result
    assert "25.00 USD" in result
    assert "999" not in result



def test_chat_sales_comparison_and_follow_up(client, login_owner):
    page = client.get("/ai/assistant")
    assert page.status_code == 200
    assert "salesFollowUps" in page.get_data(as_text=True)

    comparison = client.post(
        "/ai/chat",
        json={"message": "قارن مبيعات هذا الشهر والشهر الماضي", "ai_mode": "local"},
    )
    assert comparison.status_code == 200
    initial = comparison.get_json()
    assert initial["grounded"] is True
    assert "المبيعات هذا الشهر" in initial["response"]
    assert "المبيعات الشهر الماضي" in initial["response"]

    follow_up = client.post(
        "/ai/chat",
        json={"message": "وأمس؟", "follow_up_topic": initial["follow_up_topic"]},
    )
    assert follow_up.status_code == 200
    assert "المبيعات أمس" in follow_up.get_json()["response"]
