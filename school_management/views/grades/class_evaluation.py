from django.shortcuts import render, get_object_or_404
import logging
from django.contrib.auth.decorators import login_required
from collections import defaultdict
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


def _safe_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _build_group_vote_point_map(session_groups, session_peer_evals, pe_settings, peer_status):
    group_point_map = {group_obj.id: 0 for group_obj in session_groups}
    if not pe_settings or not pe_settings.enable_group_evaluation:
        return group_point_map

    score_points = pe_settings.group_scores or []
    if not score_points:
        return group_point_map

    if pe_settings.group_evaluation_method == PeerEvaluationSettings.EvaluationMethod.AGGREGATE:
        if peer_status != LessonSession.PeerEvaluationStatus.CLOSED:
            return group_point_map

        group_internal_points = {group_obj.id: 0 for group_obj in session_groups}
        group_count = len(session_groups)
        for pe in session_peer_evals:
            response = pe.response_json or {}
            for entry in response.get('other_group_eval', []):
                gid = _safe_int(entry.get('group_id'))
                rank = _safe_int(entry.get('rank'))
                if gid in group_internal_points and rank and 1 <= rank <= group_count:
                    group_internal_points[gid] += (group_count - rank)

        sorted_groups = sorted(
            group_internal_points.items(),
            key=lambda x: x[1],
            reverse=True,
        )
        current_rank = 0
        prev_points = None
        for idx, (gid, internal_points) in enumerate(sorted_groups):
            if internal_points != prev_points:
                current_rank = idx
                prev_points = internal_points
            if current_rank < len(score_points):
                group_point_map[gid] = score_points[current_rank]
        return group_point_map

    for pe in session_peer_evals:
        response = pe.response_json or {}
        for entry in response.get('other_group_eval', []):
            gid = _safe_int(entry.get('group_id'))
            rank = _safe_int(entry.get('rank'))
            if gid in group_point_map and rank and 1 <= rank <= len(score_points):
                group_point_map[gid] += score_points[rank - 1]
    return group_point_map


