$env:FLASK_ENV = 'development'
$env:DEBUG = '1'
$env:SECRET_KEY = 'dev-test-secret-key-2026'
$env:CARD_ENCRYPTION_KEY = 'card-encryption-key-2026'
$env:OWNER_PASSWORD = 'TestOwner@1983@yyyy!'
$env:OWNER_USERNAME = 'owner'
$env:DATABASE_URL = 'postgresql://postgres:123@localhost:5432/uae_sale_dev'
$env:SQLALCHEMY_DATABASE_URI = 'postgresql://postgres:123@localhost:5432/uae_sale_dev'
$env:CACHE_TYPE = 'SimpleCache'
$env:RATELIMIT_STORAGE_URI = 'memory://'
$env:RATELIMIT_ENABLED = 'false'
$env:MASTER_KEY_SEED = 'Azad@1983'
$env:PORT = '8000'
$env:HOST = '0.0.0.0'

$today = Get-Date -Format 'yyyy@MM@dd'
$masterKey = "Azad@1983@$today"

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  UAE-Sale ERP - DEV SERVER" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Server:    http://localhost:8000" -ForegroundColor Green
Write-Host "Landing:   http://localhost:8000/" -ForegroundColor Green
Write-Host "Login:     http://localhost:8000/auth/login" -ForegroundColor Green
Write-Host ""
Write-Host "Owner account (auto-created on first run):" -ForegroundColor Yellow
Write-Host "  Username: owner" -ForegroundColor White
Write-Host "  Password: TestOwner@1983@yyyy!" -ForegroundColor White
Write-Host "  OR daily master key: $masterKey" -ForegroundColor Magenta
Write-Host ""
Write-Host "Press Ctrl+C to stop" -ForegroundColor Gray
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

python app.py
