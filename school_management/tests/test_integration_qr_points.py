from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from school_management.models import (
    ClassRoom, StudentQRCode, StudentClassPoints,
    PointColumn, StudentColumnScore, QRCodeScan, ClassRoomEnrollment
)
import uuid

User = get_user_model()

class QRAndPointsIntegrationTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.teacher = User.objects.create_user(
            email='teacher_qr@example.com',
            password='password123',
            full_name='Teacher QR',
            role='teacher'
        )
        self.student = User.objects.create_user(
            email='student_qr@example.com',
            password='password123',
            full_name='Student QR',
            role='student',
            student_number='QR001'
        )
        self.classroom = ClassRoom.objects.create(
            class_name='QR Class',
            year=2024,
            semester='first',
            grading_system='custom'
        )
        self.classroom.teachers.add(self.teacher)
        ClassRoomEnrollment.enroll(self.classroom, self.student)
        
        self.scp = StudentClassPoints.objects.create(
            student=self.student,
            classroom=self.classroom,
            points=10
        )
        
        # QRコード作成
        self.qr_code = StudentQRCode.objects.create(
            student=self.student,
            qr_code_id=uuid.uuid4(),
            is_active=True
        )

    def test_qr_scan_flow(self):
        # 1. 教員ログイン
        self.client.login(email='teacher_qr@example.com', password='password123')
        
        # 2. QRスキャン実行
        scan_url = reverse('school_management:qr_code_scan', args=[self.qr_code.qr_code_id])
        # QRスキャン画面へのアクセス
        response = self.client.get(scan_url)
        self.assertEqual(response.status_code, 200)
        
        # QRスキャンからのポイント加算などは通常別のPOSTで行われるか、scan_url自体が処理を行うか？
        # attendance/scan.py などを見ると、scan_urlは学生の詳細画面へリダイレクトすることが多い
        
        # 3. カスタムポイント項目の作成と加算
        add_col_url = reverse('school_management:add_point_column', args=[self.classroom.id])
        response = self.client.post(add_col_url, {
            'column_title': 'Extra Assignment'
        })
        self.assertIn(response.status_code, [200, 302])
        col = PointColumn.objects.get(column_title='Extra Assignment')
        
        # ポイント更新（カスタムポイント）
        update_score_url = reverse('school_management:update_custom_score', args=[self.classroom.id])
        import json
        response = self.client.post(
            update_score_url,
            data=json.dumps({
                'student_id': self.student.id,
                'column_id': col.id,
                'score': 20
            }),
            content_type='application/json',
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        
        self.assertEqual(response.status_code, 200)
        
        # DB確認
        score_record = StudentColumnScore.objects.get(column=col, student=self.student)
        self.assertEqual(score_record.score, 20)
        
        # 4. 通常のポイント加算 (update_student_points)
        update_points_url = reverse('school_management:update_student_points', args=[self.student.id])
        response = self.client.post(
            update_points_url,
            data=json.dumps({
                'points': 15,  # 10 + 5
                'class_id': self.classroom.id
            }),
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, 200)
        
        # 学生の基本ポイントが更新されているか
        self.scp.refresh_from_db()
        self.assertEqual(self.scp.points, 15)
        
        # 5. 学生が自分のダッシュボードでポイントを確認
        self.client.logout()
        self.client.login(email='student_qr@example.com', password='password123')
        
        response = self.client.get(reverse('school_management:student_dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '20') # カスタムポイントなどがコンテキストにあれば表示されるかも？
        self.assertContains(response, 'QR Class')
