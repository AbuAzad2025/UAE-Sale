import os
os.environ.setdefault('PYTHONIOENCODING','utf-8')
from app import create_app
app=create_app()
with app.app_context():
    from models import set_current_tenant_id
    set_current_tenant_id(2)
    from extensions import db
    from sqlalchemy import text
    def cnt(t): return db.session.execute(text(f"SELECT COUNT(*) FROM {t}")).scalar()
    print('BEFORE',cnt('sales'),cnt('payments'),cnt('cheques'),cnt('gl_journal_entries'))
    # TRUNCATE CASCADE wipes all dependent rows automatically in one statement
    db.session.execute(text("TRUNCATE TABLE sales, payments, cheques CASCADE"))
    db.session.commit()
    print('AFTER',cnt('sales'),cnt('payments'),cnt('cheques'),cnt('gl_journal_entries'),cnt('product_returns'),cnt('stock_movements'))
