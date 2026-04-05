from django.db import migrations

def convert_standard_to_default(apps, schema_editor):
    # 過去のデータで 'standard' になっているものを 'default' に上書きする処理
    ClassRoom = apps.get_model('school_management', 'ClassRoom')
    ClassRoom.objects.filter(grading_system='standard').update(grading_system='default')

class Migration(migrations.Migration):

    dependencies = [
        # 直前のマイグレーションファイルを指定
        ('school_management', '0029_alter_classroom_grading_system'), 
    ]

    operations = [
        migrations.RunPython(convert_standard_to_default),
    ]