import os

from django.apps import apps
from django.test.runner import DiscoverRunner


class AppDiscoverRunner(DiscoverRunner):
    """Use school_management.tests as default label when no label is given."""

    def build_suite(self, test_labels=None, **kwargs):
        labels = list(test_labels or [])
        if not labels:
            labels = ['school_management.tests']
            try:
                return super().build_suite(labels, **kwargs)
            except TypeError:
                app_path = apps.get_app_config('school_management').path
                labels = [os.path.join(app_path, 'tests')]
        return super().build_suite(labels, **kwargs)
