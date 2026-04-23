from django.test.runner import DiscoverRunner


class AppDiscoverRunner(DiscoverRunner):
    """Use school_management.tests as default label only when no label is given."""

    def build_suite(self, test_labels=None, **kwargs):
        labels = list(test_labels or [])
        if not labels:
            labels = ['school_management/tests']
        return super().build_suite(labels, **kwargs)
