import os
os.environ.setdefault('PYTHONIOENCODING','utf-8')
from app import create_app
app=create_app()
with app.app_context():
    from extensions import db
    from sqlalchemy import text
    from decimal import Decimal as D
    from models import set_current_tenant_id
    set_current_tenant_id(2)
    
    # 1. Products
    for r in db.session.execute(text("SELECT id,name,current_stock,regular_price,cost_price FROM products WHERE tenant_id=2 ORDER BY id")).fetchall():
        price=__import__('decimal').Decimal(str(r[3] or 0))
        cost=__import__('decimal').Decimal(str(r[4] or 0))
        margin=((r[3]-r[4])/r[4]*100) if r[4] else 0
        print(f'P{r[0]} | {r[1][:22]:22} | Stock:{r[3]:>8.1f} | Price:{r[3]:>8.2f} | Cost:{r[4]:>8.2f} | Margin:{float((r[3]-r[4])/r[4]*100) if r[4] else 0:>5.1f}%')
    
    # GL balance
    bad=db.session.execute(text("SELECT COUNT(*) FROM (SELECT e.id FROM gl_journal_entries e JOIN gl_journal_lines l ON l.entry_id=e.id GROUP BY e.id HAVING ABS(SUM(l.debit)-SUM(l.credit))>0.001) x")).scalar()
    print('GLBAD',bad)
    
    # Inventory
    from models import set_current_tenant_id
    set_current_tenant_id(2)
    from services.inventory_reconciliation import reconcile_inventory
    rr=reconcile_inventory(tenant_id=2)
    print('INV',rr['control_balance'],rr['total_valuation_at_average_cost'],'DIFF',rr['gl_difference'],'BAL',rr['balanced'])
    
    # AP/AR
    from services.subledger_reconciliation import SubLedgerReconciliation
    for s in SubLedgerReconciliation.reconcile_all(tenant_id=2):
        print('SUB',s.get('section'),'diff',s.get('control_difference'),'bal',s.get('balanced'))