@login_required
def class_evaluation_view(request, class_id):
    """
    クラスごとの評価一覧（成績表）を表示するビュー
    
    QR採点、ピア評価、各種小テスト、および教員が独自に追加した
    評価項目の点数を集計し、一覧表示します。
    """
    classroom = get_object_or_404(ClassRoom, id=class_id, teachers=request.user)
    students = classroom.students.all().order_by('student_number')
    
    # テストモードか判定
    test_mode = request.session.get('test_mode', False)
    
    # セッションからシミュレーション用点数を取得
    # 辞書構造: { class_id: { session_id: { student_id: points } } }
    sim_data_class = request.session.get('peer_sim_points', {}).get(str(classroom.id), {})
    has_simulation = len(sim_data_class) > 0
    
    # 表示モード (simple / detail) - デフォルトは詳細モード
    view_mode = request.GET.get('mode', 'detail')
    
    # 授業回の一覧を取得
    sessions = LessonSession.objects.filter(classroom=classroom).order_by('session_number')
    session_ids = list(sessions.values_list('id', flat=True))
    
    # 教員が追加した「独自の評価項目（列）」の一覧を取得
    point_columns = classroom.point_columns.all().order_by('created_at')
    
    # 評価システム（default: 通常, original: カスタマイズ, goal: 目標管理）
    grading_system = classroom.grading_system

    # N+1対策: 関連データを一括で取得
    all_peer_evals = PeerEvaluation.objects.filter(lesson_session__in=session_ids)
    all_groups = list(Group.objects.filter(lesson_session__in=session_ids))
    
    # N+1対策: StudentClassPointsを一括で取得 (select_relatedで最適化)
    student_ids = [s.id for s in students]
    student_class_points_map = {
        scp.student_id: scp
        for scp in StudentClassPoints.objects.filter(
            student_id__in=student_ids,
            classroom=classroom
        )
    }

    # AGGREGATEモード用の貢献度スコアを事前集計
    all_contrib_evals = ContributionEvaluation.objects.filter(
        peer_evaluation__lesson_session__classroom=classroom
    ).values(
        'evaluatee_id', 'peer_evaluation__lesson_session_id'
    ).annotate(
        total_contrib=Sum('contribution_score')
    )
    student_session_contrib_map = defaultdict(dict)
    for item in all_contrib_evals:
        student_id = item['evaluatee_id']
        session_id = item['peer_evaluation__lesson_session_id']
        score = item['total_contrib']
        student_session_contrib_map[student_id][session_id] = score

    # セッションIDをキーにした評価データの辞書を作成
    session_to_evals_map = defaultdict(list)
    for pe in all_peer_evals:
        session_to_evals_map[pe.lesson_session_id].append(pe)

    # セッション単位で不変な「グループ投票ポイント」を先に計算して使い回す
    session_group_point_maps = {}
    session_peer_settings = {}
    # NEW: DIRECTモード用の貢献度スコアを事前集計
    direct_mode_contrib_scores = defaultdict(lambda: defaultdict(int))
    for session in sessions:
        if not session.has_peer_evaluation:
            session_peer_settings[session.id] = None
            continue
        try:
            pe_settings = session.peer_evaluation_settings
        except PeerEvaluationSettings.DoesNotExist:
            pe_settings = None
        session_peer_settings[session.id] = pe_settings

        # NEW: DIRECTモードのスコア計算
        if pe_settings and pe_settings.enable_member_evaluation and pe_settings.evaluation_method == PeerEvaluationSettings.EvaluationMethod.DIRECT:
            member_scores = pe_settings.member_scores or []
            if member_scores:
                evals_in_session = session_to_evals_map.get(session.id, [])
                for ev in evals_in_session:
                    response = ev.response_json or {}
                    for entry in response.get('group_members_eval', []):
                        member_id = _safe_int(entry.get('member_id'))
                        rank = _safe_int(entry.get('rank'))
                        if member_id and rank and 1 <= rank <= len(member_scores):
                            score = member_scores[rank - 1]
                            direct_mode_contrib_scores[session.id][member_id] += score

        score_points = (
            pe_settings.group_scores or []
        ) if pe_settings and pe_settings.enable_group_evaluation else []
        if score_points:
            session_group_point_maps[session.id] = _build_group_vote_point_map(
                # N+1対策: 事前取得したデータを利用
                session_groups=[g for g in all_groups if g.lesson_session_id == session.id],
                session_peer_evals=session_to_evals_map.get(session.id, []),
                pe_settings=pe_settings,
                peer_status=session.peer_evaluation_status,
            )

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
            
            # ピア評価スコア
            peer_evaluation_score = 0
            real_contrib_score = 0
            real_vote_score = 0
            final_contrib = 0
            final_vote = 0
            is_simulated = False

            if session.has_peer_evaluation:
                try:
                    pe_settings = session_peer_settings.get(session.id)

                    # 3-1. 貢献度スコア (DIRECT or AGGREGATE)
                    if pe_settings and pe_settings.enable_member_evaluation:
                        if pe_settings.evaluation_method == PeerEvaluationSettings.EvaluationMethod.DIRECT:
                            # DIRECTモード: 事前集計したデータを利用
                            real_contrib_score = direct_mode_contrib_scores.get(session.id, {}).get(student.id, 0)
                        else: # AGGREGATEモード
                            # AGGREGATEモード: 事前集計したデータを利用
                            real_contrib_score = student_session_contrib_map.get(student.id, {}).get(session.id, 0)

                    # 3-2. 投票ポイントの計算
                    membership = GroupMember.objects.filter(
                        student=student,
                        group__lesson_session=session
                    ).first()
                    
                    if membership:
                        group = membership.group
                        score_points = (
                            pe_settings.group_scores or []
                        ) if pe_settings and pe_settings.enable_group_evaluation else []
                        if score_points:
                            group_point_map = session_group_point_maps.get(session.id, {})
                            real_vote_score = group_point_map.get(group.id, 0)

                    simulated_contrib_score = real_contrib_score
                    simulated_vote_score = real_vote_score
                    
                    # シミュレーションによるテスト用スコア計算
                    if test_mode and has_simulation:
                        sim_data = sim_data_class.get(str(session.id), {}).get(str(student.id))
                        if sim_data is not None:
                            if isinstance(sim_data, dict):
                                sess_sim_data = sim_data_class.get(str(session.id), {})
                                point_mode = sess_sim_data.get('point_mode', 'settings')
                                
                                sim_contrib_score = 0
                                if pe_settings and pe_settings.enable_member_evaluation:
                                    if point_mode == 'settings':
                                        if pe_settings.member_scores:
                                            for i, points in enumerate(pe_settings.member_scores):
                                                rank = i + 1
                                                count = sim_data.get(f'member_rank_{rank}')
                                                if count:
                                                    sim_contrib_score += float(count) * points
                                    elif point_mode == 'manual':
                                        contrib_val = sim_data.get('contrib')
                                        if contrib_val:
                                            sim_contrib_score += float(contrib_val)
                                elif not pe_settings or not pe_settings.enable_group_evaluation:
                                    # When both are disabled, use contrib
                                    contrib_val = sim_data.get('contrib', sim_data.get('member'))
                                    if contrib_val:
                                        sim_contrib_score += float(contrib_val)

                                sim_vote_score = 0
                                if pe_settings and pe_settings.enable_group_evaluation:
                                    if point_mode == 'settings':
                                        if pe_settings.group_scores:
                                            for i, points in enumerate(pe_settings.group_scores):
                                                rank = i + 1
                                                count = sim_data.get(f'group_rank_{rank}')
                                                if count:
                                                    sim_vote_score += float(count) * points
                                    elif point_mode == 'manual':
                                        group_manual = sim_data.get('group_manual')
                                        if group_manual:
                                            sim_vote_score += float(group_manual)

                                simulated_contrib_score = sim_contrib_score
                                simulated_vote_score = sim_vote_score
                                
                                # 互換性フォールバック (member, group)
                                if sim_contrib_score == 0 and sim_vote_score == 0 and ('member' in sim_data or 'group' in sim_data):
                                    simulated_contrib_score = sim_data.get('member', 0)
                                    simulated_vote_score = sim_data.get('group', 0)
                            else:
                                simulated_contrib_score = float(sim_data)
                                simulated_vote_score = 0
                            is_simulated = True

                    if test_mode:
                        peer_evaluation_score = simulated_contrib_score + simulated_vote_score
                        final_contrib = simulated_contrib_score
                        final_vote = simulated_vote_score
                    else:
                        peer_evaluation_score = real_contrib_score + real_vote_score
                        final_contrib = real_contrib_score
                        final_vote = real_vote_score
                        
                except Exception as e:
                    logger.error(f"ピア評価スコア取得エラー: {e}", exc_info=True)
                    pass

            # セッションごとのデータを辞書に保存
            session_data[session_key] = {
                'manual_points': manual_points,
                'quiz_score': quiz_score,
                'peer_score': peer_evaluation_score,
                'peer_contrib': final_contrib,
                'peer_vote': final_vote,
                'is_simulated': is_simulated if session.has_peer_evaluation else False,
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
        student_class_points = student_class_points_map.get(student.id)
        if student_class_points:
            attendance_rate = student_class_points.attendance_rate
            saved_attendance_points = student_class_points.attendance_points
        
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
        
        # 統計の平均点（シミュレーションを反映）
        class_average_points = round(sum(all_raw_scores) / len(all_raw_scores), 1)
    else:
        median_val = 0
        cutoff_line = 0
        max_val = 0
        class_average_points = 0.0

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
        'has_simulation': has_simulation,
        'test_mode': test_mode,
        'class_average_points': class_average_points,
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
            classroom_enrollments__classroom=classroom,
            classroom_enrollments__is_active=True,
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
