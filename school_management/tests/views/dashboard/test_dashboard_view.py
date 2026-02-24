from django.test import TestCase
from django.urls import reverse
from django.contrib.auth import get_user_model

User = get_user_model()

class DashboardDispatchTest(TestCase):
    def setUp(self):
        # 全ユーザーに必須の full_name を追加
        self.admin_user = User.objects.create_user(
            email='admin@example.com',
            full_name='管理者',
            password='password123',
            role='admin'
        )
        self.teacher_user = User.objects.create_user(
            email='teacher@example.com',
            full_name='教員太郎',
            password='password123',
            role='teacher'
        )
        self.student_user = User.objects.create_user(
            email='student@example.com',
            full_name='生徒一郎',
            password='password123',
            role='student'
        )
        
        self.dashboard_url = reverse('school_management:dashboard')

    def test_admin_redirects_to_teacher_management(self):
        """管理者は教員管理ページにリダイレクトされるか"""
        self.client.login(email='admin@example.com', password='password123')
        response = self.client.get(self.dashboard_url)
        self.assertRedirects(response, reverse('school_management:admin_teacher_management'))

    def test_teacher_accesses_teacher_dashboard(self):
        """教員は teacher_dashboard の内容が表示されるか"""
        self.client.login(email='teacher@example.com', password='password123')
        response = self.client.get(self.dashboard_url)
        self.assertEqual(response.status_code, 200)

    def test_student_accesses_student_dashboard(self):
        """生徒は student_dashboard の内容が表示されるか"""
        self.client.login(email='student@example.com', password='password123')
        response = self.client.get(self.dashboard_url)
        self.assertEqual(response.status_code, 200)

    def test_login_required_for_dashboard(self):
        """未ログインならログインページへリダイレクト"""
        response = self.client.get(self.dashboard_url)
        self.assertEqual(response.status_code, 302)
