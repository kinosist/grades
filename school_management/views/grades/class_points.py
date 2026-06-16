import logging
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from collections import defaultdict
from django.db.models import Sum
from django.http import JsonResponse, HttpRequest, HttpResponse
from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse
from django.views.decorators.http import require_POST

from ...models import ClassRoom, CustomUser, StudentClassPoints, StudentLessonPoints, SelfEvaluation, QuizScore, \
    ContributionEvaluation, GroupMember, PeerEvaluation, PeerEvaluationSettings, LessonSession


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
@require_POST
def update_attendance_rate(request: HttpRequest, class_id: int) -> JsonResponse:
    """
    出席率を非同期で更新するAPI
    """
    import json

    # JSONリクエストを受け取る
    data = json.loads(request.body)
    student_id = data.get('student_id')
    attendance_rate = data.get('attendance_rate')
    attendance_points = data.get('attendance_points', 0)

    # バリデーション
    if not student_id or attendance_rate is None:
        return JsonResponse({'success': False, 'error': 'パラメータが不足しています'})

    if not (0 <= attendance_rate <= 100):
        return JsonResponse({'success': False, 'error': '出席率は0〜100の範囲で入力してください'})

    # クラスと学生を取得
    classroom = get_object_or_404(ClassRoom, id=class_id, teachers=request.user)
    student = get_object_or_404(CustomUser, id=student_id)

    # 学生がクラスに所属しているか確認
    if not classroom.students.filter(id=student_id).exists():
        return JsonResponse({'success': False, 'error': 'この学生はクラスに所属していません'})

    # 出席率、出席点、合計点をデータベースに保存
    student_class_points, created = StudentClassPoints.objects.get_or_create(
        student=student,
        classroom=classroom,
        defaults={'points': 0, 'attendance_rate': attendance_rate, 'attendance_points': attendance_points}
    )

    if not created:
        # 既存のレコードの出席率、出席点を更新（ポイントは更新しない）
        student_class_points.attendance_rate = attendance_rate
        student_class_points.attendance_points = attendance_points
        # save()メソッド内でcalculate_points_internalが呼ばれ、points(合計点)も再計算されるため
        # update_fieldsを指定せずに保存して、pointsの変更もDBに反映させる
        student_class_points.save()
    else:
        student_class_points.save()

    return JsonResponse({'success': True, 'message': '出席率を保存しました'})


