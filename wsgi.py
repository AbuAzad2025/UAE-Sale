import sys
import os

# أضف مسار المشروع إلى مسار بايثون
project_home = '/home/username/mysite'
if project_home not in sys.path:
    sys.path = [project_home] + sys.path

# تعيين متغيرات البيئة (يمكنك أيضاً تعيينها في لوحة تحكم PythonAnywhere)
# os.environ['FLASK_APP'] = 'app.py'
# os.environ['FLASK_ENV'] = 'production'

# استيراد التطبيق
from app import create_app

# إنشاء التطبيق
application = create_app()
