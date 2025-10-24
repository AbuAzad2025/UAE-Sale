#!/bin/bash
# سكريبت تهجير قاعدة البيانات - آمن للاستخدام على PythonAnywhere

echo "═══════════════════════════════════════════════════════════════"
echo "🔧 تهجير قاعدة بيانات UAE-Sale"
echo "═══════════════════════════════════════════════════════════════"

# 1. نسخة احتياطية
echo "📦 إنشاء نسخة احتياطية..."
BACKUP_FILE="instance/garage.db.backup_$(date +%Y%m%d_%H%M%S)"
cp instance/garage.db "$BACKUP_FILE"
echo "✅ تم الحفظ في: $BACKUP_FILE"

# 2. تشغيل التهجير
echo ""
echo "🔄 تشغيل التهجير..."
python database_migrations/migrate_payment_vault.py

# 3. فحص النتيجة
echo ""
echo "🔍 فحص قاعدة البيانات..."
python database_migrations/check_db.py

# 4. إعادة تحميل التطبيق
echo ""
echo "🔄 إعادة تحميل التطبيق..."
touch /var/www/uaesale_azad_pythonanywhere_com_wsgi.py

echo ""
echo "═══════════════════════════════════════════════════════════════"
echo "✅ اكتمل التهجير بنجاح!"
echo "═══════════════════════════════════════════════════════════════"

