from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages

# カスタムユーザーモデルを取得
User = get_user_model()

class LogoutViewTest(TestCase):
    def setUp(self):
        """テストの準備"""
        self.client = Client()
        self.logout_url = reverse('school_management:logout')
        self.login_url = reverse('school_management:login')
        self.password = 'testpassword123'

        #テスト用ユーザーの作成
        self.user = User.objects.create_user(
            email='testuser@example.com',
            password=self.password,
            full_name='テスト 太郎',
            role='student'
        )

    def test_logout_functionality(self):
        """ログアウト機能が正しく動作するかテスト"""
        # 1. まずテスト用ユーザーをログインさせる
        self.client.login(email=self.user.email, password=self.password)

        # （確認）セッションにユーザーIDがあり、ログイン状態であることを確認
        self.assertIn('_auth_user_id', self.client.session)

        # 2. ログアウトURLにアクセス（GETリクエスト)
        response = self.client.get(self.logout_url)

        # 3. ログイン画面に正しくリダイレクトされるか確認
        self.assertRedirects(response, self.login_url)

        # 4. セッションからユーザー情報が消え、ログアウト状態になったか確認
        self.assertNotIn('_auth_user_id', self.client.session)

        # 5. 「ログアウトしました。」のメッセージが正しくセットされているか確認
        messages = list(get_messages(response.wsgi_request))
        self.assertEqual(len(messages), 1)
        self.assertEqual(str(messages[0]), 'ログアウトしました。')