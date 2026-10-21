import psycopg2

c = psycopg2.connect('postgresql://azad_boot:azad_boot@127.0.0.1:5432/azad_boot')
cur = c.cursor()

out = []


def q(sql, label=None):
    cur.execute(sql)
    rows = cur.fetchall()
    out.append(f'{label or sql}: {rows}')
    return rows


q("SELECT version_num FROM alembic_version", 'alembic head')
for t, col in [('gl_accounts', 'is_system'), ('fiscal_periods', 'tenant_id'),
                ('customers', 'opening_balance'), ('customers', 'opening_balance_currency'),
                ('customers', 'opening_balance_rate'), ('customers', 'opening_balance_date'),
                ('suppliers', 'opening_balance'), ('suppliers', 'opening_balance_currency'),
                ('suppliers', 'opening_balance_rate'), ('suppliers', 'opening_balance_date'),
                ('payments', 'purchase_id'), ('receipts', 'allocations_json')]:
    cur.execute("SELECT count(*) FROM information_schema.columns "
                "WHERE table_name=%s AND column_name=%s", (t, col))
    out.append(f'column {t}.{col}: {"PRESENT" if cur.fetchone()[0] else "MISSING"}')

cur.execute("""SELECT conrelid::regclass::text, conname FROM pg_constraint
               WHERE contype='c' AND conname LIKE 'ck_sales%'
                  OR conname LIKE 'ck_product%' OR conname LIKE 'ck_saleline%'
                  OR conname LIKE 'ck_purchase%' OR conname LIKE 'ck_purchaseline%'
                  OR conname LIKE 'ck_payment%' OR conname LIKE 'ck_receipt%'
               ORDER BY conname""")
out.append('CHECK constraints:')
for t, n in cur.fetchall():
    out.append(f'   {n:<42} on {t}')

cur.execute("SELECT count(*) FROM gl_accounts WHERE is_system")
out.append(f'gl_accounts marked is_system: {cur.fetchone()[0]}')

c.close()
with open(r'D:\recovers\data\UAE-Sale\_mig_check.txt', 'w', encoding='utf-8') as fh:
    fh.write('\n'.join(out))
print('done')
