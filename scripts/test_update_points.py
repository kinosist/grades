import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE','school_project.settings')
import django
django.setup()
from school_management.models import CustomUser

# 作成と更新
u = CustomUser.objects.create_user(email='tmp_student_test@example.com', full_name='Tmp Student', password='pass123', role='student', student_number='TMP123')
print('created id:', u.id, 'points:', u.points)

u.points = 99
u.save()
print('after save:', CustomUser.objects.get(id=u.id).points)
