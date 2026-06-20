from django.test import TestCase
from django.db import IntegrityError
from school_management.models import (
    CustomUser,
    ClassRoom,
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
        self.classroom.students.add(self.student)
        
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
