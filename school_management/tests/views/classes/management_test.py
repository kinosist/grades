from django.test import TestCase
from django.urls import reverse
from django.contrib.auth import get_user_model
from school_management.models import ClassRoom

User = get_user_model()

class ClassManagementViewTest(TestCase):
    def setUp(self):
        # 1. テスト用ユーザーの作成
        self.teacher = User.objects.create_user(
            email='teacher@example.com',
            full_name='教員 太郎',
            password='password123'
        )
        self.other_teacher = User.objects.create_user(
            email='other@example.com',
            full_name='他教員',
            password='password123'
        )
        
        # URLの準備（urls.pyのnameに合わせてください）
        self.create_url = reverse('school_management:class_create')
        self.list_url = reverse('school_management:class_list')

    # --- class_create_view のテスト ---

    def test_create_class_success(self):
        """POSTリクエストでクラスが作成され、自分が担当者になるか"""
        self.client.login(email='teacher@example.com', password='password123')
        data = {
            'class_name': 'Django管理クラス',
            'year': '2026',
            'semester': '前期'
        }
        response = self.client.post(self.create_url, data)
        
        # 一覧画面へリダイレクト
        self.assertRedirects(response, self.list_url)
        # DBに保存されているか
        classroom = ClassRoom.objects.get(class_name='Django管理クラス')
        # teachers.add(request.user) が機能しているか
        self.assertIn(self.teacher, classroom.teachers.all())

    def test_create_class_invalid_year(self):
        """年度に数値以外が入った場合にValueErrorをキャッチしてエラーを出すか"""
        self.client.login(email='teacher@example.com', password='password123')
        data = {
            'class_name': '失敗クラス',
            'year': 'InvalidYear', # 数値以外
            'semester': '1'
        }
        response = self.client.post(self.create_url, data)
        
        # リダイレクトせず200を返す（メッセージを表示して元の画面に留まる）
        self.assertEqual(response.status_code, 200)
        # DBに作成されていないこと
        self.assertFalse(ClassRoom.objects.filter(class_name='失敗クラス').exists())

    # --- class_delete_view のテスト ---

    def test_delete_class_success(self):
        """担当教員本人がリクエストした場合に削除できるか"""
        # 削除対象の作成
        classroom = ClassRoom.objects.create(class_name="削除対象", year=2026, semester="1")
        classroom.teachers.add(self.teacher)
        delete_url = reverse('school_management:class_delete', kwargs={'class_id': classroom.id})

        self.client.login(email='teacher@example.com', password='password123')
        # @require_POST なので post で送る
        response = self.client.post(delete_url)

        self.assertRedirects(response, self.list_url)
        self.assertFalse(ClassRoom.objects.filter(id=classroom.id).exists())

    def test_delete_class_denied_for_other_teacher(self):
        """担当外の教員が削除を試みた場合に404になるか（セキュリティ）"""
        # 他人のクラスを作成
        classroom = ClassRoom.objects.create(class_name="他人のクラス", year=2026, semester="1")
        classroom.teachers.add(self.other_teacher)
        delete_url = reverse('school_management:class_delete', kwargs={'class_id': classroom.id})

        self.client.login(email='teacher@example.com', password='password123')
        response = self.client.post(delete_url)

        # get_object_or_404(..., teachers=request.user) なので 404
        self.assertEqual(response.status_code, 404)
        # DBに残っていること
        self.assertTrue(ClassRoom.objects.filter(id=classroom.id).exists())

    def test_delete_get_not_allowed(self):
        """GETリクエストによる削除が @require_POST で拒否されるか"""
        classroom = ClassRoom.objects.create(class_name="安全なクラス", year=2026, semester="1")
        classroom.teachers.add(self.teacher)
        delete_url = reverse('school_management:class_delete', kwargs={'class_id': classroom.id})

        self.client.login(email='teacher@example.com', password='password123')
        response = self.client.get(delete_url)

        # 405 Method Not Allowed
        self.assertEqual(response.status_code, 405)
        self.assertTrue(ClassRoom.objects.filter(id=classroom.id).exists())
