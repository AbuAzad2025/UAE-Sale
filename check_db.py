"""التحقق من بنية قاعدة البيانات"""
import sqlite3

conn = sqlite3.connect('instance/garage.db')
cursor = conn.cursor()

# التحقق من جدول payment_vault
cursor.execute("PRAGMA table_info(payment_vault)")
columns = cursor.fetchall()

print(f'\n🔍 فحص جدول payment_vault:')
print(f'✅ عدد الأعمدة: {len(columns)}')
print('\n📋 قائمة الأعمدة:')
for col in columns:
    print(f'  {col[0]:2d}. {col[1]:30s} ({col[2]})')

# التحقق من الأعمدة المهمة
important_columns = [
    'paypal_client_id',
    'paypal_client_secret',
    'bank_name',
    'stripe_publishable_key'
]

column_names = [col[1] for col in columns]

print('\n✅ التحقق من الأعمدة الجديدة:')
for col_name in important_columns:
    if col_name in column_names:
        print(f'  ✅ {col_name}: موجود')
    else:
        print(f'  ❌ {col_name}: مفقود!')

conn.close()

