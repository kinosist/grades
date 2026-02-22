from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages

# カスタムユーザーモデルを取得
User = get_user_model()

class LoginViewTest(TestCase):
    def setUp(self):
        """テストの実行前に毎回呼ばれる準備処理"""
        self.client = Client()
        # urls.py の設定に合わせて名前は変更してください（例: 'school_management:login'）
        self.login_url = reverse('school_management:login') 
        self.password = 'testpassword123'

        # 1. 管理者(Admin)ユーザーの作成
        self.admin_user = User.objects.create_user(
            email='admin@example.com',
            password=self.password,
            full_name='管理者 太郎',
            role='admin'
        )

        # 2. 教員(Teacher)ユーザーの作成
        self.teacher_user = User.objects.create_user(
            email='teacher@example.com',
            password=self.password,
            full_name='教員 花子',
            role='teacher'
        )

        # 3. 生徒(Student)ユーザーの作成
        self.student_user = User.objects.create_user(
            email='student@example.com',
            password=self.password,
            full_name='生徒 一郎',
            role='student'
        )
    # --- GETリクエストのテスト ---
    def test_login_page_loads_correctly(self):
        """GETリクエストでログイン画面が正常に表示されるか"""
        response = self.client.get(self.login_url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'school_management/login_temp.html')

    # --- POSTリクエスト（正常系・権限ごとのリダイレクト）のテスト ---
    def test_login_admin_redirect(self):
        """管理者権限でログインした場合、管理者画面へリダイレクトされるか"""
        response = self.client.post(self.login_url, {
            'email': self.admin_user.email,
            'password': self.password
        })
        # ログイン成功後、指定のURLにリダイレクトされることを確認
        self.assertRedirects(response, reverse('school_management:admin_teacher_management'))
    def test_login_teacher_redirect(self):
        """生徒権限でログインした場合、生徒用ダッシュボードへリダイレクトされるか"""
        response = self.client.post(self.login_url, {
            'email': self.student_user.email,
            'password': self.password
        })
        self.assertRedirects(response, reverse('school_management:student_dashboard'))
        # --- セッション（Remember me）のテスト ---
    def test_login_without_remember_me(self):
        """「ログインしたままにする」がない場合、ブラウザ終了時にセッションが切れる設定になるか"""
        self.client.post(self.login_url, {
            'email': self.student_user.email,
            'password': self.password
            # 'remember' は送信しない
        })
        # セッションの有効期限が0（ブラウザ終了時）になっているか確認
        self.assertEqual(self.client.session.get_expire_at_browser_close(), True)

    # --- POSTリクエスト（異常系）のテスト ---
    def test_login_failure_wrong_password(self):
        """間違ったパスワードを入力した場合、ログインできずにエラーメッセージが出るか"""
        response = self.client.post(self.login_url, {
            'email': self.student_user.email,
            'password': 'wrongpassword'
        })
        
        # ログイン画面が再表示される（リダイレクトされないので200）
        self.assertEqual(response.status_code, 200)
        
        # エラーメッセージが正しくセットされているか確認
        messages = list(get_messages(response.wsgi_request))
        self.assertEqual(len(messages), 1)
        self.assertEqual(str(messages[0]), 'メールアドレスまたはパスワードが正しくありません。')