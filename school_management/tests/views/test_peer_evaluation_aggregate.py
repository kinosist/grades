import uuid
from datetime import date

from django.test import TestCase
from django.urls import reverse

from school_management.models import (
    ClassRoom,
    ContributionEvaluation,
    CustomUser,
    Group,
    GroupMember,
    LessonSession,
    PeerEvaluation,
    PeerEvaluationSettings,
)


class PeerEvaluationAggregateFlowTest(TestCase):
    def setUp(self):
        self.teacher = CustomUser.objects.create_user(
            email='teacher-agg@example.com',
            full_name='Teacher Aggregate',
            password='pass123',
            role='teacher',
        )
        self.s1 = CustomUser.objects.create_user(
            email='s1@example.com',
            full_name='Student 1',
            password='pass123',
            role='student',
            student_number='A001',
        )
        self.s2 = CustomUser.objects.create_user(
            email='s2@example.com',
            full_name='Student 2',
            password='pass123',
            role='student',
            student_number='A002',
        )
        self.s3 = CustomUser.objects.create_user(
            email='s3@example.com',
            full_name='Student 3',
            password='pass123',
            role='student',
            student_number='A003',
        )
        self.s4 = CustomUser.objects.create_user(
            email='s4@example.com',
            full_name='Student 4',
            password='pass123',
            role='student',
            student_number='A004',
        )

        self.classroom = ClassRoom.objects.create(class_name='Aggregate Test', year=2026, semester='first')
        self.classroom.teachers.add(self.teacher)
        self.classroom.students.add(self.s1, self.s2, self.s3, self.s4)

        self.session = LessonSession.objects.create(
            classroom=self.classroom,
            session_number=1,
            date=date(2026, 4, 1),
            has_peer_evaluation=True,
            peer_evaluation_status=LessonSession.PeerEvaluationStatus.NOT_OPEN,
        )

        self.g1 = Group.objects.create(lesson_session=self.session, group_number=1, group_name='G1')
        self.g2 = Group.objects.create(lesson_session=self.session, group_number=2, group_name='G2')
        GroupMember.objects.create(group=self.g1, student=self.s1)
        GroupMember.objects.create(group=self.g1, student=self.s2)
        GroupMember.objects.create(group=self.g2, student=self.s3)
        GroupMember.objects.create(group=self.g2, student=self.s4)

        PeerEvaluationSettings.objects.create(
            lesson_session=self.session,
            enable_member_evaluation=True,
            member_scores=[4, 2],
            evaluation_method=PeerEvaluationSettings.EvaluationMethod.AGGREGATE,
            enable_group_evaluation=True,
            group_scores=[5, 3],
            group_evaluation_method=PeerEvaluationSettings.EvaluationMethod.AGGREGATE,
        )

        self.session.peer_evaluation_status = LessonSession.PeerEvaluationStatus.OPEN
        self.session.save(update_fields=['peer_evaluation_status'])

        self._create_submission(self.s1, self.g1, other_group=self.g2, member_id=self.s2.id)
        self._create_submission(self.s2, self.g1, other_group=self.g2, member_id=self.s1.id)
        self._create_submission(self.s3, self.g2, other_group=self.g1, member_id=self.s4.id)
        self._create_submission(self.s4, self.g2, other_group=self.g1, member_id=self.s3.id)

        self.client.force_login(self.teacher)

    def _create_submission(self, student, evaluator_group, other_group, member_id):
        PeerEvaluation.objects.create(
            lesson_session=self.session,
            student=student,
            email=student.email,
            evaluator_token=uuid.uuid4(),
            evaluator_group=evaluator_group,
            response_json={
                'other_group_eval': [{'rank': 1, 'group_id': other_group.id}],
                'group_members_eval': [{'rank': 1, 'member_id': member_id}],
            },
        )

    def test_aggregate_group_score_is_zero_before_close(self):
        response = self.client.get(
            reverse('school_management:peer_evaluation_results', kwargs={'session_id': self.session.id})
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(all(stat['score'] == 0 for stat in response.context['group_stats']))

    def test_aggregate_group_score_is_assigned_after_close(self):
        self.session.peer_evaluation_status = LessonSession.PeerEvaluationStatus.CLOSED
        self.session.save(update_fields=['peer_evaluation_status'])

        response = self.client.get(
            reverse('school_management:peer_evaluation_results', kwargs={'session_id': self.session.id})
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(all(stat['score'] == 5 for stat in response.context['group_stats']))

    def test_close_creates_expected_aggregate_contribution_evaluations(self):
        self.assertEqual(ContributionEvaluation.objects.count(), 0)

        response = self.client.post(
            reverse('school_management:close_peer_evaluation', kwargs={'session_id': self.session.id})
        )
        self.assertEqual(response.status_code, 302)

        self.session.refresh_from_db()
        self.assertEqual(self.session.peer_evaluation_status, LessonSession.PeerEvaluationStatus.CLOSED)

        contribution_evals = ContributionEvaluation.objects.filter(
            peer_evaluation__lesson_session=self.session
        )
        self.assertEqual(contribution_evals.count(), 4)
        self.assertTrue(all(item.contribution_score == 4 for item in contribution_evals))

    def test_delete_all_is_blocked_after_close(self):
        self.session.peer_evaluation_status = LessonSession.PeerEvaluationStatus.CLOSED
        self.session.save(update_fields=['peer_evaluation_status'])

        before_count = PeerEvaluation.objects.filter(lesson_session=self.session).count()
        response = self.client.post(
            reverse('school_management:delete_all_peer_evaluations', kwargs={'session_id': self.session.id})
        )

        self.assertEqual(response.status_code, 302)
        after_count = PeerEvaluation.objects.filter(lesson_session=self.session).count()
        self.assertEqual(before_count, after_count)

    def test_delete_all_works_before_close(self):
        response = self.client.post(
            reverse('school_management:delete_all_peer_evaluations', kwargs={'session_id': self.session.id})
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(PeerEvaluation.objects.filter(lesson_session=self.session).count(), 0)


class PeerEvaluationSettingsViewTest(TestCase):
    def setUp(self):
        self.teacher = CustomUser.objects.create_user(
            email='teacher-settings@example.com',
            full_name='Teacher Settings',
            password='pass123',
            role='teacher',
        )
        self.classroom = ClassRoom.objects.create(class_name='Settings Test', year=2026, semester='first')
        self.classroom.teachers.add(self.teacher)
        self.session = LessonSession.objects.create(
            classroom=self.classroom,
            session_number=1,
            date=date(2026, 4, 2),
            has_peer_evaluation=True,
            peer_evaluation_status=LessonSession.PeerEvaluationStatus.NOT_OPEN,
        )
        self.client.force_login(self.teacher)

    def test_settings_save_allows_disabled_member_and_group_evaluation(self):
        response = self.client.post(
            reverse('school_management:peer_evaluation_settings', kwargs={'session_id': self.session.id}),
            {
                'member_reason_control': PeerEvaluationSettings.ReasonMode.DISABLED,
                'evaluation_method': PeerEvaluationSettings.EvaluationMethod.DIRECT,
                'group_reason_control': PeerEvaluationSettings.ReasonMode.DISABLED,
                'group_evaluation_method': PeerEvaluationSettings.EvaluationMethod.DIRECT,
                'member_scores_json': '[]',
                'group_scores_json': '[]',
            },
        )

        self.assertEqual(response.status_code, 302)
        settings_obj = PeerEvaluationSettings.objects.get(lesson_session=self.session)
        self.assertFalse(settings_obj.enable_member_evaluation)
        self.assertFalse(settings_obj.enable_group_evaluation)
        self.assertEqual(settings_obj.member_scores, [])
        self.assertEqual(settings_obj.group_scores, [])

