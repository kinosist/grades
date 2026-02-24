from django.test import TestCase
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages

User = get_user_model()

class AdminTeacherManagementTest(TestCase):
    def setUp(self):
        # 1. 管理者ユーザー
        self.admin_user = User.objects.create_user(
            email='admin@example.com',
            full_name='管理者',
            password='password123',
            role='admin'
        )
        # 2. 一般教員ユーザー
        self.teacher_user = User.objects.create_user(
            email='teacher@example.com',
            full_name='一般教員',
            password='password123',
            role='teacher'
        )
        self.url = reverse('school_management:admin_teacher_management')

    ## --- アクセス権限のテスト ---

    def test_access_denied_for_teacher(self):
        """教員ロールのユーザーはアクセスできず、ダッシュボードへリダイレクトされるか"""
        self.client.login(email='teacher@example.com', password='password123')
        response = self.client.get(self.url)
        
        self.assertRedirects(response, reverse('school_management:dashboard'))
        
        # エラーメッセージの内容確認
        messages = list(get_messages(response.wsgi_request))
        self.assertEqual(str(messages[0]), '管理者のみアクセス可能です。')

    ## --- 表示と追加のテスト ---

    def test_list_and_add_teacher_success(self):
        """管理者が新しい教員を正常に追加できるか"""
        self.client.login(email='admin@example.com', password='password123')
        
        data = {
            'action': 'add_teacher',
            'email': 'new_teacher@example.com',
            'full_name': '新規教員',
            'furigana': 'シンキキョウイン',
            'teacher_id': 'T1001',
            'password': 'newpassword123'
        }
        response = self.client.post(self.url, data)
        
        # 成功後のリダイレクト先確認
        self.assertRedirects(response, self.url)
        
        # DBに教員ロールで作成されているか
        new_user = User.objects.get(email='new_teacher@example.com')
        self.assertEqual(new_user.full_name, '新規教員')
        self.assertEqual(new_user.role, 'teacher')
        self.assertEqual(new_user.teacher_id, 'T1001')

    def test_add_teacher_duplicate_email(self):
        """既に存在するメールアドレスで追加しようとした場合にエラーになるか"""
        self.client.login(email='admin@example.com', password='password123')
        
        data = {
            'action': 'add_teacher',
            'email': 'teacher@example.com', # setupで作成済み
            'full_name': '重複太郎',
            'password': 'password123'
        }
        response = self.client.post(self.url, data)
        
        # DBの数は増えていないはず
        self.assertEqual(User.objects.filter(email='teacher@example.com').count(), 1)
        
        # エラーメッセージの確認
        messages = list(get_messages(response.wsgi_request))
        self.assertIn('既に登録されています', str(messages[0]))

    ## --- 削除のテスト ---

    def test_delete_teacher_success(self):
        """教員を正常に削除できるか"""
        self.client.login(email='admin@example.com', password='password123')
        
        # 削除対象の教員ID（Userモデルのプライマリキー）を送信
        data = {
            'action': 'delete_teacher',
            'teacher_id': self.teacher_user.id
        }
        response = self.client.post(self.url, data)
        
        self.assertRedirects(response, self.url)
        # DBから消えているか
        self.assertFalse(User.objects.filter(id=self.teacher_user.id).exists())

    def test_delete_non_existent_teacher(self):
        """存在しないIDを削除しようとした場合にエラーメッセージが出るか"""
        self.client.login(email='admin@example.com', password='password123')
        
        data = {
            'action': 'delete_teacher',
            'teacher_id': 99999 # 存在しないID
        }
        response = self.client.post(self.url, data)
        
        messages = list(get_messages(response.wsgi_request))
        self.assertEqual(str(messages[0]), '教員が見つかりません。')
