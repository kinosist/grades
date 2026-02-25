from django.test import TestCase
from django.urls import reverse
from django.contrib.auth import get_user_model
from school_management.models import ClassRoom, LessonSession, StudentLessonPoints, StudentClassPoints
from datetime import date

User = get_user_model()

class StudentDashboardTest(TestCase):
    def setUp(self):
        """テストデータの準備"""
        # 1. 学生ユーザーの作成 (full_name は必須引数)
        self.student = User.objects.create_user(
            email='student@example.com',
            full_name='生徒 一郎',
            password='password123',
            role='student'
        )
        
        # 2. クラスの作成と所属
        self.classroom = ClassRoom.objects.create(
            class_name="テストクラス",
            year=2026,
            semester=1
        )
        # 学生をクラスに追加（この際、モデル側のロジックでポイントレコードが自動生成される場合がある）
        self.classroom.students.add(self.student)
        
        # 3. 授業セッションの作成
        self.session = LessonSession.objects.create(
            classroom=self.classroom,
            date=date(2026, 2, 23),
            session_number=1,
            has_peer_evaluation=True
        )
        
        # 4. ポイントデータの作成 (UNIQUE制約エラー回避のため update_or_create を使用)
        self.l_point, _ = StudentLessonPoints.objects.update_or_create(
            student=self.student,
            lesson_session=self.session,
            defaults={'points': 5}
        )
        
        # クラスごとのポイント合算データ
        self.c_point, _ = StudentClassPoints.objects.update_or_create(
            student=self.student,
            classroom=self.classroom,
            defaults={'points': 50}
        )
        
        # ログイン用URLとダッシュボードURL
        self.url = reverse('school_management:dashboard')

    def test_student_dashboard_context_data(self):
        """【正常系】データが正しくコンテキストに含まれ、表示されるか"""
        self.client.login(email='student@example.com', password='password123')
        response = self.client.get(self.url)
        
        self.assertEqual(response.status_code, 200)
        
        # クエリセットの内容確認
        self.assertIn(self.classroom, response.context['student_classrooms'])
        self.assertIn(self.session, response.context['recent_sessions'])
        self.assertIn(self.session, response.context['pending_evaluations'])
        self.assertEqual(response.context['total_classes'], 1)
        
        # 取得したポイントの正確性確認
        cp_list = response.context['class_points_list']
        self.assertEqual(cp_list[0]['points'], 10)
        self.assertEqual(cp_list[0]['classroom'], self.classroom)

    def test_student_dashboard_no_data(self):
        """【異常系】クラスに所属していない学生でも404にならず空の状態で表示されるか"""
        User.objects.create_user(
            email='lonely@example.com',
            full_name='未所属生徒',
            password='password123',
            role='student'
        )
        self.client.login(email='lonely@example.com', password='password123')
        response = self.client.get(self.url)
        
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['total_classes'], 0)
        self.assertEqual(len(response.context['class_points_list']), 0)

    def test_student_dashboard_missing_class_points(self):
        """【異常系】ポイントレコードが物理削除されていても、ビュー側で0点として処理されるか"""
        # setUpで作られたポイントレコードをあえて消去
        StudentClassPoints.objects.all().delete()
        
        self.client.login(email='student@example.com', password='password123')
        response = self.client.get(self.url)
        
        # ビューの try-except DoesNotExist ロジックの検証
        cp_list = response.context['class_points_list']
        self.assertEqual(cp_list[0]['points'], 0)
