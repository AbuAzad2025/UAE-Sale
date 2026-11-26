"""Stage 0 — reproducible evaluation harness for the local AI assistant."""
import os

os.environ.setdefault("PYTHONIOENCODING", "utf-8")

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models import Customer, Tenant, User
from models.tenant_scope import set_current_tenant_id
from services.ai_eval import run_eval, run_grounded_eval
from services.ai_questions import answer


def _make_user(db, username, tenant_id, perm_codes):
    from models import Permission, Role

    role = Role(name=username + "_role", name_ar=username, slug=username + "_role", is_active=True, tenant_id=tenant_id)
    db.session.add(role)
    db.session.flush()
    for code in perm_codes:
        perm = Permission.query.filter_by(code=code).first()
        if perm is not None and perm not in role.permissions:
            role.permissions.append(perm)
    db.session.commit()
    user = User(
        username=username,
        email=f"{username}@test.local",
        full_name=username,
        tenant_id=tenant_id,
        role_id=role.id,
        is_active=True,
    )
    user.set_password("Pass123!")
    db.session.add(user)
    db.session.commit()
    return user


def test_planner_eval_threshold():
    report = run_eval()
    assert report["intent_accuracy"] >= 0.85
    assert report["tool_accuracy"] >= 0.85
    assert report["total"] >= 30


def test_grounded_eval_for_tenant_user(db, owner_user):
    tenant = Tenant(name="Eval Tenant", name_ar="تقييم", slug="eval-tenant", is_active=True)
    db.session.add(tenant)
    db.session.commit()
    user = _make_user(
        db,
        "eval_tenant_user",
        tenant.id,
        [
            "manage_sales",
            "view_reports",
            "manage_customers",
            "manage_products",
            "view_products",
            "manage_expenses",
            "view_ledger",
            "manage_payments",
            "manage_ledger",
        ],
    )
    report = run_grounded_eval(user)
    for row in report["rows"]:
        print("ROW", row["q"], row["ok"], (row["result"] or "")[:90])
    assert report["accuracy"] == 1.0, report["rows"]
    assert report["denied"] == 0


def test_grounded_eval_denies_unauthenticated():
    report = run_grounded_eval(None)
    assert report["accuracy"] == 0.0
    assert report["denied"] == len(report["rows"])


def test_grounded_sales_answer_uses_live_data(db, owner_user):
    result = answer("كم عدد المبيعات اليوم؟", owner_user)
    assert result is not None
    assert "المبيعات اليوم" in result
    assert "فاتورة" in result


def test_grounded_answer_respects_tenant_isolation(db, owner_user):
    t1 = Tenant(name="Eval A", name_ar="أ", slug="eval-a", is_active=True)
    t2 = Tenant(name="Eval B", name_ar="ب", slug="eval-b", is_active=True)
    db.session.add_all([t1, t2])
    db.session.commit()

    set_current_tenant_id(t1.id)
    c1 = Customer(name="Alpha Customer", name_ar="ألفا", customer_type="regular", is_active=True, tenant_id=t1.id)
    db.session.add(c1)
    db.session.commit()

    set_current_tenant_id(t2.id)
    c2 = Customer(name="Beta Customer", name_ar="بيتا", customer_type="regular", is_active=True, tenant_id=t2.id)
    db.session.add(c2)
    db.session.commit()

    set_current_tenant_id(t1.id)
    user1 = _make_user(db, "eval_user_a", t1.id, ["view_reports", "manage_customers"])
    set_current_tenant_id(t2.id)
    user2 = _make_user(db, "eval_user_b", t2.id, ["view_reports", "manage_customers"])

    set_current_tenant_id(t1.id)
    result1 = answer("كم عدد العملاء؟", user1)
    set_current_tenant_id(t2.id)
    result2 = answer("كم عدد العملاء؟", user2)
    assert "العملاء النشطون في الشركة الحالية: 1." in result1
    assert "العملاء النشطون في الشركة الحالية: 1." in result2
    assert "Alpha Customer" not in result2
    assert "Beta Customer" not in result1


def test_grounded_answer_respects_permission(db, owner_user):
    user = _make_user(db, "eval_plain", None, [])
    result = answer("كم عدد المبيعات اليوم؟", user)
    assert result is not None
    assert "صلاحية" in result


def test_business_insights_are_localised_in_english():
    src = open(os.path.join(ROOT, "routes", "ai.py"), encoding="utf-8").read()
    assert '"تنبيه المخزون": "Inventory alert"' in src
    assert '"متابعة المدفوعات": "Payment follow-up"' in src
