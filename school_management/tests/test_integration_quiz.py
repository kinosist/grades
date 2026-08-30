from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from school_management.models import (
    ClassRoom, LessonSession, Quiz, QuizScore, ClassRoomEnrollment
)

User = get_user_model()

class QuizIntegrationTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.teacher = User.objects.create_user(
            email='teacher_qz@example.com',
            password='password123',
            full_name='Teacher QZ',
            role='teacher'
        )
        self.student = User.objects.create_user(
            email='student_qz@example.com',
            password='password123',
            full_name='Student QZ',
            role='student',
            student_number='QZ001'
        )
        self.classroom = ClassRoom.objects.create(
            class_name='Quiz Class',
            year=2024,
            semester='first'
        )
        self.classroom.teachers.add(self.teacher)
        ClassRoomEnrollment.enroll(self.classroom, self.student)
        
        self.session = LessonSession.objects.create(
            classroom=self.classroom,
            session_number=1,
            has_quiz=True
        )

    def test_quiz_full_flow(self):
        # 1. 教員としてログイン
        self.client.login(email='teacher_qz@example.com', password='password123')
        
        # 2. 小テストの作成
        create_url = reverse('school_management:quiz_create', args=[self.session.id])
        response = self.client.post(create_url, {
            'quiz_name': 'Midterm Quiz',
            'max_score': 100,
            'grading_method': 'numeric'
        })
        self.assertIn(response.status_code, [200, 302])
        
        # 作成されたか確認
        quiz = Quiz.objects.filter(lesson_session=self.session).order_by('-id').first()
        self.assertIsNotNone(quiz)
        if quiz.quiz_name != 'Midterm Quiz':
            print("Found quiz name:", quiz.quiz_name)
        self.assertEqual(quiz.quiz_name, 'Midterm Quiz')
        # 3. 採点（教員が学生の点数を入力）
        grading_url = reverse('school_management:quiz_grading', args=[quiz.id])
        response = self.client.post(grading_url, {
            'action': 'save_scores',
            f'score_{self.student.student_number}': '85'
        })
        self.assertIn(response.status_code, [200, 302])
        
        # 採点結果が保存されたか
        score = QuizScore.objects.filter(quiz=quiz, student=self.student).first()
        self.assertIsNotNone(score)
        self.assertEqual(score.score, 85)
