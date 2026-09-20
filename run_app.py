import os
import logging

# Set environment variables
os.environ['DEBUG'] = 'true'
os.environ['APP_ENV'] = 'development'
os.environ['SECRET_KEY'] = 'test-secret-key'
os.environ['CARD_ENCRYPTION_KEY'] = 'test-card-enc-key'
os.environ['OWNER_PASSWORD'] = 'test-owner-password'
os.environ['PORT'] = '8001'
os.environ['HOST'] = '127.0.0.1'
os.environ['SQLALCHEMY_DATABASE_URI'] = 'postgresql://postgres:123@localhost:5432/uae_sale_8001'

# Try to create database first
try:
    import subprocess
    subprocess.run(['psql', '-h', 'localhost', '-U', 'postgres', '-c', 'CREATE DATABASE uae_sale_8001;'], check=False, capture_output=True)
    print("Database uae_sale_8001 created or already exists")
except Exception as e:
    print(f"Database creation warning: {e}")

# Now run the app
try:
    from app import create_app
    app = create_app()
    print('App created successfully!')
    
    # Run the app
    app.run(
        host=os.environ['HOST'],
        port=int(os.environ['PORT']),
        debug=os.environ.get('DEBUG', 'false').lower() in ('true', '1', 'yes'),
        use_reloader=False
    )
except Exception as e:
    print(f'Error: {e}')
    import traceback
    traceback.print_exc()