from django.test import TestCase
from django.contrib.auth import get_user_model
from school_management.models import (
    LessonSession, ClassRoom, Group, Student, 
    GroupMember, PeerEvaluation, PeerEvaluationSettings, ContributionEvaluation,
    StudentClassPoints
)
from school_management.views.peer_eval.improved import _safe_int, _aggregate_member_scores
import uuid

User = get_user_model()

class PeerEvalUtilityTests(TestCase):
    """ユーティリティ関数のテスト"""
    
    def test_safe_int_valid_inputs(self):
        self.assertEqual(_safe_int(10), 10)
        self.assertEqual(_safe_int("42"), 42)
        self.assertEqual(_safe_int("-5"), -5)

    def test_safe_int_invalid_inputs(self):
        self.assertIsNone(_safe_int("abc"))
        self.assertIsNone(_safe_int(None))
        self.assertIsNone(_safe_int([]))


class PeerEvalAggregateLogicTests(TestCase):
    """ピア評価の集計ロジックテスト"""
    
    def setUp(self):
        # テスト用の基礎データ作成
        self.classroom = ClassRoom.objects.create(
            class_name="テストクラス",
            year=2024,
            semester="first"
        )
        # OPEN で作成して、設定作成後に CLOSED にする
        self.session = LessonSession.objects.create(
            classroom=self.classroom, 
            session_number=1,
            peer_evaluation_status=LessonSession.PeerEvaluationStatus.OPEN
        )
        
        self.settings = PeerEvaluationSettings.objects.create(
            lesson_session=self.session,
            enable_member_evaluation=True,
            enable_group_evaluation=True,
            evaluation_method=PeerEvaluationSettings.EvaluationMethod.AGGREGATE,
            group_evaluation_method=PeerEvaluationSettings.EvaluationMethod.AGGREGATE,
            member_scores=[10, 8, 6],  # 1位10点, 2位8点, 3位6点
            group_scores=[5, 3] # 1位5点, 2位3点
        )
        
        self.group_a = Group.objects.create(lesson_session=self.session, group_number=1)
        self.group_b = Group.objects.create(lesson_session=self.session, group_number=2)
        self.group_c = Group.objects.create(lesson_session=self.session, group_number=3)
        
        # メンバーの作成 (A: 3名, B: 2名, C: 2名)
        self.student_a1 = Student.objects.create(full_name="学生A1", email="a1@test.com", role="student")
        self.student_a2 = Student.objects.create(full_name="学生A2", email="a2@test.com", role="student")
        self.student_a3 = Student.objects.create(full_name="学生A3", email="a3@test.com", role="student")
        
        GroupMember.objects.create(group=self.group_a, student=self.student_a1)
        GroupMember.objects.create(group=self.group_a, student=self.student_a2)
        GroupMember.objects.create(group=self.group_a, student=self.student_a3)
        
        self.student_b1 = Student.objects.create(full_name="学生B1", email="b1@test.com", role="student")
        self.student_b2 = Student.objects.create(full_name="学生B2", email="b2@test.com", role="student")
        
        GroupMember.objects.create(group=self.group_b, student=self.student_b1)
        GroupMember.objects.create(group=self.group_b, student=self.student_b2)
        
        self.student_c1 = Student.objects.create(full_name="学生C1", email="c1@test.com", role="student")
        self.student_c2 = Student.objects.create(full_name="学生C2", email="c2@test.com", role="student")

        GroupMember.objects.create(group=self.group_c, student=self.student_c1)
        GroupMember.objects.create(group=self.group_c, student=self.student_c2)

    def test_aggregate_member_scores_normal_case(self):
        """正常系の集計テスト: 学生A1が1位を2票集めた場合など"""
        # 評価データを追加
        PeerEvaluation.objects.create(
            lesson_session=self.session, student=self.student_a1, evaluator_group=self.group_a, evaluator_token=uuid.uuid4(),
            response_json={"group_members_eval": [{"member_id": self.student_a2.id, "rank": 1}, {"member_id": self.student_a3.id, "rank": 2}]}
        )
        PeerEvaluation.objects.create(
            lesson_session=self.session, student=self.student_a2, evaluator_group=self.group_a, evaluator_token=uuid.uuid4(),
            response_json={"group_members_eval": [{"member_id": self.student_a1.id, "rank": 1}, {"member_id": self.student_a3.id, "rank": 2}]}
        )
        PeerEvaluation.objects.create(
            lesson_session=self.session, student=self.student_a3, evaluator_group=self.group_a, evaluator_token=uuid.uuid4(),
            response_json={"group_members_eval": [{"member_id": self.student_a1.id, "rank": 1}, {"member_id": self.student_a2.id, "rank": 2}]}
        )
        
        self.session.peer_evaluation_status = LessonSession.PeerEvaluationStatus.CLOSED
        self.session.save()
        
        _aggregate_member_scores(self.session, self.settings)
        
        # A1: 1位(2pt)*2 = 4pt -> 1位 (10点)
        # A2: 1位(2pt) + 2位(1pt) = 3pt -> 2位 (8点)
        # A3: 2位(1pt)*2 = 2pt -> 3位 (6点)
        evals = ContributionEvaluation.objects.filter(peer_evaluation__lesson_session=self.session)
        self.assertEqual(evals.get(evaluatee=self.student_a1).contribution_score, 10)
        self.assertEqual(evals.get(evaluatee=self.student_a2).contribution_score, 8)
        self.assertEqual(evals.get(evaluatee=self.student_a3).contribution_score, 6)

    def test_aggregate_member_scores_tie(self):
        """同点のテスト"""
        # A1: A2(1位), A3(2位)
        # A2: A3(1位), A1(2位)
        # A3: A1(1位), A2(2位)
        PeerEvaluation.objects.create(lesson_session=self.session, student=self.student_a1, evaluator_group=self.group_a, evaluator_token=uuid.uuid4(), response_json={"group_members_eval": [{"member_id": self.student_a2.id, "rank": 1}, {"member_id": self.student_a3.id, "rank": 2}]})
        PeerEvaluation.objects.create(lesson_session=self.session, student=self.student_a2, evaluator_group=self.group_a, evaluator_token=uuid.uuid4(), response_json={"group_members_eval": [{"member_id": self.student_a3.id, "rank": 1}, {"member_id": self.student_a1.id, "rank": 2}]})
        PeerEvaluation.objects.create(lesson_session=self.session, student=self.student_a3, evaluator_group=self.group_a, evaluator_token=uuid.uuid4(), response_json={"group_members_eval": [{"member_id": self.student_a1.id, "rank": 1}, {"member_id": self.student_a2.id, "rank": 2}]})

        self.session.peer_evaluation_status = LessonSession.PeerEvaluationStatus.CLOSED
        self.session.save()
        _aggregate_member_scores(self.session, self.settings)

        # 全員 1位(2pt) + 2位(1pt) = 3pt で同点1位 -> 全員10点
        evals = ContributionEvaluation.objects.filter(peer_evaluation__lesson_session=self.session)
        self.assertEqual(evals.get(evaluatee=self.student_a1).contribution_score, 10)
        self.assertEqual(evals.get(evaluatee=self.student_a2).contribution_score, 10)
        self.assertEqual(evals.get(evaluatee=self.student_a3).contribution_score, 10)

    def test_aggregate_member_scores_unranked(self):
        """未評価メンバーのテスト"""
        # Bグループは2名なので、B1がB2を評価しない場合
        PeerEvaluation.objects.create(lesson_session=self.session, student=self.student_b1, evaluator_group=self.group_b, evaluator_token=uuid.uuid4(), response_json={"group_members_eval": []})
        PeerEvaluation.objects.create(lesson_session=self.session, student=self.student_b2, evaluator_group=self.group_b, evaluator_token=uuid.uuid4(), response_json={"group_members_eval": [{"member_id": self.student_b1.id, "rank": 1}]})

        self.session.peer_evaluation_status = LessonSession.PeerEvaluationStatus.CLOSED
        self.session.save()
        _aggregate_member_scores(self.session, self.settings)

        # B1: 1位(1pt) -> 1位 (10点)
        # B2: 未評価(0pt) -> 2位 (8点) 
        # (2人グループなので2位になる)
        evals = ContributionEvaluation.objects.filter(peer_evaluation__lesson_session=self.session, evaluatee__in=[self.student_b1, self.student_b2])
        self.assertEqual(evals.get(evaluatee=self.student_b1).contribution_score, 10)
        self.assertEqual(evals.get(evaluatee=self.student_b2).contribution_score, 8)

    def test_calculate_group_vote_points_aggregate(self):
        """グループ評価（AGGREGATE方式）のテスト"""
        # A1: B(1位), C(2位)
        PeerEvaluation.objects.create(lesson_session=self.session, student=self.student_a1, evaluator_group=self.group_a, evaluator_token=uuid.uuid4(), response_json={"other_group_eval": [{"group_id": self.group_b.id, "rank": 1}, {"group_id": self.group_c.id, "rank": 2}]})
        # A2: B(1位), C(2位)
        PeerEvaluation.objects.create(lesson_session=self.session, student=self.student_a2, evaluator_group=self.group_a, evaluator_token=uuid.uuid4(), response_json={"other_group_eval": [{"group_id": self.group_b.id, "rank": 1}, {"group_id": self.group_c.id, "rank": 2}]})
        # B1: C(1位), A(2位)
        PeerEvaluation.objects.create(lesson_session=self.session, student=self.student_b1, evaluator_group=self.group_b, evaluator_token=uuid.uuid4(), response_json={"other_group_eval": [{"group_id": self.group_c.id, "rank": 1}, {"group_id": self.group_a.id, "rank": 2}]})

        self.session.peer_evaluation_status = LessonSession.PeerEvaluationStatus.CLOSED
        self.session.save()

        # B: 1位(2pt)*2 = 4pt -> 1位 (5点)
        # C: 2位(1pt)*2 + 1位(2pt) = 4pt -> 1位同点 (5点)
        # A: 2位(1pt)*1 = 1pt -> 3位 (圏外: 0点)
        scp_a1, _ = StudentClassPoints.objects.get_or_create(student=self.student_a1, classroom=self.classroom)
        scp_b1, _ = StudentClassPoints.objects.get_or_create(student=self.student_b1, classroom=self.classroom)
        scp_c1, _ = StudentClassPoints.objects.get_or_create(student=self.student_c1, classroom=self.classroom)
        self.assertEqual(scp_a1.get_activity_points(), 0)
        self.assertEqual(scp_b1.get_activity_points(), 5)
        self.assertEqual(scp_c1.get_activity_points(), 5)

    def test_calculate_group_vote_points_direct(self):
        """グループ評価（DIRECT方式）のテスト"""
        self.settings.group_evaluation_method = PeerEvaluationSettings.EvaluationMethod.DIRECT
        self.settings.save()
        
        # A1: B(1位), C(2位) -> Bに5点, Cに3点
        PeerEvaluation.objects.create(lesson_session=self.session, student=self.student_a1, evaluator_group=self.group_a, evaluator_token=uuid.uuid4(), response_json={"other_group_eval": [{"group_id": self.group_b.id, "rank": 1}, {"group_id": self.group_c.id, "rank": 2}]})
        # A2: B(1位) -> Bに5点
        PeerEvaluation.objects.create(lesson_session=self.session, student=self.student_a2, evaluator_group=self.group_a, evaluator_token=uuid.uuid4(), response_json={"other_group_eval": [{"group_id": self.group_b.id, "rank": 1}]})

        self.session.peer_evaluation_status = LessonSession.PeerEvaluationStatus.CLOSED
        self.session.save()

        # B: 5 + 5 = 10点
        # C: 3点
        # A: 0点
        scp_a1, _ = StudentClassPoints.objects.get_or_create(student=self.student_a1, classroom=self.classroom)
        scp_b1, _ = StudentClassPoints.objects.get_or_create(student=self.student_b1, classroom=self.classroom)
        scp_c1, _ = StudentClassPoints.objects.get_or_create(student=self.student_c1, classroom=self.classroom)
        self.assertEqual(scp_b1.get_activity_points(), 10)
        self.assertEqual(scp_c1.get_activity_points(), 3)
        self.assertEqual(scp_a1.get_activity_points(), 0)

    def test_get_peer_history(self):
        """ピア評価履歴のテスト"""
        PeerEvaluation.objects.create(
            lesson_session=self.session, student=self.student_a1, evaluator_group=self.group_a, evaluator_token=uuid.uuid4(),
            response_json={"group_members_eval": [{"member_id": self.student_a2.id, "rank": 1}, {"member_id": self.student_a3.id, "rank": 2}],
                           "other_group_eval": [{"group_id": self.group_b.id, "rank": 1}, {"group_id": self.group_c.id, "rank": 2}]}
        )
        PeerEvaluation.objects.create(
            lesson_session=self.session, student=self.student_b1, evaluator_group=self.group_b, evaluator_token=uuid.uuid4(),
            response_json={"other_group_eval": [{"group_id": self.group_a.id, "rank": 1}]}
        )

        self.session.peer_evaluation_status = LessonSession.PeerEvaluationStatus.CLOSED
        self.session.save()
        _aggregate_member_scores(self.session, self.settings)

        # A2 はメンバー評価で1位(10点)、グループ評価で1位(5点) -> 合計15点
        scp_a2, _ = StudentClassPoints.objects.get_or_create(student=self.student_a2, classroom=self.classroom)
        history_a2 = scp_a2.get_peer_history()
        self.assertEqual(len(history_a2), 1)
        self.assertEqual(history_a2[0]['contrib'], 10)
        self.assertEqual(history_a2[0]['vote'], 5)
        self.assertEqual(history_a2[0]['total'], 15)
