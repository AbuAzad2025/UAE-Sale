import os, sys, traceback
os.environ["DATABASE_URL"]="sqlite:///:memory:"
os.environ.setdefault("SECRET_KEY","x")
os.environ.setdefault("OWNER_PASSWORD","E2eOwner@1234567890123456!")
try:
    from app import create_app
    from config import Config
    from decimal import Decimal
    from datetime import datetime, timedelta, timezone as tz

    class C(Config):
        SQLALCHEMY_DATABASE_URI="sqlite:///:memory:"
        RATELIMIT_ENABLED=False
        WTF_CSRF_ENABLED=False

    app=create_app(C)
    with app.app_context():
        from extensions import db
        db.create_all()
        from models import User, Supplier, Purchase, Payment

        owner = User.query.filter_by(username="owner").first()
        if not owner:
            owner = User(username="owner", email="owner@test.com", is_active=True, is_owner=True)
            owner.set_password("TestOwner1234567890123456")
            db.session.add(owner)
            db.session.commit()

        old = Supplier(name="Old Sup", is_active=True)
        new = Supplier(name="New Sup", is_active=True)
        dormant = Supplier(name="Dormant Sup", is_active=True)
        db.session.add_all([old, new, dormant])
        db.session.commit()

        def _mk_purchase(supplier, number, amount, days_ago=0):
            p = Purchase(
                purchase_number=number,
                supplier_id=supplier.id,
                supplier_name=supplier.name,
                purchase_date=datetime.now(tz.utc) - timedelta(days=days_ago),
                subtotal=amount,
                discount_amount=Decimal("0"),
                tax_rate=Decimal("0"),
                tax_amount=Decimal("0"),
                total_amount=amount,
                currency="ILS",
                exchange_rate=Decimal("1"),
                amount_base=amount,
                status="confirmed",
                created_by=owner.id
            )
            db.session.add(p)
            db.session.commit()
            return p

        def _mk_payment(number, amount, supplier_id, confirmed=True):
            pay = Payment(
                payment_number=number,
                supplier_id=supplier_id,
                direction="outgoing",
                amount=amount,
                amount_base=amount,
                currency="ILS",
                exchange_rate=Decimal("1"),
                payment_confirmed=confirmed,
                created_by=1
            )
            db.session.add(pay)
            db.session.commit()
            return pay

        def _dt(days=0):
            return datetime.now(tz.utc) - timedelta(days=days)

        _mk_purchase(old, "P-RPT-OLD", Decimal("800"), 100)
        _mk_purchase(new, "P-RPT-NEW", Decimal("500"), 0)
        _mk_payment("PAY-RPT-NEW", Decimal("100"), new.id, confirmed=True)
        _mk_payment("PAY-RPT-PEND", Decimal("50"), new.id, confirmed=False)

        from services.aging_analysis_service import AgingAnalysisService
        report = AgingAnalysisService.get_payables_aging()
        out = []
        for s in report.get("suppliers", []):
            sup = s["supplier"]
            out.append(f"{sup.name}: total={s.get('total')}, overdue_total={s.get('overdue_total')}, balance={s.get('total', 0)}")
        print("\n".join(out), file=sys.stdout, flush=True)
except Exception as e:
    traceback.print_exc()
    sys.exit(1)