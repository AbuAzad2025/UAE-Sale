import os
os.environ['PYTHONIOENCODING'] = 'utf-8'
os.environ['DATABASE_URL'] = 'postgresql+psycopg2://postgres:postgres@127.0.0.1:5432/uae_sale_test'
os.environ['SECRET_KEY'] = 'test'
os.environ['OWNER_PASSWORD'] = 'TestOwner1234567890123456'
os.environ['PYTHONPATH'] = r'D:\recovers\data\UAE-Sale'

from wsgi import application
from waitress import serve

serve(application, host='0.0.0.0', port=8001, threads=4)