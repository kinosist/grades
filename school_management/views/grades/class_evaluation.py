from django.shortcuts import render, get_object_or_404
import logging
from django.contrib.auth.decorators import login_required
from django.db import models
from django.db.models import Sum, Q
from ...models import ClassRoom, LessonSession, StudentLessonPoints, Quiz, QuizScore, Group, GroupMember, StudentClassPoints, PeerEvaluation, ContributionEvaluation, SelfEvaluation

logger = logging.getLogger(__name__)

@login_required
def class_evaluation_view(request, class_id):
    """クラスごとの評価一覧（写真のような形式）"""
    classroom = get_object_or_404(ClassRoom, id=class_id, teachers=request.user)
    students = classroom.students.all().order_by('student_number')
    
    # 授業回の一覧を取得
    sessions = LessonSession.objects.filter(classroom=classroom).order_by('session_number')
    
    # 評価システム（通常 or 目標管理）
    grading_system = classroom.grading_system

    # 各学生の評価データを取得
    student_evaluations = []
    
    for student in students:
        # 各授業回のデータ（ポイント + ピア評価スコア）
        session_data = {}
        session_count = 0
        total_qr_points = 0
        
        for session in sessions:
            session_key = f"第{session.session_number}回"
            
            # 授業内手動ポイントを取得（StudentLessonPoints）
            # ※QRコードのポイントはQuizScoreに含まれるため、ここは手動付与分などの「その他」扱い
            manual_points = 0
            lesson_point = StudentLessonPoints.objects.filter(
                lesson_session=session,
                student=student
            ).first()
            if lesson_point:
                manual_points = lesson_point.points
                session_count += 1
            
            # 小テストスコアを取得（QRアクション点もここに含まれる）
            quiz_score = 0
            has_quiz = False
            try:
                # その授業回の全ての小テストスコアを合算する（重複枠対策）
                session_quiz_scores = QuizScore.objects.filter(
                    quiz__lesson_session=session,
                    student=student,
                    is_cancelled=False
                )
                if session_quiz_scores.exists():
                    has_quiz = True
                    quiz_score = sum(qs.score for qs in session_quiz_scores)
            except Exception as e:
                logger.error(f"小テストスコア取得エラー: {e}", exc_info=True)
                pass
            
            # ピア評価スコアを取得（貢献度 + 投票ポイント）
            peer_evaluation_score = 0
            try:
                if session.has_peer_evaluation:
                    # 1. 貢献度評価 (5段階評価の合計)
                    contrib_score = ContributionEvaluation.objects.filter(
                        peer_evaluation__lesson_session=session,
                        evaluatee=student
                    ).aggregate(total=Sum('contribution_score'))['total'] or 0
                    
                    # 2. 投票ポイント (1位=2点, 2位=1点)
                    vote_score = 0
                    # この授業回での学生のグループを取得
                    membership = GroupMember.objects.filter(
                        student=student,
                        group__lesson_session=session
                    ).first()
                    
                    if membership:
                        group = membership.group
                        
                        # ランキング判定
                        session_groups = Group.objects.filter(lesson_session=session)
                        group_scores = []
                        for g in session_groups:
                            f = PeerEvaluation.objects.filter(Q(first_place_group=g) | Q(lesson_session=session, first_place_group_number=g.group_number)).distinct().count()
                            s = PeerEvaluation.objects.filter(Q(second_place_group=g) | Q(lesson_session=session, second_place_group_number=g.group_number)).distinct().count()
                            group_scores.append((f * 2) + (s * 1))
                        
                        unique_scores = sorted(list(set(group_scores)), reverse=True)
                        top_2_scores = unique_scores[:2]
                        
                        my_f = PeerEvaluation.objects.filter(Q(first_place_group=group) | Q(lesson_session=session, first_place_group_number=group.group_number)).distinct().count()
                        my_s = PeerEvaluation.objects.filter(Q(second_place_group=group) | Q(lesson_session=session, second_place_group_number=group.group_number)).distinct().count()
                        my_score = (my_f * 2) + (my_s * 1)
                        
                        if my_score > 0 and my_score in top_2_scores:
                            vote_score = my_score
                        else:
                            vote_score = 0

                    peer_evaluation_score = contrib_score + vote_score
            except Exception as e:
                logger.error(f"ピア評価スコア取得エラー: {e}", exc_info=True)
                pass
            
            session_data[session_key] = {
                'manual_points': manual_points,
                'quiz_score': quiz_score,
                'peer_score': peer_evaluation_score,
                'total_score': manual_points + quiz_score + peer_evaluation_score,
                'date': session.date,
                'has_peer_evaluation': session.has_peer_evaluation,
                'has_quiz': has_quiz,
                'session': session
            }
        
        # 出席率と平均ポイントを計算
        total_sessions = sessions.count()
        # データベースから保存された出席率、出席点、ポイントを取得
        attendance_rate = 0
        saved_attendance_points = 0
        saved_class_points = 0
        try:
            student_class_points = StudentClassPoints.objects.get(student=student, classroom=classroom)
            attendance_rate = student_class_points.attendance_rate
            saved_attendance_points = student_class_points.attendance_points
        except StudentClassPoints.DoesNotExist:
            # 保存されていない場合は自動計算
            attendance_rate = (session_count / total_sessions * 100) if total_sessions > 0 else 0
            # 未保存でも出席点は計算して表示する
            saved_attendance_points = (attendance_rate / 100) * classroom.attendance_max_points
        
        # 各種スコアの合計を計算
        total_peer_score = sum(data['peer_score'] for data in session_data.values())
        total_quiz_score = sum(data.get('quiz_score', 0) for data in session_data.values())
        total_combined_score = sum(data['total_score'] for data in session_data.values())
        
        # 出席点を使用（保存されたものがあればそれを使う）
        attendance_points_value = saved_attendance_points

        # 合計計算ロジックの変更
        # 授業点 = (小テスト(QR含む) + ピア評価 + 手動ポイント) * 倍率 + 出席点
        multiplier_value = 2
        
        # total_combined_score には (Manual + Quiz(QR含む) + Peer) が含まれている
        
        # 目標管理モードの場合は、DBに保存されているポイント（講師評価点）を優先
        if grading_system == 'goal':
            # 目標管理モード: SelfEvaluationから取得（DB保存値からの逆算は誤差が出るため避ける）
            self_eval = SelfEvaluation.objects.filter(student=student, classroom=classroom).first()
            score_points = self_eval.teacher_score if self_eval and self_eval.teacher_score is not None else 0
            
            # 合計 = 授業点 + 出席点
            total_points_calculated = score_points + attendance_points_value
        else:
            # 通常モード: 積み上げ計算結果を使用
            score_points = total_combined_score
            
            # 合計 = (授業点 * 2) + 出席点
            total_points_calculated = (score_points * multiplier_value) + attendance_points_value
        
        # 平均点の計算（小テスト/QRの平均）
        average_points = round(total_quiz_score / session_count, 1) if session_count > 0 else 0

        # セッションごとのスコアをリスト化（テンプレート表示用）
        ordered_session_scores = []
        for session in sessions:
            session_key = f"第{session.session_number}回"
            ordered_session_scores.append(session_data[session_key])

        student_evaluations.append({
            'student': student,
            'total_points': total_points_calculated,  # 合計点は出席点 + 点数
            'score_points': score_points,             # 授業点（表示用）
            'total_peer_score': total_peer_score,
            'total_quiz_score': total_quiz_score,  # 小テストスコアの合計
            'total_combined_score': total_combined_score,
            'attendance_points': attendance_points_value,  # 出席点（保存された値または0）
            'attendance_rate': attendance_rate,
            'multiplied_points': total_points_calculated,  # 倍率適用済みの点数
            'multiplier': multiplier_value,
            'session_data': session_data,
            'session_scores': ordered_session_scores,
            'session_count': session_count,
            'average_points': average_points,
            'class_points': total_points_calculated,  # クラスのポイント
            'student_points': student.points,  # 学生の全体ポイント
            'qr_points': total_quiz_score,  # QRコードポイント（小テストスコア）の合計
        })
    
    session_list = [f"第{session.session_number}回" for session in sessions]
    
    # 各授業回のピア評価平均値を計算
    session_peer_averages = {}
    for session in sessions:
        if session.has_peer_evaluation:
            peer_scores = ContributionEvaluation.objects.filter(
                peer_evaluation__lesson_session=session
            ).aggregate(avg_score=models.Avg('contribution_score'))
            
            avg_score = round(peer_scores['avg_score'] or 0, 1)
            session_peer_averages[session.id] = avg_score
        else:
            session_peer_averages[session.id] = None
    
    context = {
        'classroom': classroom,
        'student_evaluations': student_evaluations,
        'session_list': session_list,
        'sessions': sessions,  # 日付情報も渡す
        'session_peer_averages': session_peer_averages,  # ピア評価平均値
        'total_sessions': len(session_list),
        'grading_system': grading_system, # テンプレート側で表示切り替えに使用
    }
    return render(request, 'school_management/class_evaluation.html', context)
