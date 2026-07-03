from collections import defaultdict
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, get_object_or_404
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.utils.http import url_has_allowed_host_and_scheme
from ...models import LessonSession, PeerEvaluationSettings, GroupMember, Student

def _safe_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None

def _build_submission_detail(evaluation, group_name_map, student_name_map, active_student_ids=None):
    active_student_ids = active_student_ids or set()
    response = evaluation.response_json or {}
    group_evaluations = []
    for entry in response.get('other_group_eval', []):
        group_id = _safe_int(entry.get('group_id'))
        group_evaluations.append({
            'rank': entry.get('rank'),
            'target_name': group_name_map.get(group_id, f'グループID:{group_id}' if group_id else '不明'),
            'reason': (entry.get('reason') or '').strip(),
        })

    member_evaluations = []
    for entry in response.get('group_members_eval', []):
        member_id = _safe_int(entry.get('member_id'))
        target_name = student_name_map.get(member_id)
        is_deleted = False
        is_unlinked = False
        if not target_name:
            if member_id:
                target_name = '削除済みの学生'
                is_deleted = True
            else:
                target_name = '不明'
        elif member_id not in active_student_ids:
            is_unlinked = True
        member_evaluations.append({
            'rank': entry.get('rank'),
            'target_name': target_name,
            'reason': (entry.get('reason') or '').strip(),
            'is_deleted': is_deleted,
            'is_unlinked': is_unlinked,
        })

    general_comment = (evaluation.general_comment or '').strip()
    class_comment = (evaluation.class_comment or '').strip()

    return {
        'group_evaluations': group_evaluations,
        'member_evaluations': member_evaluations,
        'general_comment': general_comment,
        'class_comment': class_comment,
        'has_content': bool(group_evaluations or member_evaluations or general_comment or class_comment),
    }

