from django.http import JsonResponse
from django.db import connection

def health_check(request):
    """Health check endpoint for Railway deployment"""
    try:
        # DB接続確認
        connection.ensure_connection()
        return JsonResponse({'status': 'healthy', 'database': 'connected'}, status=200)
    except Exception as e:
        return JsonResponse({'status': 'unhealthy', 'error': str(e)}, status=503)