#!/bin/bash
set -e

echo "=========================================="
echo "Starting Railway Deployment"
echo "=========================================="
echo "Time: $(date)"
echo ""

echo "Step 1: Running database migrations..."
if python migrate_with_retry.py; then
    echo "✅ Migrations completed successfully"
else
    echo "❌ Migrations failed"
    exit 1
fi
echo ""

echo "Step 2: Creating admin user..."
if python create_admin.py; then
    echo "✅ Admin user setup completed"
else
    echo "⚠️  Admin user setup failed (continuing anyway)"
fi
echo ""

echo "Step 3: Starting Gunicorn server..."
echo "Port: $PORT"
echo "Workers: 2"
echo "Timeout: 120s"
echo ""

exec gunicorn school_project.wsgi \
    --bind 0.0.0.0:$PORT \
    --workers 2 \
    --timeout 120 \
    --log-file - \
    --access-logfile - \
    --error-logfile - \
    --log-level info \
    --capture-output
