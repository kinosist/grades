import json
from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from school_management.models import (
    ClassRoom, Student, LessonSession, PointColumn, StudentColumnScore,
    StudentQRCode, QRCodeScan, StudentClassPoints, Quiz, QuizScore, ClassRoomEnrollment
)

User = get_user_model()

class CustomColumnLogicTests(TestCase):
    def setUp(self):
        self.client = Client()
        # 先生ユーザーの作成
        self.teacher = User.objects.create_user(
            email="teacher@example.com",
            password="password",
            role="teacher",
            full_name="テスト教員"
        )
        # 他の教員（権限なしテスト用）
        self.other_teacher = User.objects.create_user(
            email="other@example.com",
            password="password",
            role="teacher",
            full_name="他の教員"
        )

        self.classroom = ClassRoom.objects.create(
            class_name="テストクラス",
            year=2024,
            semester="first"
        )
        self.classroom.teachers.add(self.teacher)

        self.session = LessonSession.objects.create(
            classroom=self.classroom,
            session_number=1,
            has_peer_evaluation=False
        )

        self.student = Student.objects.create_user(
            email="student@example.com",
            password="password",
            full_name="テスト学生",
            role="student"
        )
        ClassRoomEnrollment.enroll(self.classroom, self.student)
        
        # QRコードの作成
        self.qr_code = StudentQRCode.objects.create(student=self.student)

        # 独自評価項目の作成
        self.column1 = PointColumn.objects.create(classroom=self.classroom, column_title="発言点")
        self.column2 = PointColumn.objects.create(classroom=self.classroom, column_title="小テストボーナス")

        # ログイン
        self.client.login(email="teacher@example.com", password="password")

    def test_add_custom_column_points_api_success(self):
        """API経由での授業回指定加点（正常系）"""
        url = reverse('school_management:add_custom_column_points', args=[self.classroom.id])
        data = {
            'student_id': self.student.id,
            'column_id': self.column1.id,
            'session_id': self.session.id,
            'points': 15
        }
        response = self.client.post(url, data=json.dumps(data), content_type='application/json')
        if response.status_code == 400:
            print("ERROR MESSAGE:", response.json().get('message'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['success'], True)

        score_obj = StudentColumnScore.objects.get(student=self.student, column=self.column1)
        self.assertEqual(score_obj.score, 15)

        # 追加加点は累計されること（合計を上書きするのではなく積み上げる）
        data['points'] = 20
        response = self.client.post(url, data=json.dumps(data), content_type='application/json')
        score_obj.refresh_from_db()
        self.assertEqual(score_obj.score, 35)

    def test_add_custom_column_points_api_unauthorized(self):
        """API経由での加点（権限なしエラー）"""
        # 他の教員でログイン
        self.client.login(email="other@example.com", password="password")
        url = reverse('school_management:add_custom_column_points', args=[self.classroom.id])
        data = {
            'student_id': self.student.id,
            'column_id': self.column1.id,
            'session_id': self.session.id,
            'points': 15
        }
        # この教員はclassroomの担当ではないため例外が発生し400エラーになる想定
        response = self.client.post(url, data=json.dumps(data), content_type='application/json')
        self.assertEqual(response.status_code, 400)

    def test_add_custom_column_points_rejects_out_of_range(self):
        """加点は1〜100の範囲外だとエラーになること"""
        url = reverse('school_management:add_custom_column_points', args=[self.classroom.id])

        for invalid_points in [-5, 0, 101]:
            response = self.client.post(url, data=json.dumps({
                'student_id': self.student.id,
                'column_id': self.column1.id,
                'session_id': self.session.id,
                'points': invalid_points,
            }), content_type='application/json')
            self.assertEqual(response.status_code, 400, f"points={invalid_points} は拒否されるべき")
            self.assertFalse(response.json().get('success', False))

    def test_qr_scan_custom_column_addition(self):
        """QRスキャンによるスコア加算"""
        url = reverse('school_management:qr_code_scan', args=[self.qr_code.qr_code_id])
        
        # セッションと加算対象を指定
        data = {
            'session_id': self.session.id,
            'point_type': f'custom_{self.column1.id}',
            'points': 5
        }
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 200) # Renders success message

        # スコアが加算されたか確認
        score_obj = StudentColumnScore.objects.get(student=self.student, column=self.column1)
        self.assertEqual(score_obj.score, 5)

        # もう一度スキャンして加算
        data['points'] = 3
        self.client.post(url, data)
        score_obj.refresh_from_db()
        self.assertEqual(score_obj.score, 8)
        
        # 履歴が作成されたか確認
        scans = QRCodeScan.objects.filter(qr_code=self.qr_code, point_column=self.column1)
        self.assertEqual(scans.count(), 2)

    def test_qr_scan_deletion_decrements_score(self):
        """QRスキャン削除によるスコア減算"""
        # 初期のスコア作成
        StudentColumnScore.objects.create(student=self.student, column=self.column1, score=10)
        
        # スキャン履歴を作成 (5点の加算とみなす履歴)
        scan = QRCodeScan.objects.create(
            qr_code=self.qr_code,
            scanned_by=self.teacher,
            lesson_session=self.session,
            point_column=self.column1,
            points_awarded=5
        )

        url = reverse('school_management:delete_qr_scan', args=[scan.id])
        response = self.client.post(url)
        self.assertEqual(response.status_code, 302) # redirect

        # スコアが減算されたか確認
        score_obj = StudentColumnScore.objects.get(student=self.student, column=self.column1)
        self.assertEqual(score_obj.score, 5)

    def test_bulk_delete_qr_scans(self):
        """QRスキャンの一括削除によるスコア減算"""
        StudentColumnScore.objects.create(student=self.student, column=self.column1, score=15)
        
        scan1 = QRCodeScan.objects.create(qr_code=self.qr_code, scanned_by=self.teacher, point_column=self.column1, points_awarded=3)
        scan2 = QRCodeScan.objects.create(qr_code=self.qr_code, scanned_by=self.teacher, point_column=self.column1, points_awarded=4)

        url = reverse('school_management:bulk_delete_qr_scans', args=[self.student.id])
        response = self.client.post(url, data={'scan_ids': [scan1.id, scan2.id]})
        self.assertEqual(response.status_code, 302)

        # スコアが減算されたか確認 (15 - 3 - 4 = 8)
        score_obj = StudentColumnScore.objects.get(student=self.student, column=self.column1)
        self.assertEqual(score_obj.score, 8)

    def test_activity_points_aggregation(self):
        """総合ポイントの集計ロジック確認"""
        # column1: 10点, column2: 5点
        StudentColumnScore.objects.create(student=self.student, column=self.column1, score=10)
        StudentColumnScore.objects.create(student=self.student, column=self.column2, score=5)
        
        scp, _ = StudentClassPoints.objects.get_or_create(student=self.student, classroom=self.classroom)
        
        # まだ他のポイントがないので、独自項目の合計 15点 のはず
        self.assertEqual(scp.get_activity_points(), 15)

        # 小テストのポイントを追加してみる (10点)
        quiz = Quiz.objects.create(lesson_session=self.session, quiz_name="小テスト1", max_score=10)
        QuizScore.objects.create(student=self.student, quiz=quiz, score=10, graded_by=self.teacher)
        
        # 独自(15) + 小テスト(10) = 25点
        self.assertEqual(scp.get_activity_points(), 25)
