from django.test import TestCase, Client
from django.urls import reverse
from school_management.models import CustomUser, ClassRoom, StudentClassPoints

class DashboardViewTest(TestCase):
    def setUp(self):
        self.teacher = CustomUser.objects.create_user(email='t@example.com', full_name='T', password='tpass', role='teacher')
        self.student = CustomUser.objects.create_user(email='s@example.com', full_name='S', password='spass', role='student', student_number='S1')
        self.classroom = ClassRoom.objects.create(class_name='C1', year=2025, semester='first')
        self.classroom.teachers.add(self.teacher)
        self.classroom.students.add(self.student)
        # クラスポイントを0で初期化
        StudentClassPoints.objects.get_or_create(
            student=self.student,
            classroom=self.classroom,
            defaults={'points': 0}
        )
        self.client = Client()

    def test_teacher_dashboard(self):
        self.client.force_login(self.teacher)
        resp = self.client.get(reverse('school_management:dashboard'))
        # Expect redirect to teacher dashboard
        self.assertIn(resp.status_code, (200, 302))

    def test_student_dashboard(self):
        self.client.force_login(self.student)
        resp = self.client.get(reverse('school_management:dashboard'))
        self.assertIn(resp.status_code, (200, 302))
