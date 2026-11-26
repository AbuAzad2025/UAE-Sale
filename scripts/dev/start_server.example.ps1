# Local development launcher (example).
# Copy to start_server.local.ps1 and fill in your own values.
# start_server.local.ps1 is gitignored and must never be committed.

$env:FLASK_ENV = 'development'
$env:DEBUG = '1'

# Load real secrets from your own .env / environment before starting the app.
# Example:
#   $env:SECRET_KEY = '<your-local-secret>'
#   $env:MASTER_KEY_SEED = '<your-local-master-key>'
#   $env:OWNER_PASSWORD = '<your-local-owner-password>'
#   $env:DATABASE_URL = 'postgresql://<user>:<password>@localhost:5432/<db>'

$env:CACHE_TYPE = 'SimpleCache'
$env:RATELIMIT_STORAGE_URI = 'memory://'
$env:RATELIMIT_ENABLED = 'false'

python -m flask run --host=127.0.0.1 --port=5000
