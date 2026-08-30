import csv
import io
from datetime import date

from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model

from school_management.models import (
    ClassRoom, LessonSession, Quiz, QuizScore,
    ClassRoomEnrollment, TeacherStudentAssignment,
    PointColumn, StudentColumnScore, QRCodeScan, StudentQRCode,
)

User = get_user_model()


class ClassEvaluationCsvExportTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.teacher = User.objects.create_user(
            email='csv_teacher@example.com',
            password='password123',
            full_name='CSV Teacher',
            role='teacher'
        )
        self.other_teacher = User.objects.create_user(
            email='csv_other_teacher@example.com',
            password='password123',
            full_name='Other Teacher',
            role='teacher'
        )
        self.student1 = User.objects.create_user(
            email='csv_student1@example.com',
            password='password123',
            full_name='学生1',
            furigana='ガクセイイチ',
            role='student',
            student_number='CSV001'
        )
        self.student2 = User.objects.create_user(
            email='csv_student2@example.com',
            password='password123',
            full_name='学生2',
            furigana='ガクセイニ',
            role='student',
            student_number='CSV002'
        )

        self.classroom = ClassRoom.objects.create(
            class_name='CSV Export Test Class',
            year=2026,
            semester='first',
            grading_system='default'
        )
        self.classroom.teachers.add(self.teacher)
        ClassRoomEnrollment.enroll(self.classroom, self.student1)
        ClassRoomEnrollment.enroll(self.classroom, self.student2)
        TeacherStudentAssignment.assign(self.teacher, self.student1)
        TeacherStudentAssignment.assign(self.teacher, self.student2)

        self.session1 = LessonSession.objects.create(
            classroom=self.classroom, session_number=1, date=date(2026, 4, 1)
        )
        self.session2 = LessonSession.objects.create(
            classroom=self.classroom, session_number=2, date=date(2026, 4, 8)
        )

        quiz = Quiz.objects.create(lesson_session=self.session1, quiz_name='小テスト1', max_score=10, is_qr_linked=False)
        QuizScore.objects.create(student=self.student1, quiz=quiz, score=10, graded_by=self.teacher)

        self.point_column = PointColumn.objects.create(classroom=self.classroom, column_title='電卓検定')
        qr_code, _ = StudentQRCode.objects.get_or_create(student=self.student1, defaults={'is_active': True})
        QRCodeScan.objects.create(
            qr_code=qr_code,
            scanned_by=self.teacher,
            lesson_session=self.session1,
            point_column=self.point_column,
            points_awarded=5,
        )
        StudentColumnScore.objects.create(student=self.student1, column=self.point_column, score=5)

        self.client.force_login(self.teacher)

    def _get_csv_rows(self, response):
        content = response.content.decode('utf-8-sig')
        return list(csv.reader(io.StringIO(content)))

    def test_simple_mode_returns_one_row_per_student(self):
        url = reverse('school_management:class_evaluation_csv_export', args=[self.classroom.id]) + '?mode=simple'
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertIn('text/csv', response['Content-Type'])

        rows = self._get_csv_rows(response)
        header, data_rows = rows[0], rows[1:]

        self.assertEqual(header[:3], ['学籍番号', '氏名', 'フリガナ'])
        # default（通常）モードでは「合計」の1列のみで、100点換算・足切りの列は出さない
        self.assertIn('合計', header)
        self.assertNotIn('最終成績(100点換算)', header)
        self.assertNotIn('足切り', header)
        # 独自評価項目は画面と同じ列名（接頭辞なし）で出す
        self.assertIn('電卓検定', header)
        # 1行 = 1学生 なので、学生数と行数が一致する
        self.assertEqual(len(data_rows), 2)
        student_numbers = {row[0] for row in data_rows}
        self.assertEqual(student_numbers, {'CSV001', 'CSV002'})

    def test_original_grading_system_includes_final_score_and_cutoff_columns(self):
        self.classroom.grading_system = 'original'
        self.classroom.save()

        url = reverse('school_management:class_evaluation_csv_export', args=[self.classroom.id]) + '?mode=simple'
        response = self.client.get(url)
        rows = self._get_csv_rows(response)
        header = rows[0]

        self.assertIn('最終成績(100点換算)', header)
        self.assertIn('素点', header)
        self.assertIn('足切り', header)
        self.assertNotIn('合計', header)

    def test_detail_mode_returns_one_row_per_student(self):
        """1学生1行のまま、授業回ごとの内訳が列として横に展開されること"""
        url = reverse('school_management:class_evaluation_csv_export', args=[self.classroom.id]) + '?mode=detail'
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        rows = self._get_csv_rows(response)
        header, data_rows = rows[0], rows[1:]

        # 授業回数(2) × 独自評価項目(1) を含む列が生成されているか確認
        self.assertIn('第1回_小テスト点', header)
        self.assertIn('第2回_小テスト点', header)
        self.assertIn('第1回_電卓検定', header)
        self.assertIn('第2回_電卓検定', header)

        # 1行 = 1学生 なので、複数回の点数が入っても学生数(2)のまま行数は増えない
        self.assertEqual(len(data_rows), 2)

        student_number_col = header.index('学籍番号')
        quiz_col1 = header.index('第1回_小テスト点')
        custom_col1 = header.index('第1回_電卓検定')

        student1_row = next(row for row in data_rows if row[student_number_col] == 'CSV001')
        self.assertEqual(student1_row[quiz_col1], '10')
        self.assertEqual(student1_row[custom_col1], '5')

        # ピア評価の内訳は貢献点・投票点のみ。合計とテストモードの記録は含めない
        self.assertIn('第1回_ピア貢献', header)
        self.assertIn('第1回_ピア投票', header)
        self.assertNotIn('第1回_ピア評価点', header)
        self.assertNotIn('第1回_シミュレーション', header)

    def test_no_merged_or_blank_placeholder_cells(self):
        """1学生1行の中で、値が入っていないセルは空文字ではなく0で埋まる"""
        url = reverse('school_management:class_evaluation_csv_export', args=[self.classroom.id]) + '?mode=detail'
        response = self.client.get(url)
        rows = self._get_csv_rows(response)
        header, data_rows = rows[0], rows[1:]

        name_col = header.index('氏名')
        quiz_col2 = header.index('第2回_小テスト点')
        for row in data_rows:
            self.assertNotEqual(row[name_col], '')
        # 第2回に小テストが無い学生でも、空欄ではなく0が入る
        student1_row = next(row for row in data_rows if row[header.index('学籍番号')] == 'CSV001')
        self.assertEqual(student1_row[quiz_col2], '0')

    def test_other_teacher_cannot_access(self):
        self.client.force_login(self.other_teacher)
        url = reverse('school_management:class_evaluation_csv_export', args=[self.classroom.id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)

    def test_invalid_mode_falls_back_to_detail(self):
        url = reverse('school_management:class_evaluation_csv_export', args=[self.classroom.id]) + '?mode=invalid'
        response = self.client.get(url)
        rows = self._get_csv_rows(response)
        header = rows[0]
        self.assertIn('第1回_小テスト点', header)
