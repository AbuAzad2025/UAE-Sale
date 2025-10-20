# WSGI Configuration for PythonAnywhere
# Path on PythonAnywhere: /var/www/uaesale-azad_pythonanywhere_com_wsgi.py

import sys
import os
from pathlib import Path

# Add your project directory to the sys.path
project_home = '/home/Azad/UAE-Sale'
if project_home not in sys.path:
    sys.path.insert(0, project_home)

# Set environment to production
os.environ['FLASK_ENV'] = 'production'
os.environ['APP_ENV'] = 'production'
os.environ['DEBUG'] = 'False'

# Load environment variables from .env file
from dotenv import load_dotenv
dotenv_path = os.path.join(project_home, '.env')
if os.path.exists(dotenv_path):
    load_dotenv(dotenv_path)

# Import your Flask app
from app import create_app

# Create the application instance
application = create_app()

# This is required by PythonAnywhere
app = application

if __name__ == '__main__':
    application.run()

