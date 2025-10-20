# 🚀 Push سريع لـ GitHub
# المشروع: https://github.com/AbuAzad2025/UAE-Sale
# الاستخدام: .\push.ps1

Write-Host "🚀 جاري الرفع لـ UAE-Sale..." -ForegroundColor Cyan

# إضافة كل التغييرات
git add -A

# Commit
git commit -m "update"

# Push
git push origin HEAD

Write-Host "✅ تم الرفع بنجاح!" -ForegroundColor Green
Write-Host "🔗 https://github.com/AbuAzad2025/UAE-Sale" -ForegroundColor Yellow

