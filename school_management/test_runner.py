import os

from django.apps import apps
from django.test.runner import DiscoverRunner


class AppDiscoverRunner(DiscoverRunner):
    """Use school_management test directory as default label only when no label is given."""

    def build_suite(self, test_labels=None, **kwargs):
        labels = list(test_labels or [])
        if not labels:
            app_path = apps.get_app_config('school_management').path
            labels = [os.path.join(app_path, 'tests')]
        return super().build_suite(labels, **kwargs)
