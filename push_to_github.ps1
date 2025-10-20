# 🚀 سكربت تلقائي لرفع النظام لـ GitHub
# المطور: م. أحمد غنام | شركة أزاد
# الحساب: @AbuAzad2025
# المشروع: UAE-SALE

Write-Host "============================================" -ForegroundColor Cyan
Write-Host "   رفع نظام UAE-SALE لـ GitHub" -ForegroundColor Yellow
Write-Host "   مشروع: نظام مبيعات الإمارات الذكي" -ForegroundColor Green
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""

# التأكد من وجود .git
if (!(Test-Path .git)) {
    Write-Host "❌ خطأ: مجلد .git غير موجود!" -ForegroundColor Red
    Write-Host "ℹ️  تأكد من تشغيل السكربت من مجلد المشروع" -ForegroundColor Yellow
    exit 1
}

# 1. تحديد الفرع الرئيسي
Write-Host "1️⃣  تحديد الفرع الرئيسي (main)..." -ForegroundColor Cyan
git branch -M main
if ($LASTEXITCODE -eq 0) {
    Write-Host "   ✅ تم بنجاح" -ForegroundColor Green
} else {
    Write-Host "   ❌ فشل" -ForegroundColor Red
    exit 1
}
Write-Host ""

# 2. إضافة Remote
Write-Host "2️⃣  ربط بـ GitHub Repository..." -ForegroundColor Cyan
Write-Host "   Repository: https://github.com/AbuAzad2025/UAE-SALE.git" -ForegroundColor Gray

# حذف remote القديم إن وجد
git remote remove origin 2>$null

# إضافة remote جديد
git remote add origin https://github.com/AbuAzad2025/UAE-SALE.git
if ($LASTEXITCODE -eq 0) {
    Write-Host "   ✅ تم الربط بنجاح" -ForegroundColor Green
} else {
    Write-Host "   ❌ فشل الربط" -ForegroundColor Red
    exit 1
}
Write-Host ""

# 3. Push
Write-Host "3️⃣  رفع الملفات لـ GitHub..." -ForegroundColor Cyan
Write-Host "   ⚠️  سيطلب منك:" -ForegroundColor Yellow
Write-Host "      Username: AbuAzad2025" -ForegroundColor White
Write-Host "      Password: [الصق الـ Personal Access Token]" -ForegroundColor White
Write-Host ""

git push -u origin main

if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "============================================" -ForegroundColor Green
    Write-Host "   🎉 تم الرفع بنجاح!" -ForegroundColor Green
    Write-Host "============================================" -ForegroundColor Green
    Write-Host ""
    Write-Host "افتح المشروع على:" -ForegroundColor Cyan
    Write-Host "https://github.com/AbuAzad2025/UAE-SALE" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "المحتوى:" -ForegroundColor Cyan
    Write-Host "✅ 2000+ ملف" -ForegroundColor Green
    Write-Host "✅ نظام ذكاء اصطناعي متكامل" -ForegroundColor Green
    Write-Host "✅ 47 ملف معرفة" -ForegroundColor Green
    Write-Host "✅ README احترافي" -ForegroundColor Green
    Write-Host ""
} else {
    Write-Host ""
    Write-Host "============================================" -ForegroundColor Red
    Write-Host "   ❌ حدث خطأ في الرفع" -ForegroundColor Red
    Write-Host "============================================" -ForegroundColor Red
    Write-Host ""
    Write-Host "الأسباب المحتملة:" -ForegroundColor Yellow
    Write-Host "1. Repository غير موجود - أنشئه أولاً:" -ForegroundColor White
    Write-Host "   https://github.com/new" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "2. Personal Access Token خاطئ - احصل على واحد جديد:" -ForegroundColor White
    Write-Host "   https://github.com/settings/tokens" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "3. مشكلة اتصال - تحقق من الإنترنت" -ForegroundColor White
    Write-Host ""
    Write-Host "راجع PUSH_NOW.md للتفاصيل" -ForegroundColor Yellow
    exit 1
}

Write-Host "المطور: م. أحمد غنام | شركة أزاد 🇵🇸" -ForegroundColor Magenta
Write-Host ""

