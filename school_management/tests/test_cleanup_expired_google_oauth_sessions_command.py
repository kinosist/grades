from datetime import timedelta
from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from school_management.models import GoogleOAuthSession


class CleanupExpiredGoogleOAuthSessionsCommandTest(TestCase):
    def setUp(self):
        now = timezone.now()
        self.expired = GoogleOAuthSession.objects.create(
            session_id='expired-session',
            email='expired@example.com',
            expires_at=now - timedelta(hours=1),
        )
        self.active = GoogleOAuthSession.objects.create(
            session_id='active-session',
            email='active@example.com',
            expires_at=now + timedelta(hours=1),
        )

    def test_cleanup_command_deletes_only_expired_sessions(self):
        output = StringIO()
        call_command('cleanup_expired_google_oauth_sessions', stdout=output)

        self.assertFalse(
            GoogleOAuthSession.objects.filter(id=self.expired.id).exists()
        )
        self.assertTrue(
            GoogleOAuthSession.objects.filter(id=self.active.id).exists()
        )
        self.assertIn('1 件', output.getvalue())

    def test_cleanup_command_dry_run_does_not_delete(self):
        output = StringIO()
        call_command('cleanup_expired_google_oauth_sessions', '--dry-run', stdout=output)

        self.assertTrue(
            GoogleOAuthSession.objects.filter(id=self.expired.id).exists()
        )
        self.assertTrue(
            GoogleOAuthSession.objects.filter(id=self.active.id).exists()
        )
        self.assertIn('[DRY RUN]', output.getvalue())

