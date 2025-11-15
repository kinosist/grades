web: python manage.py collectstatic --noinput && python migrate_with_retry.py && python create_admin.py && gunicorn school_project.wsgi --log-file - --timeout 120 --workers 2
