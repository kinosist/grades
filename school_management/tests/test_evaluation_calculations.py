import json
import uuid
from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from school_management.models import (
    ClassRoom, LessonSession, Quiz, QuizScore, StudentClassPoints,
    StudentColumnScore, PointColumn, StudentLessonPoints, Group,
    GroupMember, PeerEvaluation, PeerEvaluationSettings, StudentGoal,
    SelfEvaluation, ClassRoomEnrollment, TeacherStudentAssignment
)
from datetime import date

User = get_user_model()

class EvaluationCalculationTests(TestCase):
    def setUp(self):
        self.client = Client()
        # Create users
        self.teacher = User.objects.create_user(
            email='teacher_calc@example.com',
            password='password123',
            full_name='Teacher Calc',
            role='teacher'
        )
        self.student = User.objects.create_user(
            email='student_calc@example.com',
            password='password123',
            full_name='Student Calc',
            role='student',
            student_number='CALC001'
        )
        # Create classroom
        self.classroom = ClassRoom.objects.create(
            class_name='Calculation Test Class',
            year=2026,
            semester='first',
            grading_system='default'
        )
        self.classroom.teachers.add(self.teacher)
        ClassRoomEnrollment.enroll(self.classroom, self.student)
        TeacherStudentAssignment.assign(self.teacher, self.student)
        
        
        # Create session
        self.session = LessonSession.objects.create(
            classroom=self.classroom,
            session_number=1,
            date=date.today(),
            has_quiz=True,
            has_peer_evaluation=True
        )
        
        # Login teacher
        self.client.force_login(self.teacher)

    def test_quiz_stats_aggregation_and_duplicates(self):
        """小テストの統計集計（重複排除を含む）の検証"""
        scp, _ = StudentClassPoints.objects.get_or_create(student=self.student, classroom=self.classroom)
        
        # 1. 0件のケース（未受託）
        stats = scp.quiz_stats
        self.assertEqual(stats['count'], 0)
        self.assertEqual(stats['average'], 0)
        
        # 2. 1件のケース (10点)
        quiz1 = Quiz.objects.create(lesson_session=self.session, quiz_name='Quiz 1', max_score=10)
        qs1 = QuizScore.objects.create(student=self.student, quiz=quiz1, score=8, graded_by=self.teacher)
        
        stats = scp.quiz_stats
        self.assertEqual(stats['count'], 1)
        self.assertEqual(stats['average'], 8.0)
        
        # 3. 複数件のケース & 重複排除（同じクイズの再採点は最新のみ採用）
        # 同一クイズに別の点数を追加
        qs2 = QuizScore.objects.create(student=self.student, quiz=quiz1, score=10, graded_by=self.teacher)
        
        stats = scp.quiz_stats
        # クイズ数は1のまま、点数は最新の10点になるはず
        self.assertEqual(stats['count'], 1)
        self.assertEqual(stats['average'], 10.0)
        
        # 別のクイズを追加
        quiz2 = Quiz.objects.create(lesson_session=self.session, quiz_name='Quiz 2', max_score=20)
        qs3 = QuizScore.objects.create(student=self.student, quiz=quiz2, score=15, graded_by=self.teacher)
        
        stats = scp.quiz_stats
        self.assertEqual(stats['count'], 2)
        # 平均点: (10 + 15) / 2 = 12.5
        self.assertEqual(stats['average'], 12.5)

    def test_quiz_percentage_division_by_zero(self):
        """満点(max_score)が0点の場合にゼロ除算エラーが発生しないことを確認"""
        quiz = Quiz.objects.create(lesson_session=self.session, quiz_name='Zero Max Quiz', max_score=0)
        qs = QuizScore.objects.create(student=self.student, quiz=quiz, score=0, graded_by=self.teacher)
        
        # percentageプロパティが安全に0を返すことを検証
        self.assertEqual(qs.percentage, 0)

    def test_cancelled_quiz_scores_excluded(self):
        """取り消し済み(is_cancelled=True)の小テストスコアが計算から除外されることの検証"""
        scp, _ = StudentClassPoints.objects.get_or_create(student=self.student, classroom=self.classroom)
        quiz = Quiz.objects.create(lesson_session=self.session, quiz_name='Quiz', max_score=10)
        
        # 正常なスコア
        QuizScore.objects.create(student=self.student, quiz=quiz, score=9, graded_by=self.teacher)
        
        # 取り消し済みスコア (より新しい時間)
        QuizScore.objects.create(student=self.student, quiz=quiz, score=5, graded_by=self.teacher, is_cancelled=True)
        
        # 取り消し済みスコアが除外され、正常な9点のみが計算対象になること
        stats = scp.quiz_stats
        self.assertEqual(stats['count'], 1)
        self.assertEqual(stats['average'], 9.0)

    def test_peer_eval_stats_direct_method(self):
        """ピア評価の直接付与方式での統計・得点計算の検証"""
        scp, _ = StudentClassPoints.objects.get_or_create(student=self.student, classroom=self.classroom)
        
        # 1. ピア評価設定の作成
        pe_settings = PeerEvaluationSettings.objects.create(
            lesson_session=self.session,
            enable_group_evaluation=True,
            group_scores=[10, 5, 2],  # 1位10点、2位5点、3位2点
            enable_member_evaluation=False,
            evaluation_method=PeerEvaluationSettings.EvaluationMethod.DIRECT
        )
        
        # 2. グループおよびメンバーシップの作成
        group1 = Group.objects.create(lesson_session=self.session, group_number=1)
        group2 = Group.objects.create(lesson_session=self.session, group_number=2)
        GroupMember.objects.create(student=self.student, group=group1, role='member')
        
        # 3. ピア評価の作成 (group1が2位(=5点)を獲得した投票)
        PeerEvaluation.objects.create(
            lesson_session=self.session,
            evaluator_group=group2,
            evaluator_token=uuid.uuid4(),
            response_json={
                'other_group_eval': [
                    {'group_id': group1.id, 'rank': 2}
                ]
            }
        )
        
        # 4. 貢献度評価 (メンバー評価)
        eval_obj = PeerEvaluation.objects.create(
            lesson_session=self.session,
            evaluator_group=group2,
            evaluator_token=uuid.uuid4(),
            response_json={}
        )
        from school_management.models import ContributionEvaluation
        ContributionEvaluation.objects.create(
            peer_evaluation=eval_obj,
            evaluatee=self.student,
            contribution_score=4  # 貢献度4点
        )
        
        # 5. ピア評価統計の検証
        peer_stats = scp.peer_eval_stats
        # 合計点: 貢献度点(4) + 投票点(5) = 9点
        self.assertEqual(peer_stats['total'], 9)
        self.assertEqual(peer_stats['count'], 1)

    def test_peer_eval_stats_aggregate_method(self):
        """ピア評価の集計付与方式（締切時のみ配点）での統計・得点計算の検証"""
        scp, _ = StudentClassPoints.objects.get_or_create(student=self.student, classroom=self.classroom)
        
        # 1. ピア評価設定の作成 (集計付与方式)
        pe_settings = PeerEvaluationSettings.objects.create(
            lesson_session=self.session,
            enable_group_evaluation=True,
            group_scores=[10, 5],
            enable_member_evaluation=False,
            evaluation_method=PeerEvaluationSettings.EvaluationMethod.DIRECT,
            group_evaluation_method=PeerEvaluationSettings.EvaluationMethod.AGGREGATE
        )
        
        # 2. グループおよびメンバーシップ
        group1 = Group.objects.create(lesson_session=self.session, group_number=1)
        group2 = Group.objects.create(lesson_session=self.session, group_number=2)
        GroupMember.objects.create(student=self.student, group=group1, role='member')
        
        # 3. ピア評価 (受付中状態では集計されない)
        self.session.peer_evaluation_status = LessonSession.PeerEvaluationStatus.OPEN
        self.session.save()
        
        PeerEvaluation.objects.create(
            lesson_session=self.session,
            evaluator_group=group2,
            evaluator_token=uuid.uuid4(),
            response_json={
                'other_group_eval': [
                    {'group_id': group1.id, 'rank': 1}  # group1が1位(=10点)
                ]
            }
        )
        
        # 受付中状態なので、集計点数は0
        self.assertEqual(scp._calculate_group_vote_points(), 0)
        
        # 4. ステータスを「締切」に変更
        self.session.peer_evaluation_status = LessonSession.PeerEvaluationStatus.CLOSED
        self.session.save()
        
        # 締切後は1位の配点(10点)が反映される
        self.assertEqual(scp._calculate_group_vote_points(), 10)

    def test_overall_points_standard_grading(self):
        """通常評価システム（default）における総合点計算式の検証"""
        scp, _ = StudentClassPoints.objects.get_or_create(
            student=self.student,
            classroom=self.classroom,
            attendance_points=10.0
        )
        
        # データ設定
        # 1. 小テスト (8点)
        quiz = Quiz.objects.create(lesson_session=self.session, quiz_name='Quiz', max_score=10)
        QuizScore.objects.create(student=self.student, quiz=quiz, score=8, graded_by=self.teacher)
        
        # 2. 授業内ポイント (5点)
        StudentLessonPoints.objects.create(student=self.student, lesson_session=self.session, points=5)
        
        # 3. 独自項目ポイント (3点)
        column = PointColumn.objects.create(classroom=self.classroom, column_title='Bonus Column')
        StudentColumnScore.objects.create(student=self.student, column=column, score=3)
        
        # 計算を実行
        scp.calculate_points_internal()
        scp.save()
        
        # 期待値: (小テスト(8) + ピア評価(0) + 授業ポイント(5) + 独自ポイント(3)) * 2 + 出席点(10)
        # = 16 * 2 + 10 = 42
        self.assertEqual(scp.points, 42)

    def test_overall_points_goal_grading(self):
        """目標管理モード（goal）における総合点計算式の検証"""
        self.classroom.grading_system = 'goal'
        self.classroom.save()
        
        scp, _ = StudentClassPoints.objects.get_or_create(
            student=self.student,
            classroom=self.classroom,
            attendance_points=15.0
        )
        
        # 講師評価点の設定
        SelfEvaluation.objects.create(
            student=self.student,
            classroom=self.classroom,
            teacher_score=80
        )
        
        # 計算を実行
        scp.calculate_points_internal()
        scp.save()
        
        # 期待値: 講師評価点(80) + 出席点(15) = 95
        self.assertEqual(scp.points, 95)

    def test_float_attendance_points_rounding(self):
        """出席点に小数が含まれる場合の四捨五入/丸め処理の検証"""
        scp, _ = StudentClassPoints.objects.get_or_create(
            student=self.student,
            classroom=self.classroom,
            attendance_points=12.5
        )
        # 小テスト (7点)
        quiz = Quiz.objects.create(lesson_session=self.session, quiz_name='Quiz', max_score=10)
        QuizScore.objects.create(student=self.student, quiz=quiz, score=7, graded_by=self.teacher)
        
        scp.calculate_points_internal()
        # 期待値: int( (7 * 2) + 12.5 ) = int(14 + 12.5) = 26
        self.assertEqual(scp.points, 26)

    def test_null_missing_data_safe(self):
        """データが完全に欠損（または未入力）状態での安全性の検証"""
        # クラスポイントのみ作成し、スコア等は一切存在しない状態
        scp, _ = StudentClassPoints.objects.get_or_create(
            student=self.student,
            classroom=self.classroom,
            attendance_points=0.0
        )
        
        # 1. ゼロ除算エラーや例外が発生せず計算が正常に0を返すこと
        scp.calculate_points_internal()
        self.assertEqual(scp.points, 0)
        
        stats = scp.quiz_stats
        self.assertEqual(stats['count'], 0)
        self.assertEqual(stats['average'], 0)
        
        peer_stats = scp.peer_eval_stats
        self.assertEqual(peer_stats['count'], 0)
        self.assertEqual(peer_stats['total'], 0)

    def test_class_student_detail_view_integration(self):
        """学生詳細ビュー（クラス別）における統計平均表示の統合検証"""
        # 1. データを設定
        scp, _ = StudentClassPoints.objects.get_or_create(
            student=self.student,
            classroom=self.classroom,
            attendance_points=10.0
        )
        
        # 小テスト1回 (10点)
        quiz = Quiz.objects.create(lesson_session=self.session, quiz_name='Quiz 1', max_score=10)
        QuizScore.objects.create(student=self.student, quiz=quiz, score=10, graded_by=self.teacher)
        
        # ピア評価 貢献度 (6点)
        pe_settings = PeerEvaluationSettings.objects.create(
            lesson_session=self.session,
            enable_group_evaluation=False,
            enable_member_evaluation=True
        )
        eval_obj = PeerEvaluation.objects.create(
            lesson_session=self.session,
            evaluator_token=uuid.uuid4(),
            evaluator_group=Group.objects.create(lesson_session=self.session, group_number=1)
        )
        from school_management.models import ContributionEvaluation
        ContributionEvaluation.objects.create(
            peer_evaluation=eval_obj,
            evaluatee=self.student,
            contribution_score=6
        )
        
        # 2. ビューへリクエスト
        url = reverse('school_management:class_student_detail', args=[self.classroom.id, self.student.student_number])
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, 200)
        # contextのstatsが正しい平均点を保持しているか確認
        # 平均点の式: (小テスト点(10) + ピア評価(6)) / (小テスト数(1) + ピア回数(1)) = 16 / 2 = 8.0点
        stats = response.context['stats']
        self.assertEqual(stats['total_quizzes'], 1)
        self.assertEqual(stats['avg_score'], 8.0)
        
    def test_general_student_detail_view_integration(self):
        """全体学生詳細ビューにおける統計平均表示の統合検証"""
        # 1. データを設定 (小テスト: 10点, ピア評価: 6点)
        scp, _ = StudentClassPoints.objects.get_or_create(
            student=self.student,
            classroom=self.classroom,
            attendance_points=10.0
        )
        
        quiz = Quiz.objects.create(lesson_session=self.session, quiz_name='Quiz 1', max_score=10)
        QuizScore.objects.create(student=self.student, quiz=quiz, score=10, graded_by=self.teacher)
        
        pe_settings = PeerEvaluationSettings.objects.create(
            lesson_session=self.session,
            enable_group_evaluation=False,
            enable_member_evaluation=True
        )
        eval_obj = PeerEvaluation.objects.create(
            lesson_session=self.session,
            evaluator_token=uuid.uuid4(),
            evaluator_group=Group.objects.create(lesson_session=self.session, group_number=1)
        )
        from school_management.models import ContributionEvaluation
        ContributionEvaluation.objects.create(
            peer_evaluation=eval_obj,
            evaluatee=self.student,
            contribution_score=6
        )
        
        # 2. ビューへリクエスト
        url = reverse('school_management:student_detail', args=[self.student.student_number])
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, 200)
        # contextのstatsの平均点が 8.0点 か確認
        stats = response.context['stats']
        self.assertEqual(stats['total_quizzes'], 1)
        self.assertEqual(stats['avg_score'], 8.0)
