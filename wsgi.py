"""PythonAnywhere WSGI entry point.

Configure in the Web tab:
  WSGI configuration file -> /home/<username>/<repo>/wsgi.py
  Virtualenv             -> /home/<username>/<repo>/venv
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.environ.setdefault("APP_ENV", "production")

from app import create_app  # noqa: E402

application = create_app()
