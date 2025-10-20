# 🚀 Push سريع لـ GitHub
# الاستخدام: .\push.ps1

Write-Host "🚀 جاري الرفع..." -ForegroundColor Cyan

# إضافة كل التغييرات
git add -A

# Commit
git commit -m "update"

# Push
git push origin HEAD

Write-Host "✅ تم الرفع بنجاح!" -ForegroundColor Green

