import os
os.environ.setdefault('PYTHONIOENCODING','utf-8')
from app import create_app
app=create_app()
with app.app_context():
    from extensions import db
    from sqlalchemy import text
    from models import set_current_tenant_id
    set_current_tenant_id(2)

    # Fix product cost prices for products 1-5, 6, 7, 9, 10, 11
    costs = {1: 1200, 2: 320, 3: 15, 4: 140, 5: 80, 6: 2.85, 7: 2.45, 9: 50, 10: 700, 11: 1489.66}
    for pid, cost in {1:1200, 2:320, 3:15, 4:140, 5:80, 6:2.85, 7:2.45, 9:50, 10:700, 11:1489.66}.items():
        db.session.execute(text("UPDATE products SET average_cost=:c, cost_price=:c WHERE id=:p"), {'c':cost, 'p':pid})
    
    # Fix stock quantities from movements
    from extensions import db
    from sqlalchemy import text
    for pid in (6,7,8,9,10,11):
        q = db.session.execute(text("SELECT COALESCE(SUM(quantity),0) FROM stock_movements WHERE tenant_id=2 AND product_id=:p"), {'p':pid}).scalar()
        q = max(0, float(q or 0))
        db.session.execute(text("UPDATE products SET current_stock=:q WHERE id=:p"), {'q':q, 'p':pid})
    
    # Remove negative stock for product 8 (deleted product)
    db.session.execute(text("DELETE FROM stock_movements WHERE tenant_id=2 AND product_id=8"))
    db.session.execute(text("UPDATE products SET current_stock=0, average_cost=0 WHERE id=8"))
    
    db.session.commit()
    print('FIXED COSTS AND STOCK')

    # Recalculate inventory
    from models import set_current_tenant_id
    set_current_tenant_id(2)
    from services.inventory_reconciliation import reconcile_inventory
    rr = reconcile_inventory(tenant_id=2)
    print('INV', rr['control_balance'], rr['total_valuation_at_average_cost'], 'DIFF', rr['gl_difference'], 'BAL', rr['balanced'])