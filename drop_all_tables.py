import psycopg2

conn = psycopg2.connect('postgresql://postgres:123@localhost:5432/uae_sale')
cur = conn.cursor()
cur.execute("""
    DO $$
    DECLARE
        r RECORD;
    BEGIN
        FOR r IN (SELECT tablename FROM pg_tables WHERE schemaname = 'public') LOOP
            EXECUTE 'DROP TABLE IF EXISTS ' || quote_ident(r.tablename) || ' CASCADE';
        END LOOP;
    END $$;
""")
conn.commit()
print('Dropped all tables')
conn.close()