from django.test import TestCase
from django.db import IntegrityError
from school_management.models import (
    CustomUser,
    ClassRoom,
    ClassRoomEnrollment,
    LessonSession,
    StudentLessonPoints,
    Group,
    GroupMember,
    PeerEvaluationSettings,
    Student
)
from datetime import date

class ModelsTestCase(TestCase):
    def setUp(self):
        # Users
        self.teacher = CustomUser.objects.create_user(
            email='teacher_model@example.com',
            full_name='Teacher Model',
            password='pass',
            role='teacher'
        )
        self.student = CustomUser.objects.create_user(
            email='student_model@example.com',
            full_name='Student Model',
            password='pass',
            role='student',
            student_number='S123'
        )
        
        # Classroom
        self.classroom = ClassRoom.objects.create(
            class_name='Model Test Class',
            year=2026,
            semester='first'
        )
        self.classroom.teachers.add(self.teacher)
        ClassRoomEnrollment.enroll(self.classroom, self.student)
        
        # Lesson Session
        self.session = LessonSession.objects.create(
            classroom=self.classroom,
            session_number=1,
            topic='Model testing session',
            date=date.today(),
            has_peer_evaluation=True
        )

    def test_custom_user_manager_create_superuser(self):
        # Create a superuser
        admin = CustomUser.objects.create_superuser(
            email='admin@example.com',
            full_name='Admin Test',
            password='adminpass'
        )
        self.assertTrue(admin.is_superuser)
        self.assertTrue(admin.is_staff)
        self.assertEqual(admin.role, 'admin')

    def test_custom_user_manager_create_superuser_missing_is_staff(self):
        with self.assertRaises(ValueError):
            CustomUser.objects.create_superuser(
                email='admin2@example.com',
                full_name='Admin2 Test',
                password='adminpass',
                is_staff=False
            )

    def test_custom_user_manager_create_superuser_missing_is_superuser(self):
        with self.assertRaises(ValueError):
            CustomUser.objects.create_superuser(
                email='admin3@example.com',
                full_name='Admin3 Test',
                password='adminpass',
                is_superuser=False
            )

    def test_models_str_methods(self):
        self.assertEqual(str(self.teacher), "Teacher Model")
        self.assertEqual(str(self.student), "Student Model")
        self.assertIn("Model Test Class", str(self.classroom))

    def test_student_class_points_calculate_internal(self):
        from school_management.models import StudentClassPoints
        # Testing calculate_points_internal
        scp = StudentClassPoints.objects.create(
            student=self.student,
            classroom=self.classroom,
            points=0,
            attendance_points=5.0
        )
        scp.calculate_points_internal()
        scp.refresh_from_db()
        self.assertEqual(scp.points, 5)

    def test_student_model_is_teacher_and_is_student_properties(self):
        self.assertTrue(self.teacher.is_teacher)
        self.assertFalse(self.teacher.is_student)
        self.assertTrue(self.student.is_student)
        self.assertFalse(self.student.is_teacher)

    def test_get_activity_points_boundary_values(self):
        from school_management.models import StudentClassPoints, StudentColumnScore, PointColumn, Quiz, QuizScore, StudentLessonPoints
        
        # 1. No records (equivalent to None aggregations)
        scp = StudentClassPoints.objects.create(
            student=self.student,
            classroom=self.classroom,
            points=0,
            attendance_points=5.0
        )
        self.assertEqual(scp.get_activity_points(), 0)

        # Create components
        column = PointColumn.objects.create(classroom=self.classroom, column_title="Test Column")
        quiz = Quiz.objects.create(lesson_session=self.session, quiz_name="Test Quiz", max_score=10)

        # 2. Boundary value: 0
        score_0 = StudentColumnScore.objects.create(student=self.student, column=column, score=0)
        quiz_score_0 = QuizScore.objects.create(student=self.student, quiz=quiz, score=0, graded_by=self.teacher)
        lesson_points_0 = StudentLessonPoints.objects.create(student=self.student, lesson_session=self.session, points=0)
        
        self.assertEqual(scp.get_activity_points(), 0)

        # Clean up
        score_0.delete()
        quiz_score_0.delete()
        lesson_points_0.delete()

        # 3. Boundary value: -1
        score_neg = StudentColumnScore.objects.create(student=self.student, column=column, score=-1)
        quiz_score_neg = QuizScore.objects.create(student=self.student, quiz=quiz, score=-1, graded_by=self.teacher)
        lesson_points_neg = StudentLessonPoints.objects.create(student=self.student, lesson_session=self.session, points=-1)

        # sum is -1 + -1 + -1 = -3
        self.assertEqual(scp.get_activity_points(), -3)
        
        # Test how calculate_points_internal handles negative points
        scp.calculate_points_internal()
        scp.refresh_from_db()
        # Points = int((-3 * 2) + 5.0) = -6 + 5 = -1
        self.assertEqual(scp.points, -1)

    def test_update_custom_score_boundary_values(self):
        from school_management.models import PointColumn, StudentColumnScore
        import json
        from django.urls import reverse
        from django.test import Client
        
        client = Client()
        client.force_login(self.teacher)
        column = PointColumn.objects.create(classroom=self.classroom, column_title="API Test Column")
        url = reverse('school_management:update_custom_score', args=[self.classroom.id])

        # 1. Boundary value: 0
        data_0 = {
            'student_id': self.student.id,
            'column_id': column.id,
            'score': 0
        }
        response = client.post(url, data=json.dumps(data_0), content_type='application/json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(StudentColumnScore.objects.get(student=self.student, column=column).score, 0)

        # 2. Boundary value: -1
        data_neg = {
            'student_id': self.student.id,
            'column_id': column.id,
            'score': -1
        }
        response = client.post(url, data=json.dumps(data_neg), content_type='application/json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(StudentColumnScore.objects.get(student=self.student, column=column).score, -1)

        # 3. Boundary value: None (null in JSON)
        # It should return a 400 error because database field is not nullable, and be caught gracefully
        data_none = {
            'student_id': self.student.id,
            'column_id': column.id,
            'score': None
        }
        response = client.post(url, data=json.dumps(data_none), content_type='application/json')
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json().get('success', False))
