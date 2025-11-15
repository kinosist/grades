"""
Railwayデプロイ時に管理者ユーザーを自動作成するスクリプト
環境変数でメールアドレスとパスワードを指定
"""
import os
import sys
import time
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'school_project.settings')
django.setup()

from school_management.models import CustomUser
from django.db import connection

def create_admin_with_retry(max_retries=3, delay=2):
    """Create admin user with retry logic"""
    # 環境変数から管理者情報を取得
    ADMIN_EMAIL = os.environ.get('ADMIN_EMAIL', 'admin@example.com')
    ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'admin123')
    ADMIN_NAME = os.environ.get('ADMIN_NAME', '管理者')

    for attempt in range(max_retries):
        try:
            print(f"Checking database connection (attempt {attempt + 1}/{max_retries})...")
            connection.ensure_connection()
            print("Database connection successful!")

            # 既に存在する場合はスキップ
            if not CustomUser.objects.filter(email=ADMIN_EMAIL).exists():
                CustomUser.objects.create_superuser(
                    email=ADMIN_EMAIL,
                    full_name=ADMIN_NAME,
                    password=ADMIN_PASSWORD
                )
                print(f"✅ 管理者ユーザーを作成しました: {ADMIN_EMAIL}")
            else:
                print(f"ℹ️  管理者ユーザーは既に存在します: {ADMIN_EMAIL}")
            return True

        except Exception as e:
            print(f"Attempt {attempt + 1} failed: {e}")
            if attempt < max_retries - 1:
                print(f"Retrying in {delay} seconds...")
                time.sleep(delay)
                try:
                    connection.close()
                except:
                    pass
            else:
                print(f"All {max_retries} attempts failed!")
                return False

    return False

if __name__ == '__main__':
    try:
        success = create_admin_with_retry()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"Fatal error: {e}")
        sys.exit(1)
