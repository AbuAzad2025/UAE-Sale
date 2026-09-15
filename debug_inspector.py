import os
os.environ['SECRET_KEY'] = 'test-secret-key'
os.environ['OWNER_PASSWORD'] = 'TestOwner1234567890123456'
os.environ['APP_ENV'] = 'testing'

from app import create_app
app = create_app()

with app.app_context():
    from sqlalchemy import inspect
    from extensions import db
    
    # Check raw connection
    conn = db.engine.raw_connection()
    cur = conn.cursor()
    cur.execute("SELECT tablename FROM pg_tables WHERE schemaname='public'")
    tables = [row[0] for row in cur.fetchall()]
    print(f'Raw psycopg2 tables: {len(tables)}')
    
    # Check inspector
    inspector = inspect(db.engine)
    insp_tables = set(inspector.get_table_names())
    print(f'Inspector tables: {len(insp_tables)}')
    
    critical = {'customers', 'expenses', 'gl_accounts', 'gl_journal_entries', 'gl_journal_lines', 'integration_settings', 'permissions', 'products', 'roles', 'sales', 'system_settings', 'tenants'}
    
    print(f'Has customers (raw): {"customers" in tables}')
    print(f'Has customers (insp): {"customers" in insp_tables}')
    print(f'Missing (raw): {critical - set(tables)}')
    print(f'Missing (insp): {critical - insp_tables}')