@login_required
def save_peer_evaluation_simulation(request: HttpRequest, session_id: int) -> HttpResponse:
    """ピア評価のシミュレーション（テスト用）点数をセッションに保存する"""
    if request.method == 'POST':
        session = get_object_or_404(LessonSession, id=session_id, classroom__teachers=request.user)
        class_id = str(session.classroom.id)
        
        sim_data = request.session.get('peer_sim_points', {})
        if class_id not in sim_data:
            sim_data[class_id] = {}
        
        session_sim = {}
        session_sim['point_mode'] = request.POST.get('sim_point_mode', 'settings')
        
        for key, value in request.POST.items():
            if value.strip():
                # 詳細な順位・獲得票の入力形式
                # 例: sim_member_rank_1_123, sim_group_rank_2_123
                if key.startswith('sim_member_rank_'):
                    # parts: ['sim', 'member', 'rank', '1', '123']
                    parts = key.split('_')
                    if len(parts) >= 5:
                        rank = parts[3]
                        student_id = parts[4]
                        if student_id not in session_sim:
                            session_sim[student_id] = {}
                        try:
                            session_sim[student_id][f'member_rank_{rank}'] = float(value)
                        except ValueError:
                            pass
                elif key.startswith('sim_group_rank_'):
                    parts = key.split('_')
                    if len(parts) >= 5:
                        rank = parts[3]
                        student_id = parts[4]
                        if student_id not in session_sim:
                            session_sim[student_id] = {}
                        try:
                            session_sim[student_id][f'group_rank_{rank}'] = float(value)
                        except ValueError:
                            pass
                elif key.startswith('sim_contrib_'):
                    student_id = key.replace('sim_contrib_', '')
                    if student_id not in session_sim:
                        session_sim[student_id] = {}
                    try:
                        session_sim[student_id]['contrib'] = float(value)
                    except ValueError:
                        pass
                elif key.startswith('sim_group_manual_'):
                    student_id = key.replace('sim_group_manual_', '')
                    if student_id not in session_sim:
                        session_sim[student_id] = {}
                    try:
                        session_sim[student_id]['group_manual'] = float(value)
                    except ValueError:
                        pass
                # 古い形式との互換性用
                elif key.startswith('sim_member_score_'):
                    student_id = key.replace('sim_member_score_', '')
                    if student_id not in session_sim:
                        session_sim[student_id] = {}
                    try:
                        session_sim[student_id]['member'] = float(value)
                    except ValueError:
                        pass
                elif key.startswith('sim_group_score_'):
                    student_id = key.replace('sim_group_score_', '')
                    if student_id not in session_sim:
                        session_sim[student_id] = {}
                    try:
                        session_sim[student_id]['group'] = float(value)
                    except ValueError:
                        pass
                elif key.startswith('sim_score_'):
                    student_id = key.replace('sim_score_', '')
                    if student_id not in session_sim:
                        session_sim[student_id] = {}
                    try:
                        session_sim[student_id]['member'] = float(value)
                    except ValueError:
                        pass
        
        sim_data[class_id][str(session_id)] = session_sim
        request.session['peer_sim_points'] = sim_data
        
        from django.contrib import messages
        messages.success(request, 'シミュレーション用のテスト点数を保存しました。')
        
    next_url = request.META.get('HTTP_REFERER')
    if not next_url or not url_has_allowed_host_and_scheme(
        next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        next_url = '/'
    return HttpResponseRedirect(next_url)

@login_required
def clear_peer_evaluation_simulation(request: HttpRequest, session_id: int) -> HttpResponse:
    """特定のセッションのシミュレーションデータをクリアする"""
    if request.method == 'POST':
        session = get_object_or_404(LessonSession, id=session_id, classroom__teachers=request.user)
        class_id = str(session.classroom.id)
        
        sim_data = request.session.get('peer_sim_points', {})
        if class_id in sim_data and str(session_id) in sim_data[class_id]:
            del sim_data[class_id][str(session_id)]
            request.session['peer_sim_points'] = sim_data
            
        from django.contrib import messages
        messages.success(request, 'この授業回のシミュレーションデータをクリアしました。')
        
    next_url = request.META.get('HTTP_REFERER')
    if not next_url or not url_has_allowed_host_and_scheme(
        next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        next_url = '/'
    return HttpResponseRedirect(next_url)

@login_required
def toggle_test_mode(request: HttpRequest) -> HttpResponse:
    """テストモードのON/OFFを切り替える"""
    if request.method == 'POST':
        current_mode = request.session.get('test_mode', False)
        request.session['test_mode'] = not current_mode
        from django.contrib import messages
        mode_str = 'ON' if not current_mode else 'OFF'
        messages.success(request, f'テストモードを {mode_str} にしました。')
    next_url = request.POST.get('next') or request.META.get('HTTP_REFERER')
    if not next_url or not url_has_allowed_host_and_scheme(
        next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        next_url = '/'
    return HttpResponseRedirect(next_url)

@login_required
def peer_evaluation_results_view(request: HttpRequest, session_id: int) -> HttpResponse:
    """ピア評価結果表示"""
    session = get_object_or_404(LessonSession, id=session_id, classroom__teachers=request.user)
    evaluations = session.peerevaluation_set.all()
    
    pe_settings = None
    if session.peer_evaluation_configured:
        pe_settings = session.peer_evaluation_settings
    
    group_score_list = pe_settings.group_scores if pe_settings else []
    
    # response_jsonからグループ別得票を集計
    group_vote_counts = defaultdict(lambda: defaultdict(int))
    
    contribution_scores = {}
    
    for evaluation in evaluations:
        response = evaluation.response_json or {}
        for entry in response.get('other_group_eval', []):
            gid = _safe_int(entry.get('group_id'))
            rank = _safe_int(entry.get('rank'))
            if gid is not None and rank is not None:
                group_vote_counts[gid][rank] += 1
        
        # 貢献度評価集計
        for contrib_eval in evaluation.contributionevaluation_set.all():
            student_name = contrib_eval.evaluatee.full_name
            if student_name not in contribution_scores:
                contribution_scores[student_name] = []
            contribution_scores[student_name].append(contrib_eval.contribution_score)
    
    # 平均貢献度計算
    avg_contribution_scores = {}
    for student, scores in contribution_scores.items():
        avg_contribution_scores[student] = sum(scores) / len(scores)

    # グループ別集計
    groups = session.group_set.all()
    group_stats = {}
    
    # AGGREGATEモードの場合の内部ポイントを計算
    aggregate_internal_points = {}
    if (
        pe_settings
        and pe_settings.enable_group_evaluation
        and pe_settings.group_evaluation_method == PeerEvaluationSettings.EvaluationMethod.AGGREGATE
        and session.peer_evaluation_status == LessonSession.PeerEvaluationStatus.CLOSED
    ):
        group_ids = [g.id for g in groups]
        group_count = len(group_ids)
        aggregate_internal_points = {gid: 0 for gid in group_ids}
        for ev in evaluations:
            response = ev.response_json or {}
            for entry in response.get('other_group_eval', []):
                gid = _safe_int(entry.get('group_id'))
                rank = _safe_int(entry.get('rank'))
                if gid in aggregate_internal_points and rank is not None and 1 <= rank <= group_count:
                    aggregate_internal_points[gid] += (group_count - rank)

    for group in groups:
        votes = group_vote_counts.get(group.id, {})
        total_score = 0
        for rank, count in votes.items():
            rank = _safe_int(rank)
            if rank is not None and 1 <= rank <= len(group_score_list):
                total_score += group_score_list[rank - 1] * count
        
        evaluations_given = evaluations.filter(evaluator_group=group).count()
        
        group_stats[group.id] = {
            'group': group,
            'votes_by_rank': dict(votes),
            'total_score': total_score,
            'internal_points': aggregate_internal_points.get(group.id, 0),
            'evaluations_given': evaluations_given,
            'score': total_score,
        }
    
    sorted_groups = sorted(group_stats.values(), key=lambda x: x['score'], reverse=True)

    submission_map = {}
    for submission in evaluations.filter(student__isnull=False).order_by('student_id', '-created_at'):
        if submission.student_id not in submission_map:
            submission_map[submission.student_id] = submission

    # 現在担当している（在籍中の）学生のIDセット
    active_student_ids = set(
        session.classroom.students.filter(role='student').values_list('id', flat=True)
    )
    # 担当から外れていても、このグループ・この授業回に関わっていた学生は
    # 「担当から外れた学生」として一覧から消さずに表示する
    former_participant_ids = set(
        GroupMember.objects.filter(group__lesson_session=session).values_list('student_id', flat=True)
    ) | set(
        evaluations.exclude(student__isnull=True).values_list('student_id', flat=True)
    )
    all_participant_ids = active_student_ids | former_participant_ids

    enrolled_students = list(Student.objects.filter(id__in=all_participant_ids, role='student').order_by('full_name'))
    group_name_map = {group.id: group.display_name for group in groups}
    student_name_map = {student.id: student.full_name for student in enrolled_students}
    submission_rows = []
    submitted_count = 0
    for enrolled_student in enrolled_students:
        submission = submission_map.get(enrolled_student.id)
        submitted = submission is not None
        if submitted and enrolled_student.id in active_student_ids:
            submitted_count += 1
            
        # シミュレーション用の値を取得（辞書形式を想定）
        student_sim_data = {}
        sim_data = request.session.get('peer_sim_points', {}).get(str(session.classroom.id), {}).get(str(session.id), {})
        if str(enrolled_student.id) in sim_data:
            data = sim_data[str(enrolled_student.id)]
            if isinstance(data, dict):
                student_sim_data = data
            else:
                # 過去の単一数値データの場合の互換性
                student_sim_data = {'member': float(data), 'group': 0}
        # テンプレートでループしやすいようにリストを作成
        member_sim_inputs = []
        if pe_settings and pe_settings.enable_member_evaluation:
            for i, point in enumerate(pe_settings.member_scores or []):
                rank = i + 1
                val = student_sim_data.get(f'member_rank_{rank}', '')
                member_sim_inputs.append({'rank': rank, 'point': point, 'val': val})
                
        group_sim_inputs = []
        if pe_settings and pe_settings.enable_group_evaluation:
            for i, point in enumerate(pe_settings.group_scores or []):
                rank = i + 1
                val = student_sim_data.get(f'group_rank_{rank}', '')
                group_sim_inputs.append({'rank': rank, 'point': point, 'val': val})
                
        sim_contrib = student_sim_data.get('contrib', '')
        if not sim_contrib and 'member' in student_sim_data:
            # 古い互換性データの場合
            sim_contrib = student_sim_data['member']
            
        submission_rows.append({
            'student': enrolled_student,
            'email': enrolled_student.email,
            'submitted': submitted,
            'submitted_at': submission.created_at if submission else None,
            'submission_detail': _build_submission_detail(submission, group_name_map, student_name_map, active_student_ids) if submission else None,
            'sim_data': student_sim_data,
            'member_sim_inputs': member_sim_inputs,
            'group_sim_inputs': group_sim_inputs,
            'sim_contrib': sim_contrib,
            'is_unlinked': enrolled_student.id not in active_student_ids,
        })

    total_students = len(active_student_ids)
    submission_rate = round((submitted_count / total_students) * 100, 1) if total_students else 0
    
    # 現在のセッションのシミュレーション状態
    has_simulation = str(session.id) in request.session.get('peer_sim_points', {}).get(str(session.classroom.id), {})
    test_mode = request.session.get('test_mode', False)

    context = {
        'lesson_session': session,
        'evaluations': evaluations,
        'avg_contribution_scores': avg_contribution_scores,
        'group_stats': sorted_groups,
        'total_evaluations': evaluations.count(),
        'total_groups': groups.count(),
        'submission_rows': submission_rows,
        'submitted_count': submitted_count,
        'total_students': total_students,
        'submission_rate': submission_rate,
        'pe_settings': pe_settings,
        'has_simulation': has_simulation,
        'test_mode': test_mode,
    }
    return render(request, 'school_management/peer_evaluation_results.html', context)