from django.test import TestCase, Client
from django.urls import reverse
from school_management.models import CustomUser, ClassRoom, StudentClassPoints

class PointsAPITest(TestCase):
    def setUp(self):
        # 教員と学生ユーザー、クラスを作成
        self.teacher = CustomUser.objects.create_user(email='teacher@example.com', full_name='Teacher One', password='pass123', role='teacher')
        self.student = CustomUser.objects.create_user(email='student@example.com', full_name='Student One', password='pass123', role='student', student_number='S001')
        self.classroom = ClassRoom.objects.create(class_name='Test Class', year=2025, semester='first')
        self.classroom.teachers.add(self.teacher)
        self.classroom.students.add(self.student)
        # クラスポイントを0で初期化
        StudentClassPoints.objects.get_or_create(
            student=self.student,
            classroom=self.classroom,
            defaults={'points': 0}
        )

        # クライアントをログイン状態で用意（teacher）
        self.client = Client()
        self.client.force_login(self.teacher)

    def test_update_overall_points_requires_class_id(self):
        """class_idなしではエラーを返すことを確認"""
        url = reverse('school_management:update_student_points', kwargs={'student_id': self.student.id})
        data = {'points': 7}
        response = self.client.post(url, data, content_type='application/json')
        self.assertEqual(response.status_code, 200)
        response_data = response.json()
        self.assertFalse(response_data['success'])
        self.assertIn('class_id', response_data['error'])

    def test_update_class_points(self):
        url = reverse('school_management:update_student_points', kwargs={'student_id': self.student.id})
        data = {'points': 12, 'class_id': self.classroom.id}
        response = self.client.post(url, data, content_type='application/json')
        self.assertEqual(response.status_code, 200)
        # StudentClassPoints が作成され、値が設定されていること
        scp = StudentClassPoints.objects.get(student=self.student, classroom=self.classroom)
        self.assertEqual(scp.points, 12)

    def test_student_edit_does_not_update_points(self):
        """学生編集画面ではポイントを更新しないことを確認"""
        url = reverse('school_management:student_edit', kwargs={'student_number': self.student.student_number})
        # 必須フィールドを含めたフォームデータ
        initial_points = self.student.points
        data = {
            'full_name': 'Updated Name',
            'furigana': 'フリガナ',
            'email': self.student.email,
            'points': '15'  # これは無視されるべき
        }
        response = self.client.post(url, data)
        # リダイレクトが発生すれば成功とみなす
        self.assertIn(response.status_code, (302, 200))
        self.student.refresh_from_db()
        # ポイントは変更されていないことを確認
        self.assertEqual(self.student.points, initial_points)
        # 名前は更新されていることを確認
        self.assertEqual(self.student.full_name, 'Updated Name')
