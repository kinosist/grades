from django.test import TestCase
from django.urls import reverse
from django.contrib.auth import get_user_model
from school_management.models import ClassRoom, LessonSession
from datetime import date, timedelta

User = get_user_model()

class TeacherDashboardFrontendTest(TestCase):
    def setUp(self):
        """テストデータの準備"""
        # 1. 教員ユーザー作成 (StudentがUserモデルを指す場合でも、roleで区別)
        self.teacher = User.objects.create_user(
            email='teacher@example.com',
            full_name='教員 太郎',
            password='password123',
            role='teacher'
        )
        
        # 2. クラス作成と教員の紐付け
        self.classroom = ClassRoom.objects.create(
            class_name="Webプログラミング演習",
            year=2026,
            semester='first' # テンプレートの bg-spring 判定用
        )
        self.classroom.teachers.add(self.teacher)

        # 3. 授業セッション作成
        self.today = date.today()
        self.session_today = LessonSession.objects.create(
            classroom=self.classroom,
            date=self.today,
            session_number=5
        )

        self.url = reverse('school_management:dashboard')

    def test_dashboard_renders_with_correct_context(self):
        """テンプレートに正しいデータが渡され、表示されているか"""
        self.client.login(email='teacher@example.com', password='password123')
        response = self.client.get(self.url)
        
        self.assertEqual(response.status_code, 200)
        
        # テンプレートで使用されている変数の存在確認
        self.assertContains(response, "Webプログラミング演習")
        self.assertContains(response, "第5回")
        
        # 今日の日付バッジが表示されているか
        self.assertContains(response, "今日")
        
        # 統計データ
        self.assertEqual(response.context['total_classes'], 1)
        self.assertIn('daily_sessions', response.context)

    def test_date_navigation_links(self):
        """日付ナビゲーション（前日・翌日）のURLが正しく生成されているか"""
        self.client.login(email='teacher@example.com', password='password123')
        response = self.client.get(self.url)
        
        prev_date_str = (self.today - timedelta(days=1)).strftime('%Y-%m-%d')
        next_date_str = (self.today + timedelta(days=1)).strftime('%Y-%m-%d')
        
        # リンクがHTML内に存在するか
        self.assertContains(response, f"?date={prev_date_str}")
        self.assertContains(response, f"?date={next_date_str}")

    def test_empty_state_display(self):
        """授業がない日の表示（コーヒーアイコンのエリア）が機能するか"""
        self.client.login(email='teacher@example.com', password='password123')
        
        # 授業がないはずの遠い未来を指定
        future_date = "2099-12-31"
        response = self.client.get(self.url, {'date': future_date})
        
        self.assertEqual(response.status_code, 200)
        # テンプレート内の「授業はありません」メッセージ
        self.assertContains(response, "この日の授業はありません")
        # コーヒーアイコン（FontAwesome）のクラスが含まれているか
        self.assertContains(response, "fa-mug-hot")
