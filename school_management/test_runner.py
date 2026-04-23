from django.test.runner import DiscoverRunner


class AppDiscoverRunner(DiscoverRunner):
    """Run school_management tests when no explicit labels are provided."""

    def build_suite(self, test_labels=None, **kwargs):
        labels = list(test_labels or [])
        if not labels:
            labels = ['school_management.tests']
        return super().build_suite(labels, **kwargs)
