import json
from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from school_management.models import ClassRoom, StudentClassPoints

User = get_user_model()

class StudentNormalizationTests(TestCase):
    def setUp(self):
        self.client = Client()
        
        # 教員ユーザー作成
        self.teacher = User.objects.create_user(
            email='teacher_norm@example.com',
            password='password123',
            full_name='Teacher Norm',
            role='teacher'
        )
        self.client.login(email='teacher_norm@example.com', password='password123')
        
        # クラス作成
        self.classroom = ClassRoom.objects.create(
            class_name='Normalization Class',
            year=2024,
            semester='first'
        )
        self.classroom.teachers.add(self.teacher)

    def test_pure_normalization_functions(self):
        # 1. 学籍番号の正規化テスト
        self.assertEqual(User.clean_student_number("s 123 45"), "S12345")
        self.assertEqual(User.clean_student_number("  S12345  "), "S12345")
        self.assertEqual(User.clean_student_number("ｓ１２３　４５"), "S12345") # 全角英数字は半角に変換され、大文字になり、全角スペースは除去される
        self.assertEqual(User.clean_student_number("s　123　45"), "S12345") # 全角スペース除去テスト
        self.assertEqual(User.clean_student_number(""), "")
        self.assertEqual(User.clean_student_number(None), "")
        
        # 2. メールアドレスの正規化テスト
        self.assertEqual(User.clean_email(" User@Example.com "), "user@example.com")
        self.assertEqual(User.clean_email("user @ example.com"), "user@example.com")
        self.assertEqual(User.clean_email("user　@　example.com"), "user@example.com") # 全角スペース除去テスト
        self.assertEqual(User.clean_email(""), None)
        self.assertEqual(User.clean_email(None), None)

    def test_single_registration_flow(self):
        # 1. パターンA（新規登録）：正規化されて保存されるか
        create_url = reverse('school_management:student_create')
        response = self.client.post(create_url, {
            'registration_type': 'single',
            'student_number': ' s 999 99 ', # 空白・小文字
            'full_name': 'Test Normalization',
            'furigana': 'てすと のーまらいぜーしょん',
            'email': ' Student_Norm@Example.com ', # 空白・大文字混じり
            'classroom_id': self.classroom.id
        })
        self.assertIn(response.status_code, [200, 302])
        
        # DB確認
        student = User.objects.get(full_name='Test Normalization')
        self.assertEqual(student.student_number, 'S99999')
        self.assertEqual(student.email, 'student_norm@example.com')
        self.assertTrue(self.classroom.students.filter(id=student.id).exists())
        
        # 2. パターンB（既存アカウント共有）：大文字小文字/スペースが違っていても既存アカウントを紐づける
        # 別のクラスを作成
        another_class = ClassRoom.objects.create(
            class_name='Another Class',
            year=2024,
            semester='first'
        )
        another_class.teachers.add(self.teacher)
        
        # 同じ学生を違う表記「s99999」かつ「student_norm@example.com」で登録
        response = self.client.post(create_url, {
            'registration_type': 'single',
            'student_number': 's99999',
            'full_name': 'Test Normalization',
            'furigana': 'てすと のーまらいぜーしょん',
            'email': 'student_norm@example.com',
            'classroom_id': another_class.id
        })
        self.assertIn(response.status_code, [200, 302])
        
        # 新しいアカウントが作成されていないことを確認
        self.assertEqual(User.objects.filter(student_number='S99999').count(), 1)
        # another_class に紐づいているか確認
        self.assertTrue(another_class.students.filter(student_number='S99999').exists())

        # 3. パターンC（不整合エラー）：学籍番号が一致するがメールアドレスが異なる場合
        response = self.client.post(create_url, {
            'registration_type': 'single',
            'student_number': 'S99999',
            'full_name': 'Test Normalization',
            'furigana': 'てすと のーまらいぜーしょん',
            'email': 'different_email@example.com',
            'classroom_id': self.classroom.id
        })
        # 登録を中止し、エラーメッセージを返す
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '既に別のメールアドレス')

    def test_bulk_text_registration_flow(self):
        # 画面からの一括登録テキストエリア
        create_url = reverse('school_management:student_create')
        bulk_data = (
            " s 100 01 , Student Bulk 1, しゅーでんと 1, Bulk1@Example.com \n" # スペース除去・大文字小文字変換
            "s10002, Student Bulk 2, しゅーでんと 2, bulk2@example.com\n"
        )
        response = self.client.post(create_url, {
            'registration_type': 'bulk',
            'bulk_student_data': bulk_data,
            'classroom_id': self.classroom.id
        })
        self.assertIn(response.status_code, [200, 302])
        
        # DB確認
        s1 = User.objects.get(student_number='S10001')
        self.assertEqual(s1.email, 'bulk1@example.com')
        s2 = User.objects.get(student_number='S10002')
        self.assertEqual(s2.email, 'bulk2@example.com')
        
        # 不整合エラー（パターンC）の一括登録ロールバックテスト
        bulk_data_invalid = (
            "s10003, Student Bulk 3, しゅーでんと 3, bulk3@example.com\n"
            "S10001, Student Bulk 1, しゅーでんと 1, invalid_email@example.com\n" # S10001は登録済みのメールと異なる
        )
        response = self.client.post(create_url, {
            'registration_type': 'bulk',
            'bulk_student_data': bulk_data_invalid,
            'classroom_id': self.classroom.id
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '既に別のメールアドレス')
        # ロールバックされてS10003が作成されていないことを確認
        self.assertFalse(User.objects.filter(student_number='S10003').exists())

    def test_bulk_csv_enrollment_flow(self):
        # クラス詳細からのCSV一括登録
        csv_url = reverse('school_management:bulk_student_add_csv', args=[self.classroom.id])
        csv_data = (
            " s 200 01 , Student CSV 1, csv1@Example.com \n" # スペース混じり・大文字小文字
            "s20002, Student CSV 2, csv2@example.com\n"
        )
        response = self.client.post(csv_url, {
            'student_data': csv_data
        })
        self.assertIn(response.status_code, [200, 302])
        
        # DB確認
        s1 = User.objects.get(student_number='S20001')
        self.assertEqual(s1.email, 'csv1@example.com')
        s2 = User.objects.get(student_number='S20002')
        self.assertEqual(s2.email, 'csv2@example.com')

        # パターンC（不整合）による全件中止
        csv_data_invalid = (
            "s20003, Student CSV 3, csv3@example.com\n"
            "S20001, Student CSV 1, different_csv@example.com\n" # S20001の既存メールと異なる
        )
        response = self.client.post(csv_url, {
            'student_data': csv_data_invalid
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '既に別のメールアドレス')
        # 全件ロールバックされてS20003が登録されていないこと
        self.assertFalse(User.objects.filter(student_number='S20003').exists())

    def test_student_edit_validation(self):
        # 1. 学生を一人登録
        student1 = User.objects.create_user(
            email='edit1@example.com',
            password='password123',
            full_name='Student Edit 1',
            student_number='E001',
            role='student'
        )
        student2 = User.objects.create_user(
            email='edit2@example.com',
            password='password123',
            full_name='Student Edit 2',
            student_number='E002',
            role='student'
        )
        
        # 2. 編集画面から正常に更新
        edit_url = reverse('school_management:student_edit', args=[student1.student_number])
        response = self.client.post(edit_url, {
            'full_name': 'Student Edit 1 Mod',
            'furigana': 'ふりがな',
            'email': '  Edit1_Mod@Example.com  ' # 正規化される
        })
        self.assertIn(response.status_code, [200, 302])
        
        student1.refresh_from_db()
        self.assertEqual(student1.full_name, 'Student Edit 1 Mod')
        self.assertEqual(student1.email, 'edit1_mod@example.com')
        
        # 3. 編集画面で他人のメールアドレスと重複させた場合
        response = self.client.post(edit_url, {
            'full_name': 'Student Edit 1 Mod',
            'furigana': 'ふりがな',
            'email': 'edit2@example.com' # student2 of email
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '既に別の学生（学籍番号: E002）に使用されています。')
