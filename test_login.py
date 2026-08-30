#!/usr/bin/env python
"""
ログインテスト用スクリプト
"""
import django
import os

# Django設定
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'school_project.settings')
django.setup()

from django.test import Client
from django.contrib.auth import get_user_model

def ensure_test_user():
    """テスト用ログインユーザーを用意する"""
    User = get_user_model()
    user = User.objects.filter(email='admin@test.com').first()
    if user:
        if not user.is_teacher:
            user.role = 'teacher'
            user.save(update_fields=['role'])
        return user

    return User.objects.create_user(
        email='admin@test.com',
        full_name='Test Admin',
        password='admin123',
        role='teacher',
        is_staff=True,
    )


def test_student_create_access():
    """学生作成ページへのアクセステスト"""
    client = Client()
    
    # ログイン前のアクセス
    print("=== ログイン前のアクセス ===")
    response = client.get('/students/create/')
    print(f"Status Code: {response.status_code}")
    print(f"Location: {response.get('Location', 'なし')}")
    
    # ログイン
    print("\n=== ログイン ===")
    user = ensure_test_user()
    client.force_login(user)
    print("ログイン成功（テストユーザー準備済み）")
    
    # ログイン後のアクセス
    print("\n=== ログイン後のアクセス ===")
    response = client.get('/students/create/')
    print(f"Status Code: {response.status_code}")
    print(f"Content Length: {len(response.content)}")
    
    if response.status_code == 200:
        content = response.content.decode('utf-8')
        if '学生登録' in content:
            print("学生登録ページが正しく表示されています")
        else:
            print("警告: 学生登録ページの内容が見つかりません")
            print("最初の500文字:", content[:500])
    else:
        print(f"エラー: 期待されない応答 {response.status_code}")

if __name__ == '__main__':
    test_student_create_access()
