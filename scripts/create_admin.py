import os
import pathlib
# change cwd to project root (where manage.py lives)
project_root = pathlib.Path(__file__).resolve().parents[1]
os.chdir(project_root)
os.environ.setdefault('DJANGO_SETTINGS_MODULE','school_project.settings')
import django
django.setup()
from school_management.models import CustomUser

if not CustomUser.objects.filter(email='admin@local').exists():
    CustomUser.objects.create_superuser(email='admin@local', full_name='Admin User', password='adminpass')
    print('created admin@local')
else:
    print('admin@local already exists')
