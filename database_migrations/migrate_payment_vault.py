"""
Migration Script - Payment Vault
تهجير آمن لجدول payment_vault مع الحفاظ على البيانات
"""
import sqlite3
import os
from datetime import datetime

# مسار قاعدة البيانات
DB_PATH = 'instance/app.db'

def migrate_payment_vault():
    """تهجير آمن لجدول payment_vault"""
    
    if not os.path.exists(DB_PATH):
        print(f'❌ قاعدة البيانات غير موجودة: {DB_PATH}')
        return False
    
    print('🔧 بدء عملية التهجير...')
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    try:
        # 1. التحقق من وجود الجدول
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='payment_vault'")
        table_exists = cursor.fetchone()
        
        if not table_exists:
            print('📋 الجدول غير موجود، سيتم إنشاؤه...')
            # إنشاء الجدول من الصفر
            cursor.execute('''
                CREATE TABLE payment_vault (
                    id INTEGER PRIMARY KEY,
                    vault_password_hash VARCHAR(255) NOT NULL,
                    vault_name VARCHAR(100),
                    is_locked BOOLEAN,
                    last_access DATETIME,
                    nowpayments_api_key VARCHAR(255),
                    nowpayments_ipn_secret VARCHAR(255),
                    bitcoin_address VARCHAR(255),
                    ethereum_address VARCHAR(255),
                    usdt_address VARCHAR(255),
                    paypal_client_id VARCHAR(255),
                    paypal_client_secret VARCHAR(255),
                    paypal_business_email VARCHAR(200),
                    paypal_mode VARCHAR(20),
                    bank_name VARCHAR(200),
                    bank_account_name VARCHAR(200),
                    bank_account_number VARCHAR(100),
                    bank_iban VARCHAR(50),
                    bank_swift_code VARCHAR(20),
                    bank_branch VARCHAR(200),
                    bank_country VARCHAR(100),
                    bank_currency VARCHAR(10),
                    stripe_publishable_key VARCHAR(255),
                    stripe_secret_key VARCHAR(255),
                    stripe_webhook_secret VARCHAR(255),
                    mollie_api_key VARCHAR(255),
                    square_access_token VARCHAR(255),
                    razorpay_key_id VARCHAR(255),
                    razorpay_key_secret VARCHAR(255),
                    min_donation_amount NUMERIC(10, 2),
                    max_donation_amount NUMERIC(10, 2),
                    daily_limit NUMERIC(15, 2),
                    require_2fa BOOLEAN,
                    auto_lock_minutes INTEGER,
                    max_failed_attempts INTEGER,
                    failed_attempts INTEGER,
                    created_at DATETIME,
                    updated_at DATETIME
                )
            ''')
            conn.commit()
            print('✅ تم إنشاء جدول payment_vault بنجاح')
        else:
            print('📋 الجدول موجود، سيتم تحديثه...')
            
            # 2. الحصول على الأعمدة الحالية
            cursor.execute("PRAGMA table_info(payment_vault)")
            existing_columns = {col[1] for col in cursor.fetchall()}
            
            # 3. قائمة الأعمدة الجديدة المطلوبة
            new_columns = {
                'paypal_client_id': 'VARCHAR(255)',
                'paypal_client_secret': 'VARCHAR(255)',
                'paypal_business_email': 'VARCHAR(200)',
                'paypal_mode': 'VARCHAR(20)',
                'bank_name': 'VARCHAR(200)',
                'bank_account_name': 'VARCHAR(200)',
                'bank_account_number': 'VARCHAR(100)',
                'bank_iban': 'VARCHAR(50)',
                'bank_swift_code': 'VARCHAR(20)',
                'bank_branch': 'VARCHAR(200)',
                'bank_country': 'VARCHAR(100)',
                'bank_currency': 'VARCHAR(10)',
                'stripe_publishable_key': 'VARCHAR(255)',
                'stripe_secret_key': 'VARCHAR(255)',
                'stripe_webhook_secret': 'VARCHAR(255)',
                'mollie_api_key': 'VARCHAR(255)',
                'square_access_token': 'VARCHAR(255)',
                'razorpay_key_id': 'VARCHAR(255)',
                'razorpay_key_secret': 'VARCHAR(255)',
            }
            
            # 4. إضافة الأعمدة المفقودة
            added_count = 0
            for col_name, col_type in new_columns.items():
                if col_name not in existing_columns:
                    try:
                        cursor.execute(f'ALTER TABLE payment_vault ADD COLUMN {col_name} {col_type}')
                        print(f'  ✅ تم إضافة عمود: {col_name}')
                        added_count += 1
                    except sqlite3.OperationalError as e:
                        print(f'  ⚠️ تخطي {col_name}: {e}')
                else:
                    print(f'  ℹ️ عمود موجود بالفعل: {col_name}')
            
            conn.commit()
            
            if added_count > 0:
                print(f'\n✅ تم إضافة {added_count} عمود جديد')
            else:
                print('\nℹ️ جميع الأعمدة موجودة بالفعل')
        
        # 5. التحقق النهائي
        cursor.execute("PRAGMA table_info(payment_vault)")
        final_columns = cursor.fetchall()
        
        print(f'\n📊 إجمالي الأعمدة بعد التهجير: {len(final_columns)}')
        
        # التحقق من الأعمدة المهمة
        column_names = {col[1] for col in final_columns}
        required_columns = ['paypal_client_id', 'bank_name', 'stripe_publishable_key']
        
        all_present = all(col in column_names for col in required_columns)
        
        if all_present:
            print('✅ جميع الأعمدة المطلوبة موجودة')
            return True
        else:
            print('⚠️ بعض الأعمدة المطلوبة مفقودة')
            for col in required_columns:
                if col not in column_names:
                    print(f'  ❌ مفقود: {col}')
            return False
            
    except Exception as e:
        print(f'❌ خطأ في التهجير: {str(e)}')
        conn.rollback()
        return False
    
    finally:
        conn.close()


if __name__ == '__main__':
    print('═══════════════════════════════════════════════════════════════')
    print('🔧 تهجير آمن لجدول payment_vault')
    print('═══════════════════════════════════════════════════════════════')
    print(f'📁 قاعدة البيانات: {DB_PATH}')
    print(f'🕒 الوقت: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
    print('───────────────────────────────────────────────────────────────')
    
    success = migrate_payment_vault()
    
    print('───────────────────────────────────────────────────────────────')
    if success:
        print('✅ اكتمل التهجير بنجاح!')
        print('🚀 يمكنك الآن تشغيل النظام')
    else:
        print('❌ فشل التهجير - راجع الأخطاء أعلاه')
    print('═══════════════════════════════════════════════════════════════')

