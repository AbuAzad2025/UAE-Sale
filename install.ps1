# Quick installation script for UAE-Sale
# Excludes PostgreSQL and MySQL drivers (not needed for SQLite)

Write-Host "Installing UAE-Sale dependencies..." -ForegroundColor Cyan

pip install `
Flask==3.0.0 `
Flask-SQLAlchemy==3.1.1 `
Flask-Migrate==4.0.5 `
Flask-Login==0.6.3 `
Flask-WTF==1.2.1 `
Flask-Mail==0.9.1 `
Flask-Caching==2.1.0 `
Flask-Limiter==3.5.0 `
Flask-CORS==4.0.0 `
Flask-Babel==4.0.0 `
Flask-Compress==1.14 `
WTForms==3.1.1 `
email-validator==2.1.0 `
SQLAlchemy==2.0.23 `
alembic==1.13.0 `
python-dotenv==1.0.0 `
Werkzeug==3.0.1 `
requests==2.31.0 `
cryptography==41.0.7 `
Pillow==10.1.0 `
qrcode==7.4.2 `
openpyxl==3.1.2 `
reportlab==4.0.7 `
colorama==0.4.6 `
redis==5.0.1 `
celery==5.3.4 `
gunicorn==21.2.0 `
scikit-learn==1.3.2 `
numpy==1.26.2 `
pandas==2.1.4 `
joblib==1.3.2 `
scipy==1.11.4

Write-Host "✓ Installation complete!" -ForegroundColor Green
Write-Host "Run: python app.py" -ForegroundColor Yellow

