from django.test import TestCase
from django.urls import reverse
from django.contrib.auth import get_user_model
from school_management.models import ClassRoom, LessonSession, StudentClassPoints
from datetime import date

User = get_user_model()

class ClassDetailViewTest(TestCase):
    def setUp(self):
        # 1. 教員ユーザー作成
        self.teacher = User.objects.create_user(
            email='teacher@example.com',
            full_name='教員 太郎',
            password='password123'
        )
        self.other_teacher = User.objects.create_user(
            email='other@example.com',
            full_name='他教員',
            password='password123'
        )
        
        # 2. 学生ユーザー作成 (student_number を追加！)
        # ※ もし User モデルに直接 student_number がない場合は、
        # ※ 適切なプロフィールモデル等に合わせて書き換えてください。
        self.student = User.objects.create_user(
            email='student1@example.com',
            full_name='生徒 一郎',
            password='password123',
            student_number='S2026001'
        )
        
        # 3. ClassRoom作成
        self.classroom = ClassRoom.objects.create(
            class_name="Pythonクラス",
            year=2026,
            semester=1
        )
        self.classroom.teachers.add(self.teacher)
        self.classroom.students.add(self.student)
        
        # 4. 授業セッション作成
        self.session = LessonSession.objects.create(
            classroom=self.classroom, 
            date=date(2026, 2, 22),
            session_number=1
        )
        
        # 5. ポイントデータ作成
        self.point = StudentClassPoints.objects.create(
            classroom=self.classroom, 
            student=self.student, 
            points=10
        )
        
        self.url = reverse('school_management:class_detail', kwargs={'class_id': self.classroom.id})

    def test_login_required(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)

    def test_access_denied_for_non_teacher(self):
        self.client.login(email='other@example.com', password='password123')
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 404)

    def test_class_detail_success(self):
        self.client.login(email='teacher@example.com', password='password123')
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        
        lessons = response.context.get('lessons') or response.context.get('sessions')
        self.assertIn(self.session, lessons)
        
        students_in_context = response.context['students']
        target_student = next(s for s in students_in_context if s.id == self.student.id)
        self.assertTrue(hasattr(target_student, 'class_point'))

    def test_template_used(self):
        self.client.login(email='teacher@example.com', password='password123')
        response = self.client.get(self.url)
        self.assertTemplateUsed(response, 'school_management/class_detail.html')
