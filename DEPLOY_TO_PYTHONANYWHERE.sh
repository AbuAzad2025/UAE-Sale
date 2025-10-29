#!/bin/bash

echo "======================================"
echo "🚀 نشر النظام على PythonAnywhere"
echo "======================================"

echo ""
echo "1️⃣ الانتقال للمجلد..."
cd ~/UAE-Sale

echo ""
echo "2️⃣ تحديث remote URL (Private Repo)..."
git remote set-url origin git@github.com:AbuAzad2025/UAE-Sale.git

echo ""
echo "3️⃣ إضافة GitHub للـ known hosts..."
ssh-keyscan github.com >> ~/.ssh/known_hosts

echo ""
echo "4️⃣ سحب آخر التحديثات من GitHub (Private Repo)..."
GIT_SSH_COMMAND='ssh -i ~/.ssh/pythonanywhere_deploy -o IdentitiesOnly=yes' git pull origin main

echo ""
echo "5️⃣ تحديث المكتبات..."
pip3.10 install --user -r requirements.txt

echo ""
echo "6️⃣ تطبيق Migrations..."
flask db upgrade

echo ""
echo "7️⃣ إعادة تحميل التطبيق..."
touch /var/www/uaesale-azad_pythonanywhere_com_wsgi.py

echo ""
echo "======================================"
echo "✅ تم النشر بنجاح!"
echo "======================================"
echo ""
echo "🌐 الموقع: https://uaesale-azad.pythonanywhere.com"
echo ""
echo "📊 للفحص:"
echo "tail -30 /var/log/uaesale-azad.pythonanywhere.com.error.log"
echo ""
