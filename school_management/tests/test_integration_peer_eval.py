import json
from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from school_management.models import (
    ClassRoom, LessonSession, Group, GroupMember,
    PeerEvaluationSettings, PeerEvaluation, ClassRoomEnrollment
)

User = get_user_model()

class PeerEvaluationIntegrationTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.teacher = User.objects.create_user(
            email='teacher_pe@example.com',
            password='password123',
            full_name='Teacher PE',
            role='teacher'
        )
        self.student1 = User.objects.create_user(
            email='student1_pe@example.com',
            password='password123',
            full_name='Student1 PE',
            role='student',
            student_number='PE001'
        )
        self.student2 = User.objects.create_user(
            email='student2_pe@example.com',
            password='password123',
            full_name='Student2 PE',
            role='student',
            student_number='PE002'
        )
        self.student3 = User.objects.create_user(
            email='student3_pe@example.com',
            password='password123',
            full_name='Student3 PE',
            role='student',
            student_number='PE003'
        )
        
        self.classroom = ClassRoom.objects.create(
            class_name='PE Class',
            year=2024,
            semester='first'
        )
        self.classroom.teachers.add(self.teacher)
        ClassRoomEnrollment.bulk_enroll(self.classroom, [self.student1, self.student2, self.student3])
        
        self.session = LessonSession.objects.create(
            classroom=self.classroom,
            session_number=1,
            has_peer_evaluation=True,
            peer_evaluation_status=LessonSession.PeerEvaluationStatus.NOT_OPEN
        )

        # グループ作成
        self.group1 = Group.objects.create(lesson_session=self.session, group_name='Group A', group_number=1)
        self.group2 = Group.objects.create(lesson_session=self.session, group_name='Group B', group_number=2)
        
        GroupMember.objects.create(group=self.group1, student=self.student1)
        GroupMember.objects.create(group=self.group1, student=self.student2)
        GroupMember.objects.create(group=self.group2, student=self.student3)

    def test_peer_evaluation_full_flow(self):
        # 1. ピア評価設定の作成 (Teacher)
        self.client.login(email='teacher_pe@example.com', password='password123')
        
        # settingsへのPOST (設定保存)
        settings_url = reverse('school_management:peer_evaluation_settings', args=[self.session.id])
        response = self.client.post(settings_url, {
            'enable_member_evaluation': 'on',
            'member_evaluation_method': 'RANKING',
            'member_scores_json': '[5,3]',
            'member_reason_control': 'OPTIONAL',
            'enable_group_evaluation': 'on',
            'group_evaluation_method': 'RANKING',
            'group_scores_json': '[10,5]',
            'group_reason_control': 'OPTIONAL',
            'show_points': 'on'
        })
        self.assertIn(response.status_code, [200, 302])
        
        # 受付開始
        start_url = reverse('school_management:improved_peer_evaluation_create', args=[self.session.id])
        response = self.client.post(start_url, {'action': 'start'})
        
        # 設定が保存されているか確認
        self.session.refresh_from_db()
        self.assertEqual(self.session.peer_evaluation_status, LessonSession.PeerEvaluationStatus.OPEN)
        self.assertTrue(hasattr(self.session, 'peer_evaluation_settings'))
        
        self.client.logout()
        
        # 2. 学生1がピア評価に回答
        from django.utils import timezone
        import datetime
        from school_management.models import GoogleOAuthSession
        
        # 認証セッションの作成とCookieの設定
        session_id_value = 'test_session_token_123'
        GoogleOAuthSession.objects.create(
            session_id=session_id_value,
            email='student1_pe@example.com',
            expires_at=timezone.now() + datetime.timedelta(hours=1)
        )
        self.client.cookies['peer_eval_session_id'] = session_id_value
        
        self.client.login(email='student1_pe@example.com', password='password123')
        eval_url = reverse('school_management:peer_evaluation_common', args=[self.session.id])
        
        # GETリクエストでフォームが表示されるか
        response = self.client.get(eval_url)
        self.assertEqual(response.status_code, 200)
        
        # POSTリクエストで回答を送信
        response = self.client.post(eval_url, {
            'group_rank_1': str(self.group2.id), # Group B を 1位に
            'member_rank_1': str(self.student2.id), # 同じグループのStudent2に1位
            'general_comment': 'Good job',
            'class_comment': 'Great class'
        })
        
        self.assertIn(response.status_code, [200, 302])
        
        # PeerEvaluation レコードが作られたか
        if not PeerEvaluation.objects.filter(lesson_session=self.session, student=self.student1).exists():
            print(response.content.decode('utf-8'))
        self.assertTrue(PeerEvaluation.objects.filter(lesson_session=self.session, student=self.student1).exists())
        self.client.logout()
        
        # 3. 評価を締め切り
        self.client.login(email='teacher_pe@example.com', password='password123')
        close_url = reverse('school_management:close_peer_evaluation', args=[self.session.id])
        response = self.client.post(close_url)
        
        self.session.refresh_from_db()
        self.assertEqual(self.session.peer_evaluation_status, LessonSession.PeerEvaluationStatus.CLOSED)
        
        # 4. 成績確認 (class_evaluation_view)
        class_eval_url = reverse('school_management:class_evaluation', args=[self.classroom.id])
        response = self.client.get(class_eval_url)
        self.assertEqual(response.status_code, 200)
        
        # コンテキストに成績データが含まれているか
        student_evaluations = response.context.get('student_evaluations')
        self.assertIsNotNone(student_evaluations)
        
        # Student2がStudent1からの評価を受け取っているかなどをチェック
        found_student2 = False
        for s in student_evaluations:
            if s['student'].id == self.student2.id:
                found_student2 = True
        self.assertTrue(found_student2)
