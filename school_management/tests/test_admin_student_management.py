from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from school_management.models import TeacherStudentAssignment

User = get_user_model()

class AdminStudentManagementTests(TestCase):
    def setUp(self):
        self.client = Client()
        
        # 管理者ユーザー作成
        self.admin = User.objects.create_user(
            email='admin_mgr@example.com',
            password='password123',
            full_name='Admin Manager',
            role='admin'
        )
        
        # 教員ユーザー作成
        self.teacher = User.objects.create_user(
            email='teacher_mgr@example.com',
            password='password123',
            full_name='Teacher Manager',
            role='teacher'
        )
        
        # 学生ユーザー作成
        self.student = User.objects.create_user(
            email='student_mgr@example.com',
            password='password123',
            full_name='Student Manager',
            student_number='MGR001',
            role='student'
        )
        TeacherStudentAssignment.assign(self.teacher, self.student)

    def test_unauthorized_access_denied(self):
        # 1. ログインなしでアクセス -> ログイン画面へリダイレクト
        url = reverse('school_management:admin_teacher_management')
        response = self.client.get(url)
        self.assertRedirects(response, f"{reverse('school_management:login')}?next={url}")
        
        # 2. 教員（非管理者）でログインしてアクセス -> ダッシュボードへリダイレクト
        self.client.login(email='teacher_mgr@example.com', password='password123')
        response = self.client.get(url)
        self.assertRedirects(response, reverse('school_management:dashboard'))
        self.client.logout()

        # 3. 学生でログインしてアクセス -> ダッシュボードへリダイレクト
        self.client.login(email='student_mgr@example.com', password='password123')
        response = self.client.get(url)
        self.assertRedirects(response, reverse('school_management:dashboard'))

    def test_admin_access_allowed(self):
        # 管理者でログインしてアクセス -> 200 OK
        self.client.login(email='admin_mgr@example.com', password='password123')
        url = reverse('school_management:admin_teacher_management')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        
        # コンテキストに含まれる教師と学生のチェック
        self.assertIn('teachers', response.context)
        self.assertIn('students_page', response.context)
        
        # 作成した教師と学生がリスト内に存在することを確認
        teachers_list = response.context['teachers']
        students_page = response.context['students_page']
        self.assertTrue(any(t.id == self.teacher.id for t in teachers_list))
        self.assertTrue(any(s.id == self.student.id for s in students_page.object_list))

    def test_admin_delete_student_success(self):
        # 管理者でログイン
        self.client.login(email='admin_mgr@example.com', password='password123')
        url = reverse('school_management:admin_teacher_management')
        
        # 学生の完全削除をPOSTリクエストで実行
        response = self.client.post(url, {
            'action': 'delete_student',
            'student_id': self.student.id
        })
        # 削除成功後はリダイレクトされること
        self.assertRedirects(response, f"{url}?tab=students")
        
        # DBから完全に削除されているか確認
        self.assertFalse(User.objects.filter(id=self.student.id).exists())

    def test_non_admin_delete_student_denied(self):
        # 教員（非管理者）でログイン
        self.client.login(email='teacher_mgr@example.com', password='password123')
        url = reverse('school_management:admin_teacher_management')
        
        # 学生の完全削除をPOSTリクエストで実行
        response = self.client.post(url, {
            'action': 'delete_student',
            'student_id': self.student.id
        })
        # アクセス権限がないため、ダッシュボードへリダイレクトされること
        self.assertRedirects(response, reverse('school_management:dashboard'))
        
        # DB上で学生が削除されていない（生存している）ことを確認
        self.assertTrue(User.objects.filter(id=self.student.id).exists())

    def test_filtering_and_search(self):
        # 管理者でログイン
        self.client.login(email='admin_mgr@example.com', password='password123')
        url = reverse('school_management:admin_teacher_management')

        # 孤立した（担当教員がいない）学生を作成
        orphan_student = User.objects.create_user(
            email='orphan@example.com',
            password='password123',
            full_name='Orphan Student',
            student_number='ORP001',
            role='student'
        )

        # 1. フリーワード検索テスト ('MGR')
        response = self.client.get(url, {'search': 'MGR', 'tab': 'students'})
        self.assertEqual(response.status_code, 200)
        students = response.context['students_page'].object_list
        self.assertTrue(any(s.id == self.student.id for s in students))
        self.assertFalse(any(s.id == orphan_student.id for s in students))
        self.assertEqual(response.context['filtered_students_count'], 1)
        self.assertTrue(response.context['has_filter'])

        # 2. 教員フィルタテスト (self.teacher.id)
        response = self.client.get(url, {'teacher_id': self.teacher.id, 'tab': 'students'})
        self.assertEqual(response.status_code, 200)
        students = response.context['students_page'].object_list
        self.assertTrue(any(s.id == self.student.id for s in students))
        self.assertFalse(any(s.id == orphan_student.id for s in students))
        self.assertEqual(response.context['filtered_students_count'], 1)
        self.assertTrue(response.context['has_filter'])

        # 3. 孤立学生フィルタテスト (orphan_only='on')
        response = self.client.get(url, {'orphan_only': 'on', 'tab': 'students'})
        self.assertEqual(response.status_code, 200)
        students = response.context['students_page'].object_list
        self.assertFalse(any(s.id == self.student.id for s in students))
        self.assertTrue(any(s.id == orphan_student.id for s in students))
        self.assertEqual(response.context['filtered_students_count'], 1)
        self.assertTrue(response.context['has_filter'])

    def test_pagination(self):
        # 管理者でログイン
        self.client.login(email='admin_mgr@example.com', password='password123')
        url = reverse('school_management:admin_teacher_management')

        # さらに51名の学生を登録（合計52名）
        for i in range(51):
            User.objects.create_user(
                email=f'pagestudent_{i}@example.com',
                password='password123',
                full_name=f'Page Student {i}',
                student_number=f'PAGE{i:03d}',
                role='student'
            )

        # 1ページ目は50件表示されること
        response = self.client.get(url, {'tab': 'students', 'page': 1})
        self.assertEqual(response.status_code, 200)
        students_page = response.context['students_page']
        self.assertEqual(len(students_page.object_list), 50)
        self.assertTrue(students_page.has_next())

        # 2ページ目は2件表示されること
        response = self.client.get(url, {'tab': 'students', 'page': 2})
        self.assertEqual(response.status_code, 200)
        students_page = response.context['students_page']
        self.assertEqual(len(students_page.object_list), 2)
        self.assertFalse(students_page.has_next())

    def test_bulk_delete_students_success(self):
        # 管理者でログイン
        self.client.login(email='admin_mgr@example.com', password='password123')
        url = reverse('school_management:admin_teacher_management')

        # さらに2名学生を作成
        student2 = User.objects.create_user(
            email='student2@example.com',
            password='password123',
            full_name='Student 2',
            student_number='STU002',
            role='student'
        )
        student3 = User.objects.create_user(
            email='student3@example.com',
            password='password123',
            full_name='Student 3',
            student_number='STU003',
            role='student'
        )

        # self.student と student2 を一括削除
        response = self.client.post(url, {
            'action': 'bulk_delete_students',
            'selected_student_ids': [self.student.id, student2.id]
        })
        self.assertRedirects(response, f"{url}?tab=students")

        # 削除されたことを確認
        self.assertFalse(User.objects.filter(id=self.student.id).exists())
        self.assertFalse(User.objects.filter(id=student2.id).exists())
        # 選択しなかった学生は存在することを確認
        self.assertTrue(User.objects.filter(id=student3.id).exists())

    def test_bulk_delete_students_denied_for_non_admin(self):
        # 教員（非管理者）でログイン
        self.client.login(email='teacher_mgr@example.com', password='password123')
        url = reverse('school_management:admin_teacher_management')

        student2 = User.objects.create_user(
            email='student2@example.com',
            password='password123',
            full_name='Student 2',
            student_number='STU002',
            role='student'
        )

        # 一括削除を試みる
        response = self.client.post(url, {
            'action': 'bulk_delete_students',
            'selected_student_ids': [self.student.id, student2.id]
        })
        self.assertRedirects(response, reverse('school_management:dashboard'))

        # 学生が削除されていないことを確認
        self.assertTrue(User.objects.filter(id=self.student.id).exists())
        self.assertTrue(User.objects.filter(id=student2.id).exists())

    def test_bulk_delete_select_all_without_exclusions(self):
        self.client.login(email='admin_mgr@example.com', password='password123')
        url = reverse('school_management:admin_teacher_management')

        # さらに3名の学生を作成（合計4名）
        for i in range(3):
            User.objects.create_user(
                email=f'bulk_stu_{i}@example.com',
                password='password123',
                full_name=f'Bulk Student {i}',
                student_number=f'BLK{i:03d}',
                role='student'
            )

        # 全学生を一括削除（フィルタなし、除外なし）
        response = self.client.post(url, {
            'action': 'bulk_delete_students',
            'select_all': 'true'
        })
        self.assertRedirects(response, f"{url}?tab=students")

        # すべての学生が削除されていることを確認
        self.assertEqual(User.objects.filter(role='student').count(), 0)

    def test_bulk_delete_select_all_with_exclusions(self):
        self.client.login(email='admin_mgr@example.com', password='password123')
        url = reverse('school_management:admin_teacher_management')

        # さらに3名の学生を作成（合計4名）
        students = []
        for i in range(3):
            s = User.objects.create_user(
                email=f'bulk_stu_{i}@example.com',
                password='password123',
                full_name=f'Bulk Student {i}',
                student_number=f'BLK{i:03d}',
                role='student'
            )
            students.append(s)

        # self.student と students[1] を除外して、全学生を一括削除
        response = self.client.post(url, {
            'action': 'bulk_delete_students',
            'select_all': 'true',
            'deselected_student_ids': [self.student.id, students[1].id]
        })
        self.assertRedirects(response, f"{url}?tab=students")

        # 除外した学生のみが存在することを確認
        remaining_students = User.objects.filter(role='student')
        self.assertEqual(remaining_students.count(), 2)
        remaining_ids = [s.id for s in remaining_students]
        self.assertIn(self.student.id, remaining_ids)
        self.assertIn(students[1].id, remaining_ids)
        self.assertNotIn(students[0].id, remaining_ids)
        self.assertNotIn(students[2].id, remaining_ids)
