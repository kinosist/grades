from django.shortcuts import render, get_object_or_404
import logging
from django.contrib.auth.decorators import login_required
from django.db.models import Sum

import json
from django.http import JsonResponse
from django.views.decorators.http import require_POST
import statistics

# 必要なモデルをインポート
from ...models import (
    ClassRoom, LessonSession, Student, StudentLessonPoints, QuizScore, Group, 
    GroupMember, StudentClassPoints, PeerEvaluation, ContributionEvaluation, 
    SelfEvaluation, PointColumn, StudentColumnScore, PeerEvaluationSettings
)

logger = logging.getLogger(__name__)

@login_required
def class_evaluation_view(request, class_id):
    """
    クラスごとの評価一覧（成績表）を表示するビュー
    
    QR採点、ピア評価、各種小テスト、および教員が独自に追加した
    評価項目の点数を集計し、一覧表示します。
    """
    classroom = get_object_or_404(ClassRoom, id=class_id, teachers=request.user)
    students = classroom.students.all().order_by('student_number')
    
    # 表示モード (simple / detail) - デフォルトは詳細モード
    view_mode = request.GET.get('mode', 'detail')
    
    # 授業回の一覧を取得
    sessions = LessonSession.objects.filter(classroom=classroom).order_by('session_number')
    
    # 教員が追加した「独自の評価項目（列）」の一覧を取得
    point_columns = classroom.point_columns.all().order_by('created_at')
    
    # 評価システム（default: 通常, original: カスタマイズ, goal: 目標管理）
    grading_system = classroom.grading_system

    # 各学生の評価データを格納するリスト
    student_evaluations = []
    
    for student in students:
        # 各授業回のデータ（ポイント + ピア評価スコア）を格納する辞書
        session_data = {}
        
        for session in sessions:
            session_key = f"第{session.session_number}回"
            
            # 1. 授業内手動ポイントを取得（StudentLessonPoints）
            manual_points = 0
            lesson_point = StudentLessonPoints.objects.filter(
                lesson_session=session,
                student=student
            ).first()
            if lesson_point:
                manual_points = lesson_point.points
            
            # 2. 小テストスコアを取得（QRアクション点もここに含まれる）
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
                    # 重複対策: 同一クイズは最新のスコアのみを採用
                    quiz_score_dict = {}
                    for qs in session_quiz_scores:
                        quiz_score_dict[qs.quiz.id] = qs.score
                    quiz_score = sum(quiz_score_dict.values())
            except Exception as e:
                logger.error(f"小テストスコア取得エラー: {e}", exc_info=True)
                pass
            
            # 3. ピア評価スコアを取得（貢献度 + 投票ポイント）
            peer_evaluation_score = 0
            contrib_score = 0
            vote_score = 0
            try:
                if session.has_peer_evaluation:
                    # 3-1. 貢献度評価 (5段階評価の合計を取得)
                    contrib_score = ContributionEvaluation.objects.filter(
                        peer_evaluation__lesson_session=session,
                        evaluatee=student
                    ).aggregate(total=Sum('contribution_score'))['total'] or 0
                    
                    # 3-2. 投票ポイントの計算（response_json + 設定配点）
                    membership = GroupMember.objects.filter(
                        student=student,
                        group__lesson_session=session
                    ).first()
                    
                    if membership:
                        group = membership.group
                        try:
                            pe_settings = session.peer_evaluation_settings
                        except PeerEvaluationSettings.DoesNotExist:
                            pe_settings = None

                        score_points = (
                            pe_settings.group_scores or []
                        ) if pe_settings and pe_settings.enable_group_evaluation else []

                        if score_points:
                            session_groups = Group.objects.filter(lesson_session=session)
                            group_point_map = {g.id: 0 for g in session_groups}
                            session_evals = PeerEvaluation.objects.filter(lesson_session=session)
                            for pe in session_evals:
                                response = pe.response_json or {}
                                for entry in response.get('other_group_eval', []):
                                    gid = entry.get('group_id')
                                    rank = entry.get('rank')
                                    if gid in group_point_map and rank and 1 <= rank <= len(score_points):
                                        group_point_map[gid] += score_points[rank - 1]

                            vote_score = group_point_map.get(group.id, 0)

                    peer_evaluation_score = contrib_score + vote_score
            except Exception as e:
                logger.error(f"ピア評価スコア取得エラー: {e}", exc_info=True)
                pass
            
            # セッションごとのデータを辞書に保存
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

        # 4. 独自の評価項目（列）ごとの点数を取得
        custom_column_scores = {}
        custom_columns_total = 0
        for col in point_columns:
            score_obj = StudentColumnScore.objects.filter(student=student, column=col).first()
            score_val = score_obj.score if score_obj else 0
            custom_column_scores[col.id] = score_val
            custom_columns_total += score_val
        
        # 5. データベースから保存された出席率、出席点を取得
        attendance_rate = 0
        saved_attendance_points = 0
        try:
            student_class_points = StudentClassPoints.objects.get(student=student, classroom=classroom)
            attendance_rate = student_class_points.attendance_rate
            saved_attendance_points = student_class_points.attendance_points
        except StudentClassPoints.DoesNotExist:
            pass
        
        # 6. 各種スコアの合計を計算
        total_peer_score = sum(data['peer_score'] for data in session_data.values())
        total_quiz_score = sum(data.get('quiz_score', 0) for data in session_data.values())
        total_combined_score = sum(data['total_score'] for data in session_data.values())
        
        # 評価システム（モード）に応じた合計点数の算出
        if grading_system == 'goal':
            # 目標管理モード: 教師評価点 + 出席点
            self_eval = SelfEvaluation.objects.filter(student=student, classroom=classroom).first()
            score_points = self_eval.teacher_score if self_eval and self_eval.teacher_score is not None else 0
            total_points_calculated = score_points + saved_attendance_points
        else:
            # 通常モード / オリジナルモード: 合計 = (授業点 * 2) + 出席点
            # 独自の評価項目で獲得した点数も授業点に加算
            score_points = total_combined_score + custom_columns_total
            total_points_calculated = (score_points * 2) + saved_attendance_points

        # セッションごとのスコアをリスト化（テンプレート表示用）
        ordered_session_scores = []
        for session in sessions:
            session_key = f"第{session.session_number}回"
            ordered_session_scores.append(session_data[session_key])

        # 学生ごとの評価データをリストに追加
        student_evaluations.append({
            'student': student,
            'total_points': total_points_calculated,
            'score_points': score_points,
            'total_peer_score': total_peer_score,
            'total_quiz_score': total_quiz_score,
            'custom_columns_total': custom_columns_total,
            'custom_column_scores': custom_column_scores,
            'attendance_points': saved_attendance_points,
            'attendance_rate': attendance_rate,
            'session_scores': ordered_session_scores,
        })

    # --- クラス全体の統計データ（中央値・最高点）の算出 ---
    all_raw_scores = [e['total_points'] for e in student_evaluations]
    if all_raw_scores:
        # 中央値を取得
        median_val = statistics.median(all_raw_scores)
        # 中央値の半分を足切りラインに設定
        cutoff_line = median_val / 2
        
        # 足切りをクリアした学生の中での最高点を取得（換算の基準値）
        passed_scores = [s for s in all_raw_scores if s > cutoff_line]
        max_val = max(passed_scores) if passed_scores else 0
    else:
        median_val = 0
        cutoff_line = 0
        max_val = 0

    # --- 評価システムに応じた最終成績の処理（足切りと換算） ---
    for eval_data in student_evaluations:
        current_raw = eval_data['total_points']
        
        # クラスが「オリジナル（カスタマイズ）」モードの場合のみ、足切りと100点換算を実施
        if grading_system == 'original':
            # 足切り判定 (中央値の半分以下か)
            if current_raw <= cutoff_line:
                eval_data['is_below_cutoff'] = True
                eval_data['final_score_100'] = 0  # 足切りライン以下の場合は0点
            else:
                eval_data['is_below_cutoff'] = False
                # 換算処理: 最高得点者が100点になるように比率で計算
                if max_val > 0:
                    eval_data['final_score_100'] = round((current_raw / max_val) * 100, 1)
                else:
                    eval_data['final_score_100'] = 0
        else:
            # 「デフォルト（通常）」や「目標管理」モードの場合は足切りを行わず、素点をそのまま利用
            eval_data['is_below_cutoff'] = False
            eval_data['final_score_100'] = round(current_raw, 1)

        
    total_sessions = sessions.count()

    # テーブルのカラム幅（colspan）を調整（独自評価項目の数を考慮）
    base_colspan = (total_sessions * 2 + 7) if view_mode == 'detail' else 7
    table_colspan = base_colspan + point_columns.count()

    # テンプレートに渡すコンテキストデータ
    context = {
        'classroom': classroom,
        'student_evaluations': student_evaluations,
        'sessions': sessions,
        'point_columns': point_columns,
        'total_sessions': total_sessions,
        'grading_system': grading_system,
        'view_mode': view_mode,
        'table_colspan': table_colspan,
    }
    return render(request, 'school_management/class_evaluation.html', context)


@login_required
@require_POST
def update_custom_score(request, class_id):
    try:
        data = json.loads(request.body)
        student_id = data.get('student_id')
        column_id = data.get('column_id')
        score = data.get('score', 0)

        # クラス取得（担当教員かチェック）
        classroom = get_object_or_404(
            ClassRoom,
            id=class_id,
            teachers=request.user
        )

        # クラスに属する学生かチェック
        student = get_object_or_404(
            Student,
            id=student_id,
            classroom=classroom
        )

        # クラスに属する評価項目かチェック
        column = get_object_or_404(
            PointColumn,
            id=column_id,
            classroom=classroom
        )

        # 更新 or 作成
        StudentColumnScore.objects.update_or_create(
            student=student,
            column=column,
            defaults={'score': score}
        )

        return JsonResponse({'success': True})

    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=400)