@login_required
def class_points_view(request: HttpRequest, class_id: int) -> HttpResponse:
    """
    クラスごとのポイント一覧を表示するビュー
    """
    classroom = get_object_or_404(ClassRoom, id=class_id, teachers=request.user)
    grading_system = classroom.grading_system
    students = classroom.students.all().order_by('student_number')
    
    # テストモードか判定
    test_mode = request.session.get('test_mode', False)
    
    # セッションからシミュレーション用点数を取得
    # 辞書構造: { class_id: { session_id: { student_id: points } } }
    sim_data_class = request.session.get('peer_sim_points', {}).get(str(classroom.id), {})
    has_simulation = len(sim_data_class) > 0

    # ===== N+1問題対策: クラス全体の投票データを一度に取得して事前集計 =====
    from ...models import Group

    # このクラスの全セッションを取得
    all_sessions = classroom.lessonsession_set.all()
    session_ids = list(all_sessions.values_list('id', flat=True))

    # 全セッションのグループと投票データを一括取得
    all_groups = Group.objects.filter(lesson_session__in=session_ids).select_related('lesson_session')
    all_peer_evals = PeerEvaluation.objects.filter(lesson_session__in=session_ids)

    # セッションIDをキーにした評価データの辞書を作成
    session_to_evals_map = defaultdict(list)
    for pe in all_peer_evals:
        session_to_evals_map[pe.lesson_session_id].append(pe)

    # NEW: セッション設定のキャッシュ
    all_sessions_settings = {}
    for s in all_sessions:
        try:
            all_sessions_settings[s.id] = s.peer_evaluation_settings
        except PeerEvaluationSettings.DoesNotExist:
            all_sessions_settings[s.id] = None

    # セッションごとのランキング情報をキャッシュ
    session_rankings_cache = {}
    # NEW: DIRECTモード用の貢献度スコアを事前集計
    direct_mode_contrib_scores = defaultdict(lambda: defaultdict(int))

    for sess in all_sessions:
        sess_id = sess.id
        # そのセッションのグループを抽出
        session_groups = [g for g in all_groups if g.lesson_session_id == sess_id]
        # そのセッションの投票を抽出
        session_peer_evals = session_to_evals_map.get(sess_id, [])

        # グループごとの投票スコアを計算（response_json + 設定配点）
        pe_settings = all_sessions_settings.get(sess_id)

        # NEW: DIRECTモードのスコア計算
        if pe_settings and pe_settings.enable_member_evaluation and pe_settings.evaluation_method == PeerEvaluationSettings.EvaluationMethod.DIRECT:
            member_scores = pe_settings.member_scores or []
            if member_scores:
                for ev in session_peer_evals:
                    response = ev.response_json or {}
                    for entry in response.get('group_members_eval', []):
                        member_id = _safe_int(entry.get('member_id'))
                        rank = _safe_int(entry.get('rank'))
                        if member_id and rank and 1 <= rank <= len(member_scores):
                            score = member_scores[rank - 1]
                            direct_mode_contrib_scores[sess_id][member_id] += score

        group_scores = _build_group_vote_point_map(
            session_groups=session_groups,
            session_peer_evals=session_peer_evals,
            pe_settings=pe_settings,
            peer_status=sess.peer_evaluation_status,
        )

        # キャッシュに保存
        session_rankings_cache[sess_id] = {
            'group_scores': group_scores,
        }

    # NEW: ピア評価の貢献度スコアを事前集計
    # AGGREGATEモード用の集計
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

    # DIRECTモード用の評価データ辞書
    session_to_evals_map = defaultdict(list)
    for pe in all_peer_evals:
        session_to_evals_map[pe.lesson_session_id].append(pe)

    # N+1対策: 全学生のグループメンバーシップを一括で取得
    student_ids = [s.id for s in students]
    all_group_members = GroupMember.objects.filter(
        student_id__in=student_ids,
        group__lesson_session__classroom=classroom
    ).select_related('group', 'group__lesson_session')
    
    # 学生ごとのグループメンバーシップマップ
    student_group_members_map = defaultdict(list)
    for gm in all_group_members:
        student_group_members_map[gm.student_id].append(gm)

    # ===== 各学生のクラス内成績を取得 =====
    student_grades = []

    for student in students:
        # N+1対策: 事前取得したマップから学生のグループメンバーシップを取得
        student_groups = student_group_members_map.get(student.id, [])

        # 1. 授業内手動ポイント (StudentLessonPoints)
        lesson_points_qs = StudentLessonPoints.objects.filter(
            student=student,
            lesson_session__classroom=classroom
        ).select_related('lesson_session').order_by('lesson_session__session_number')
        lesson_total = sum(p.points for p in lesson_points_qs)

        # 2. 小テスト/QRポイント (QuizScore)
        all_quiz_scores = QuizScore.objects.filter(
            student=student,
            quiz__lesson_session__classroom=classroom,
            is_cancelled=False
        ).select_related('quiz', 'quiz__lesson_session').order_by('quiz__lesson_session__session_number')

        # 重複対策: 同一クイズは最新のみ
        quiz_score_dict = {}
        for qs in all_quiz_scores:
            quiz_score_dict[qs.quiz.id] = qs
        unique_quiz_scores = list(quiz_score_dict.values())
        unique_quiz_scores.sort(key=lambda x: x.quiz.lesson_session.session_number)

        quiz_total = sum(qs.score for qs in unique_quiz_scores)

        # 3. ピア評価ポイント
        peer_total = 0
        peer_details = []
        session_peer_map = {}

        # 全セッションをループしてピア評価ポイントを計算
        for sess in all_sessions:
            if not sess.has_peer_evaluation:
                continue

            sess_id = sess.id
            real_contrib_score = 0
            real_vote_score = 0
            
            try:
                pe_settings = all_sessions_settings.get(sess_id)

                # 貢献度スコア
                if pe_settings and pe_settings.enable_member_evaluation:
                    if pe_settings.evaluation_method == PeerEvaluationSettings.EvaluationMethod.DIRECT:
                        # DIRECTモード: 事前集計したデータを利用
                        real_contrib_score = direct_mode_contrib_scores.get(sess_id, {}).get(student.id, 0)
                    else:  # AGGREGATE
                        real_contrib_score = student_session_contrib_map.get(student.id, {}).get(sess_id, 0)
                
                # 投票ポイント
                student_group_in_session = next((g for g in student_groups if g.group.lesson_session_id == sess_id), None)
                if student_group_in_session:
                    group_id = student_group_in_session.group_id
                    if sess_id in session_rankings_cache:
                        ranking_info = session_rankings_cache[sess_id]
                        real_vote_score = ranking_info['group_scores'].get(group_id, 0)
                
                simulated_contrib_score = real_contrib_score
                simulated_vote_score = real_vote_score
                
                # シミュレーションによるテスト用スコア計算
                is_simulated = False
                if test_mode and has_simulation:
                    sim_data = sim_data_class.get(str(sess_id), {}).get(str(student.id))
                    if sim_data is not None:
                        if isinstance(sim_data, dict):
                            sess_sim_data = sim_data_class.get(str(sess_id), {})
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

                if real_contrib_score > 0 or real_vote_score > 0 or simulated_contrib_score > 0 or simulated_vote_score > 0 or is_simulated:
                    session_peer_map[sess_id] = {
                        'session': sess, 
                        'real_contrib': real_contrib_score, 
                        'real_vote': real_vote_score, 
                        'simulated_contrib': simulated_contrib_score,
                        'simulated_vote': simulated_vote_score,
                        'is_simulated': is_simulated
                    }
            except (AttributeError, IndexError, TypeError, ValueError) as e:
                logger.error(f"ピア評価ポイントの計算中にエラーが発生しました (student: {student.id}, session: {sess_id}): {e}", exc_info=True)
                # エラーが発生した場合、エラー情報を持ったエントリをマップに追加
                session_peer_map[sess_id] = {
                    'session': sess,
                    'real_contrib': 0,
                    'real_vote': 0,
                    'simulated_contrib': 0,
                    'simulated_vote': 0,
                    'error': f"計算エラー: {e}"
                }

        real_peer_total = 0
        simulated_peer_total = 0

        for data in session_peer_map.values():
            # エラーがある場合は、このセッションのピア評価ポイントを0として扱う
            real_p_sum = 0 if data.get('error') else data.get('real_contrib', 0) + data.get('real_vote', 0)
            sim_p_sum = 0 if data.get('error') else data.get('simulated_contrib', 0) + data.get('simulated_vote', 0)
            
            real_peer_total += real_p_sum
            simulated_peer_total += sim_p_sum
            
            peer_details.append({
                'session': data['session'],
                'contrib': data.get('simulated_contrib', 0) if test_mode else data.get('real_contrib', 0),
                'vote': data.get('simulated_vote', 0) if test_mode else data.get('real_vote', 0),
                'total': sim_p_sum if test_mode else real_p_sum,
                'error': data.get('error')  # テンプレートでエラー表示に利用
            })
        peer_details.sort(key=lambda x: x['session'].session_number)

        # 純粋な合計ポイント (QR + ピア + その他) - 本番用と表示用（テストモード用）を分ける
        real_raw_total_points = lesson_total + quiz_total + real_peer_total
        simulated_raw_total_points = lesson_total + quiz_total + simulated_peer_total

        # DB保存値（目標管理モード用）
        try:
            scp = StudentClassPoints.objects.get(student=student, classroom=classroom)
            db_points = scp.points
            attendance_points = scp.attendance_points
        except StudentClassPoints.DoesNotExist:
            db_points = 0
            attendance_points = 0

        # ポイント一覧では、モードに関わらず純粋な獲得ポイント（積み上げ）を表示する
        # テストモードの場合は、シミュレーション用ポイントを表示
        display_points = simulated_raw_total_points if test_mode else real_raw_total_points

        # 評価レベル判定（仮: 授業回あたりの平均などで判定していたロジックを維持）
        session_count = lesson_points_qs.count()
        lesson_average = round(lesson_total / session_count, 1) if session_count > 0 else 0

        if lesson_average >= 5:
            grade_level = '優秀'
            grade_color = 'success'
        elif lesson_average >= 3:
            grade_level = '良好'
            grade_color = 'warning'
        elif lesson_average >= 1:
            grade_level = '普通'
            grade_color = 'info'
        else:
            grade_level = '要努力'
            grade_color = 'secondary'

        student_grades.append({
            'student': student,
            'total_points': display_points,  # 一覧の「総ポイント」列に使用（テスト時はテスト用）
            'raw_total_points': real_raw_total_points, # 常に本番の合計を保持
            'quiz_total': quiz_total,
            'peer_total': simulated_peer_total if test_mode else real_peer_total,
            'lesson_total': lesson_total,
            'attendance_points': attendance_points,
            'average_points': lesson_average,
            'session_count': session_count,
            'lesson_points': lesson_points_qs,
            'quiz_scores': unique_quiz_scores,
            'peer_details': peer_details,
            'grade_level': grade_level,
            'grade_color': grade_color,
            'overall_points': student.points,  # 全体のポイント（参考用）
            'class_points': display_points,
        })

    # 合計ポイント順でソート
    student_grades.sort(key=lambda x: x['total_points'], reverse=True)

    # クラス全体の統計
    total_students = len(student_grades)
    if total_students > 0:
        class_average = round(sum(grade['total_points'] for grade in student_grades) / total_students, 1)
        max_average = max(grade['total_points'] for grade in student_grades)
        min_average = min(grade['total_points'] for grade in student_grades)
    else:
        class_average = 0
        max_average = 0
        min_average = 0

    context = {
        'classroom': classroom,
        'grading_system': grading_system,
        'student_grades': student_grades,
        'class_stats': {
            'total_students': total_students,
            'class_average': class_average,
            'max_average': max_average,
            'min_average': min_average,
        },
        'has_simulation': has_simulation,
        'test_mode': test_mode,
    }

    return render(request, 'school_management/class_points.html', context)


