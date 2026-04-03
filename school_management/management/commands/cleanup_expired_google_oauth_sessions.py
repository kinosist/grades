from django.core.management.base import BaseCommand
from django.utils import timezone

from school_management.models import GoogleOAuthSession


class Command(BaseCommand):
    help = '期限切れのGoogleOAuthSessionを削除します。'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='削除せずに対象件数だけ表示します。',
        )

    def handle(self, *args, **options):
        now = timezone.now()
        expired_qs = GoogleOAuthSession.objects.filter(expires_at__lte=now)
        expired_count = expired_qs.count()

        if options['dry_run']:
            self.stdout.write(
                self.style.WARNING(
                    f'[DRY RUN] 期限切れセッション: {expired_count} 件（削除は実行しません）'
                )
            )
            return

        deleted_count, _ = expired_qs.delete()
        self.stdout.write(
            self.style.SUCCESS(
                f'期限切れセッションを削除しました: {deleted_count} 件'
            )
        )

