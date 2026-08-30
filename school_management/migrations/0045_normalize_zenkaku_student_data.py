# Generated manually

import re
import unicodedata
from django.db import migrations


def normalize_students(apps, schema_editor):
    CustomUser = apps.get_model('school_management', 'CustomUser')
    for student in CustomUser.objects.filter(role='student'):
        changed = False
        if student.student_number:
            cleaned_number = re.sub(r'\s+', '', unicodedata.normalize('NFKC', str(student.student_number))).upper()
            if student.student_number != cleaned_number:
                student.student_number = cleaned_number
                changed = True

        if student.email:
            cleaned_email = re.sub(r'\s+', '', unicodedata.normalize('NFKC', str(student.email))).lower()
            if not cleaned_email:
                cleaned_email = None
            if student.email != cleaned_email:
                student.email = cleaned_email
                changed = True

        if changed:
            student.save()


class Migration(migrations.Migration):

    dependencies = [
        ('school_management', '0044_normalize_existing_student_data'),
    ]

    operations = [
        migrations.RunPython(normalize_students, migrations.RunPython.noop),
    ]