@login_required
def update_class_settings(request: HttpRequest, class_id: int) -> HttpResponse:
    """
    クラス設定（評価システム、QRポイント、出席点など）を更新するビュー
    """
    classroom = get_object_or_404(ClassRoom, id=class_id, teachers=request.user)

    # 1. 評価システムの更新
    grading_system = request.POST.get('grading_system')
    recalculate_points = False
    
    #  修正ポイント：models.py の GRADING_SYSTEM_CHOICES に合わせて許可リストを更新
    if grading_system in ['default', 'original', 'goal']:
        if classroom.grading_system != grading_system:
            classroom.grading_system = grading_system
            recalculate_points = True
            messages.success(request, '評価システムを更新しました。')
        else:
            messages.info(request, '評価システムは変更されていません。')

    # 2. QRポイントの更新
    qr_point_value = request.POST.get('qr_point_value')
    if qr_point_value:
        try:
            val = int(qr_point_value)
            if 0 < val <= 100:
                if classroom.qr_point_value != val:
                    classroom.qr_point_value = val
                    messages.success(request, 'QRアクションポイントを更新しました。')
                else:
                    messages.info(request, 'QRアクションポイントは変更されていません。')
            else:
                messages.error(request, 'QRアクションポイントは1〜100の間で設定してください。')
        except ValueError:
            pass

    # 3. 出席点満点の更新
    attendance_max_points = request.POST.get('attendance_max_points')
    recalculate_attendance = False
    if attendance_max_points:
        try:
            val = int(attendance_max_points)
            if 0 <= val <= 1000:
                if classroom.attendance_max_points != val:
                    classroom.attendance_max_points = val
                    recalculate_attendance = True
                    messages.success(request, '出席点満点を更新しました。')
                else:
                    messages.info(request, '出席点満点は変更されていません。')
            else:
                messages.error(request, '出席点満点は0〜1000の間で設定してください。')
        except ValueError:
            pass

    classroom.save()

    # 評価システムが変更された場合、全学生のポイントを再計算（モード切替）
    if recalculate_points:
        scps = StudentClassPoints.objects.filter(classroom=classroom)
        for scp in scps:
            scp.save()  # save()時に calculate_points_internal が走り、モードに応じた計算が行われる

    # 出席点満点が変更された場合、全学生の出席点を再計算
    if recalculate_attendance:
        scps = StudentClassPoints.objects.filter(classroom=classroom)
        for scp in scps:
            # 出席点 = 出席率 * 満点 / 100
            scp.attendance_points = (scp.attendance_rate * classroom.attendance_max_points) / 100
            scp.save()  # save()で合計点も再計算される

    # リファラ（元のページ）に応じてリダイレクト先を調整
    referer = request.META.get('HTTP_REFERER', '')
    if 'qr-codes' in referer:
        return redirect(referer)
    if 'evaluation' in referer:
        return redirect(referer)

    return redirect(f"{reverse('school_management:class_detail', args=[class_id])}?active_tab=settings")