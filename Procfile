web: python migrate_with_retry.py && python create_admin.py && gunicorn school_project.wsgi --bind 0.0.0.0:$PORT --log-file - --timeout 120 --workers 2 --access-logfile - --error-logfile -
