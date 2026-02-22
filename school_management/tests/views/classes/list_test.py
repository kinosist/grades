from django.test import TestCase
from django.urls import reverse
from django.contrib.auth import get_user_model
from school_management.models import ClassRoom

User = get_user_model()

class ClassListViewTest(TestCase):
    def setUp(self):
        # 1. ユーザー作成
        self.teacher = User.objects.create_user(
            email='teacher@example.com',
            full_name='教員 A',
            password='password123'
        )
        self.other_teacher = User.objects.create_user(
            email='other@example.com',
            full_name='教員 B',
            password='password123'
        )
        
        # 2. クラス作成 (自分用と他人用)
        self.my_class = ClassRoom.objects.create(
            class_name="自分の担当クラス",
            year=2026
        )
        self.my_class.teachers.add(self.teacher)
        
        self.other_class = ClassRoom.objects.create(
            class_name="他人の担当クラス",
            year=2026
        )
        self.other_class.teachers.add(self.other_teacher)
        
        self.url = reverse('school_management:class_list')

    def test_login_required(self):
        """ログインしていない場合はログイン画面へリダイレクト"""
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login/', response.url)

    def test_class_list_filtering(self):
        """ログイン中の教員が担当するクラスのみが表示されるか"""
        self.client.login(email='teacher@example.com', password='password123')
        response = self.client.get(self.url)
        
        self.assertEqual(response.status_code, 200)
        
        # 自分のクラスは含まれているべき
        self.assertIn(self.my_class, response.context['classes'])
        # 他人のクラスは含まれていてはいけない (フィルタリングの検証)
        self.assertNotIn(self.other_class, response.context['classes'])

    def test_template_used(self):
        """正しいテンプレートが使用されているか"""
        self.client.login(email='teacher@example.com', password='password123')
        response = self.client.get(self.url)
        self.assertTemplateUsed(response, 'school_management/class_list.html')
