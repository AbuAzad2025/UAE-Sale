from dotenv import load_dotenv
load_dotenv(".env")
import psycopg2
c=psycopg2.connect("postgresql://postgres:123@localhost:5433/ERPLite2026");cur=c.cursor()
cur.execute("SELECT id,name FROM customers WHERE name LIKE '%المعابر والحدود%'")
print(cur.fetchall())
c.close()
