# Quick installation script for UAE-Sale
# Uses pre-built wheels to avoid compilation errors

Write-Host "Installing UAE-Sale dependencies..." -ForegroundColor Cyan
Write-Host "Using pre-built wheels for Windows..." -ForegroundColor Yellow

# Install numpy first (required by others)
pip install numpy

# Install scipy and scikit-learn (use --only-binary to force wheels)
pip install --only-binary :all: scipy scikit-learn pandas

# Install Flask and extensions
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
Flask-Compress==1.14

# Install form handling
pip install WTForms==3.1.1 email-validator==2.1.0

# Install database
pip install SQLAlchemy==2.0.23 alembic==1.13.0

# Install utilities
pip install `
python-dotenv==1.0.0 `
Werkzeug==3.0.1 `
requests==2.31.0 `
cryptography `
Pillow `
qrcode==7.4.2 `
openpyxl==3.1.2 `
reportlab==4.0.7 `
colorama==0.4.6

# Install background tasks
pip install redis==5.0.1 celery==5.3.4 gunicorn==21.2.0

# Install ML libraries
pip install joblib==1.3.2

Write-Host "✓ Installation complete!" -ForegroundColor Green
Write-Host "✓ All dependencies installed successfully" -ForegroundColor Green
Write-Host ""
Write-Host "Next step: python app.py" -ForegroundColor Yellow

