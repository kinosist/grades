import uuid
from datetime import date, timedelta

from django.conf import settings
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from school_management.models import (
    ClassRoom,
    CustomUser,
    GoogleOAuthSession,
    Group,
    GroupMember,
    LessonSession,
    PeerEvaluation,
)


@override_settings(
    ALLOWED_GMAIL_DOMAINS=('example.com',),
    GOOGLE_OAUTH_CLIENT_ID='dummy-client-id',
    GOOGLE_OAUTH_CLIENT_SECRET='dummy-client-secret',
    PEER_EVAL_SESSION_COOKIE_NAME='peer_eval_session_id',
    PEER_EVAL_SESSION_TTL_HOURS=24,
)
class PeerEvaluationAuthTest(TestCase):
    def setUp(self):
        self.teacher = CustomUser.objects.create_user(
            email='teacher@example.com',
            full_name='Teacher One',
            password='pass123',
            role='teacher',
        )
        self.student1 = CustomUser.objects.create_user(
            email='STUDENT1@EXAMPLE.COM',
            full_name='Student One',
            password='pass123',
            role='student',
            student_number='S001',
        )
        self.student2 = CustomUser.objects.create_user(
            email='student2@example.com',
            full_name='Student Two',
            password='pass123',
            role='student',
            student_number='S002',
        )

        self.classroom = ClassRoom.objects.create(class_name='Test Class', year=2026, semester='first')
        self.classroom.teachers.add(self.teacher)
        self.classroom.students.add(self.student1, self.student2)

        self.lesson_session = LessonSession.objects.create(
            classroom=self.classroom,
            session_number=1,
            date=date(2026, 4, 1),
            has_peer_evaluation=True,
        )
        self.group1 = Group.objects.create(lesson_session=self.lesson_session, group_number=1, group_name='A')
        self.group2 = Group.objects.create(lesson_session=self.lesson_session, group_number=2, group_name='B')
        GroupMember.objects.create(group=self.group1, student=self.student1)
        GroupMember.objects.create(group=self.group2, student=self.student2)

    def _set_oauth_cookie(self, email='student1@example.com', expired=False):
        oauth_session = GoogleOAuthSession.objects.create(
            session_id='test-session-id',
            email=email,
            expires_at=timezone.now() - timedelta(hours=1) if expired else timezone.now() + timedelta(hours=1),
        )
        self.client.cookies[settings.PEER_EVAL_SESSION_COOKIE_NAME] = oauth_session.session_id
        return oauth_session

    def test_common_form_requires_google_auth_without_cookie(self):
        response = self.client.get(
            reverse('school_management:peer_evaluation_common', kwargs={'session_id': self.lesson_session.id})
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['requires_google_auth'])

    def test_common_form_accepts_case_insensitive_email_match(self):
        self._set_oauth_cookie(email='student1@example.com')

        response = self.client.get(
            reverse('school_management:peer_evaluation_common', kwargs={'session_id': self.lesson_session.id})
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context['requires_google_auth'])
        self.assertEqual(response.context['authenticated_student'].id, self.student1.id)

    def test_common_form_rejects_not_allowed_domain(self):
        self._set_oauth_cookie(email='student1@blocked.com')

        response = self.client.get(
            reverse('school_management:peer_evaluation_common', kwargs={'session_id': self.lesson_session.id})
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['requires_google_auth'])
        self.assertEqual(GoogleOAuthSession.objects.count(), 0)

    def test_common_form_shows_submitted_state_for_existing_submission(self):
        self._set_oauth_cookie(email='student1@example.com')
        PeerEvaluation.objects.create(
            lesson_session=self.lesson_session,
            student=self.student1,
            email='student1@example.com',
            evaluator_token=uuid.uuid4(),
            evaluator_group=self.group1,
            first_place_group=self.group2,
            second_place_group=self.group1,
            first_place_reason='good',
            second_place_reason='ok',
        )

        response = self.client.get(
            reverse('school_management:peer_evaluation_common', kwargs={'session_id': self.lesson_session.id})
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['submission_exists'])

    def test_results_include_submission_rate(self):
        PeerEvaluation.objects.create(
            lesson_session=self.lesson_session,
            student=self.student1,
            email='student1@example.com',
            evaluator_token=uuid.uuid4(),
            evaluator_group=self.group1,
            first_place_group=self.group2,
            second_place_group=self.group1,
            first_place_reason='good',
            second_place_reason='ok',
        )

        self.client.force_login(self.teacher)
        response = self.client.get(
            reverse('school_management:peer_evaluation_results', kwargs={'session_id': self.lesson_session.id})
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['submitted_count'], 1)
        self.assertEqual(response.context['total_students'], 2)
        self.assertEqual(response.context['submission_rate'], 50.0)

    def test_post_without_evaluator_group_uses_authenticated_students_group(self):
        self._set_oauth_cookie(email='student1@example.com')

        response = self.client.post(
            reverse('school_management:peer_evaluation_common', kwargs={'session_id': self.lesson_session.id}),
            {
                'participant_count': '1',
                'first_place_group': str(self.group2.id),
                'second_place_group': str(self.group1.id),
                'first_place_reason': 'good',
                'second_place_reason': 'ok',
                'general_comment': 'comment',
            },
        )

        self.assertEqual(response.status_code, 200)
        created = PeerEvaluation.objects.get(lesson_session=self.lesson_session, student=self.student1)
        self.assertEqual(created.evaluator_group_id, self.group1.id)


