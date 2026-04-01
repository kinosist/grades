from django.shortcuts import render, get_object_or_404
import logging
from django.contrib.auth.decorators import login_required
from django.db.models import Sum, Q
# ✨ StudentColumnScore を新しくインポートに追加！
from ...models import (
    ClassRoom, LessonSession, StudentLessonPoints, QuizScore, Group, 
    GroupMember, StudentClassPoints, PeerEvaluation, ContributionEvaluation, 
    SelfEvaluation, PointColumn, StudentColumnScore
)

logger = logging.getLogger(__name__)

@login_required
def class_evaluation_view(request, class_id):
    """
    クラスごとの評価一覧（成績表）を表示するビュー
    
    QR採点、ピア評価、各種小テスト、および教員が独自に追加した
    評価項目の点数を集計し、一覧表示する。
    """
    classroom = get_object_or_404(ClassRoom, id=class_id, teachers=request.user)
    students = classroom.students.all().order_by('student_number')
    
    # 表示モード (simple / detail) - デフォルトは詳細モード
    view_mode = request.GET.get('mode', 'detail')
    
    # 授業回の一覧を取得
    sessions = LessonSession.objects.filter(classroom=classroom).order_by('session_number')
    
    # ✨ 先生が追加した「独自の評価項目（列）」の一覧を取得！
    point_columns = classroom.point_columns.all().order_by('created_at')
    
    # 評価システム（通常 or 目標管理）
    grading_system = classroom.grading_system

    # 各学生の評価データを取得
    student_evaluations = []
    
    for student in students:
        # 各授業回のデータ（ポイント + ピア評価スコア）
        session_data = {}
        
        for session in sessions:
            session_key = f"第{session.session_number}回"
            
            # 授業内手動ポイントを取得（StudentLessonPoints）
            manual_points = 0
            lesson_point = StudentLessonPoints.objects.filter(
                lesson_session=session,
                student=student
            ).first()
            if lesson_point:
                manual_points = lesson_point.points
            
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
                    # 重複対策: 同一クイズは最新のみ
                    quiz_score_dict = {}
                    for qs in session_quiz_scores:
                        quiz_score_dict[qs.quiz.id] = qs.score
                    quiz_score = sum(quiz_score_dict.values())
            except Exception as e:
                logger.error(f"小テストスコア取得エラー: {e}", exc_info=True)
                pass
            
            # ピア評価スコアを取得（貢献度 + 投票ポイント）
            peer_evaluation_score = 0
            contrib_score = 0
            vote_score = 0
            try:
                if session.has_peer_evaluation:
                    # 1. 貢献度評価 (5段階評価の合計)
                    contrib_score = ContributionEvaluation.objects.filter(
                        peer_evaluation__lesson_session=session,
                        evaluatee=student
                    ).aggregate(total=Sum('contribution_score'))['total'] or 0
                    
                    # 2. 投票ポイント (1位=2点, 2位=1点)
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
                'peer_contrib': contrib_score,
                'peer_vote': vote_score,
                'total_score': manual_points + quiz_score + peer_evaluation_score,
                'date': session.date,
                'has_peer_evaluation': session.has_peer_evaluation,
                'has_quiz': has_quiz,
                'session': session
            }

        # ✨ 新規追加：この学生の「独自の評価項目（列）」ごとの点数を取得！
        custom_column_scores = {}
        custom_columns_total = 0
        for col in point_columns:
            score_obj = StudentColumnScore.objects.filter(student=student, column=col).first()
            score_val = score_obj.score if score_obj else 0
            custom_column_scores[col.id] = score_val
            custom_columns_total += score_val
        
        # データベースから保存された出席率、出席点を取得
        attendance_rate = 0
        saved_attendance_points = 0
        try:
            student_class_points = StudentClassPoints.objects.get(student=student, classroom=classroom)
            attendance_rate = student_class_points.attendance_rate
            saved_attendance_points = student_class_points.attendance_points
        except StudentClassPoints.DoesNotExist:
            pass
        
        # 各種スコアの合計を計算
        total_peer_score = sum(data['peer_score'] for data in session_data.values())
        total_quiz_score = sum(data.get('quiz_score', 0) for data in session_data.values())
        total_combined_score = sum(data['total_score'] for data in session_data.values())
        
        # 目標管理モードの場合は、DBに保存されているポイント（講師評価点）を優先
        if grading_system == 'goal':
            self_eval = SelfEvaluation.objects.filter(student=student, classroom=classroom).first()
            score_points = self_eval.teacher_score if self_eval and self_eval.teacher_score is not None else 0
            total_points_calculated = score_points + saved_attendance_points
        else:
            # 通常モード: 合計 = (授業点 * 2) + 出席点
            # ✨ 独自の評価項目で獲得した点数も、最終スコアに加算する！
            score_points = total_combined_score + custom_columns_total
            total_points_calculated = (score_points * 2) + saved_attendance_points

        # セッションごとのスコアをリスト化（テンプレート表示用）
        ordered_session_scores = []
        for session in sessions:
            session_key = f"第{session.session_number}回"
            ordered_session_scores.append(session_data[session_key])

        student_evaluations.append({
            'student': student,
            'total_points': total_points_calculated,
            'score_points': score_points,
            'total_peer_score': total_peer_score,
            'total_quiz_score': total_quiz_score,
            'custom_columns_total': custom_columns_total,   # ✨ 独自項目の合計点
            'custom_column_scores': custom_column_scores,   # ✨ 各独自項目の個別点数
            'attendance_points': saved_attendance_points,
            'attendance_rate': attendance_rate,
            'session_scores': ordered_session_scores,
        })
    
    total_sessions = sessions.count()

    # ✨ テーブルのカラム幅を調整（独自評価項目の数を足す）
    base_colspan = (total_sessions * 2 + 7) if view_mode == 'detail' else 7
    table_colspan = base_colspan + point_columns.count()

    context = {
        'classroom': classroom,
        'student_evaluations': student_evaluations,
        'sessions': sessions,
        'point_columns': point_columns,  # ✨ HTMLで列のヘッダーを作るために渡す
        'total_sessions': total_sessions,
        'grading_system': grading_system,
        'view_mode': view_mode,
        'table_colspan': table_colspan,
    }
    return render(request, 'school_management/class_evaluation.html', context)