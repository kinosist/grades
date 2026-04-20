from django.test import TestCase, Client
from django.urls import reverse
from datetime import date
from school_management.models import (
    CustomUser,
    ClassRoom,
    StudentClassPoints,
    LessonSession,
    Group,
    GroupMember,
    PeerEvaluation,
    PeerEvaluationSettings,
)
import uuid

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


class ClassPointsGroupVoteConsistencyTest(TestCase):
    def setUp(self):
        self.teacher = CustomUser.objects.create_user(
            email='teacher2@example.com',
            full_name='Teacher Two',
            password='pass123',
            role='teacher',
        )
        self.student1 = CustomUser.objects.create_user(
            email='student1-2@example.com',
            full_name='Student One Two',
            password='pass123',
            role='student',
            student_number='S101',
        )
        self.student2 = CustomUser.objects.create_user(
            email='student2-2@example.com',
            full_name='Student Two Two',
            password='pass123',
            role='student',
            student_number='S102',
        )
        self.student3 = CustomUser.objects.create_user(
            email='student3-2@example.com',
            full_name='Student Three Two',
            password='pass123',
            role='student',
            student_number='S103',
        )
        self.classroom = ClassRoom.objects.create(class_name='Vote Test Class', year=2025, semester='first')
        self.classroom.teachers.add(self.teacher)
        self.classroom.students.add(self.student1, self.student2, self.student3)

        self.session = LessonSession.objects.create(
            classroom=self.classroom,
            session_number=1,
            date=date(2026, 4, 1),
            has_peer_evaluation=True,
        )
        self.group1 = Group.objects.create(lesson_session=self.session, group_number=1, group_name='G1')
        self.group2 = Group.objects.create(lesson_session=self.session, group_number=2, group_name='G2')
        self.group3 = Group.objects.create(lesson_session=self.session, group_number=3, group_name='G3')
        GroupMember.objects.create(group=self.group1, student=self.student1)
        GroupMember.objects.create(group=self.group2, student=self.student2)
        GroupMember.objects.create(group=self.group3, student=self.student3)

        PeerEvaluationSettings.objects.create(
            lesson_session=self.session,
            member_scores=[0],
            enable_group_evaluation=True,
            group_scores=[5, 3, 1],
            group_evaluation_method=PeerEvaluationSettings.EvaluationMethod.AGGREGATE,
        )

        PeerEvaluation.objects.create(
            lesson_session=self.session,
            student=self.student1,
            email=self.student1.email,
            evaluator_token=uuid.uuid4(),
            evaluator_group=self.group1,
            response_json={'other_group_eval': [{'rank': 1, 'group_id': self.group1.id}, {'rank': 2, 'group_id': self.group2.id}]},
        )
        PeerEvaluation.objects.create(
            lesson_session=self.session,
            student=self.student2,
            email=self.student2.email,
            evaluator_token=uuid.uuid4(),
            evaluator_group=self.group2,
            response_json={'other_group_eval': [{'rank': 1, 'group_id': self.group1.id}, {'rank': 2, 'group_id': self.group3.id}]},
        )

        self.client = Client()
        self.client.force_login(self.teacher)

    def _get_student_grade(self, response, student_id):
        for grade in response.context['student_grades']:
            if grade['student'].id == student_id:
                return grade
        return None

    def _get_student_evaluation(self, response, student_id):
        for evaluation in response.context['student_evaluations']:
            if evaluation['student'].id == student_id:
                return evaluation
        return None

    def test_class_points_aggregate_closed_matches_model_vote_points(self):
        self.session.peer_evaluation_status = LessonSession.PeerEvaluationStatus.CLOSED
        self.session.save(update_fields=['peer_evaluation_status'])

        response = self.client.get(reverse('school_management:class_points', kwargs={'class_id': self.classroom.id}))
        self.assertEqual(response.status_code, 200)

        grade = self._get_student_grade(response, self.student1.id)
        self.assertIsNotNone(grade)
        self.assertEqual(grade['peer_total'], 5)

        scp, _ = StudentClassPoints.objects.get_or_create(student=self.student1, classroom=self.classroom)
        self.assertEqual(grade['peer_total'], scp._calculate_group_vote_points())

    def test_class_points_aggregate_open_shows_zero_vote_points(self):
        self.session.peer_evaluation_status = LessonSession.PeerEvaluationStatus.OPEN
        self.session.save(update_fields=['peer_evaluation_status'])

        response = self.client.get(reverse('school_management:class_points', kwargs={'class_id': self.classroom.id}))
        self.assertEqual(response.status_code, 200)

        grade = self._get_student_grade(response, self.student1.id)
        self.assertIsNotNone(grade)
        self.assertEqual(grade['peer_total'], 0)

    def test_class_evaluation_aggregate_closed_matches_model_vote_points(self):
        self.session.peer_evaluation_status = LessonSession.PeerEvaluationStatus.CLOSED
        self.session.save(update_fields=['peer_evaluation_status'])

        response = self.client.get(reverse('school_management:class_evaluation', kwargs={'class_id': self.classroom.id}))
        self.assertEqual(response.status_code, 200)

        evaluation = self._get_student_evaluation(response, self.student1.id)
        self.assertIsNotNone(evaluation)
        self.assertEqual(evaluation['session_scores'][0]['peer_vote'], 5)

        scp, _ = StudentClassPoints.objects.get_or_create(student=self.student1, classroom=self.classroom)
        self.assertEqual(evaluation['session_scores'][0]['peer_vote'], scp._calculate_group_vote_points())

    def test_class_evaluation_aggregate_open_shows_zero_vote_points(self):
        self.session.peer_evaluation_status = LessonSession.PeerEvaluationStatus.OPEN
        self.session.save(update_fields=['peer_evaluation_status'])

        response = self.client.get(reverse('school_management:class_evaluation', kwargs={'class_id': self.classroom.id}))
        self.assertEqual(response.status_code, 200)

        evaluation = self._get_student_evaluation(response, self.student1.id)
        self.assertIsNotNone(evaluation)
        self.assertEqual(evaluation['session_scores'][0]['peer_vote'], 0)
