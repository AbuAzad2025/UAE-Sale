import psycopg2

conn = psycopg2.connect('postgresql://postgres:123@localhost:5432/uae_sale')
cur = conn.cursor()
cur.execute("SELECT tablename FROM pg_tables WHERE schemaname='public'")
tables = cur.fetchall()
print(f'Total tables: {len(tables)}')
for t in tables:
    print(f'  {t[0]}')
conn.close()