import os
os.environ.setdefault('PYTHONIOENCODING','utf-8')
from app import create_app
app=create_app()
with app.app_context():
    from models import set_current_tenant_id
    set_current_tenant_id(2)
    from extensions import db
    from sqlalchemy import text
    from decimal import Decimal as D
    from models import Purchase
    
    # Fix amount_base for tax-inclusive purchases
    purchases = db.session.execute(text("SELECT id, total_amount, tax_amount, tax_inclusive FROM purchases WHERE tax_inclusive=true AND tenant_id=2")).fetchall()
    for r in rows:
        pid, total, tax = r[0], D(str(r[1] or 0)), D(str(r[2] or 0))
        if r[3]:  # tax_inclusive
            base = (total - tax).quantize(D('0.001'))
        else:
            base = total
        db.session.execute(text("UPDATE purchases SET amount_base=:b WHERE id=:id"), {'b': base, 'id': pid})
    
    db.session.commit()
    print('FIXED amount_base for tax-inclusive purchases')
    
    # Verify
    rows = db.session.execute(text("SELECT id, purchase_number, total_amount, amount_base, tax_amount, tax_inclusive FROM purchases WHERE tenant_id=2 ORDER BY id")).fetchall()
    for r in rows:
        print(f'P{r[0]} {r[1]}: total={r[2]} base={r[3]} tax={r[4]} incl={r[5]}')