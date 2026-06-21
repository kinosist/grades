import json
from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from school_management.models import ClassRoom, StudentClassPoints

User = get_user_model()

class AuthAndDashboardIntegrationTests(TestCase):
    def setUp(self):
        self.client = Client()
        
        # 教員作成
        self.teacher = User.objects.create_user(
            email='teacher_int@example.com',
            password='password123',
            full_name='Teacher Int',
            role='teacher'
        )
        
        # 学生作成
        self.student = User.objects.create_user(
            email='student_int@example.com',
            password='password123',
            full_name='Student Int',
            role='student',
            student_number='INT001'
        )
        
        # クラス作成
        self.classroom = ClassRoom.objects.create(
            class_name='Integration Class',
            year=2024,
            semester='first'
        )
        self.classroom.teachers.add(self.teacher)
        self.classroom.students.add(self.student)
        
        # 学生のクラスポイントレコード初期化
        StudentClassPoints.objects.create(
            student=self.student,
            classroom=self.classroom
        )

    def test_teacher_login_and_dashboard(self):
        # 1. 未ログインアクセス -> ログインへリダイレクト
        response = self.client.get(reverse('school_management:dashboard'))
        self.assertRedirects(response, f"{reverse('school_management:login')}?next={reverse('school_management:dashboard')}")
        
        # 2. 教員としてログイン
        logged_in = self.client.login(email='teacher_int@example.com', password='password123')
        self.assertTrue(logged_in)
        
        # 3. ダッシュボードにアクセスし、担当クラスが表示されているか確認
        response = self.client.get(reverse('school_management:dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Integration Class')
        
        # 学生用ダッシュボードにアクセスした場合も200で表示される（現在の仕様）
        response = self.client.get(reverse('school_management:student_dashboard'))
        self.assertEqual(response.status_code, 200)

    def test_student_login_and_dashboard(self):
        # 1. 学生としてログイン
        logged_in = self.client.login(email='student_int@example.com', password='password123')
        self.assertTrue(logged_in)
        
        # 2. 学生ダッシュボードで自分のクラスが表示されるか（ダッシュボードルート）
        response = self.client.get(reverse('school_management:dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Integration Class')
        
        # 3. 学生ダッシュボードへの直接アクセス
        response = self.client.get(reverse('school_management:student_dashboard'))
        self.assertEqual(response.status_code, 200)
