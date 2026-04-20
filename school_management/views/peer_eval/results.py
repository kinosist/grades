from collections import defaultdict

from django.contrib.auth.decorators import login_required
from django.shortcuts import render, get_object_or_404

from ...models import LessonSession


def _safe_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _build_submission_detail(evaluation, group_name_map, student_name_map):
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
        member_evaluations.append({
            'rank': entry.get('rank'),
            'target_name': student_name_map.get(member_id, f'学生ID:{member_id}' if member_id else '不明'),
            'reason': (entry.get('reason') or '').strip(),
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
def peer_evaluation_list_view(request, session_id):
    """ピア評価一覧"""
    session = get_object_or_404(LessonSession, id=session_id, classroom__teachers=request.user)
    evaluations = session.peerevaluation_set.all()
    
    context = {
        'session': session,
        'evaluations': evaluations,
    }
    return render(request, 'school_management/peer_evaluation_list.html', context)

@login_required
def peer_evaluation_results_view(request, session_id):
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
            'evaluations_given': evaluations_given,
            'score': total_score,
        }
    
    sorted_groups = sorted(group_stats.values(), key=lambda x: x['score'], reverse=True)

    submission_map = {}
    for submission in evaluations.filter(student__isnull=False).order_by('student_id', '-created_at'):
        if submission.student_id not in submission_map:
            submission_map[submission.student_id] = submission

    enrolled_students = list(session.classroom.students.filter(role='student').order_by('full_name'))
    group_name_map = {group.id: group.display_name for group in groups}
    student_name_map = {student.id: student.full_name for student in enrolled_students}
    submission_rows = []
    submitted_count = 0
    for enrolled_student in enrolled_students:
        submission = submission_map.get(enrolled_student.id)
        submitted = submission is not None
        if submitted:
            submitted_count += 1
        submission_rows.append({
            'student': enrolled_student,
            'email': enrolled_student.email,
            'submitted': submitted,
            'submitted_at': submission.created_at if submission else None,
            'submission_detail': _build_submission_detail(submission, group_name_map, student_name_map) if submission else None,
        })

    total_students = len(enrolled_students)
    submission_rate = round((submitted_count / total_students) * 100, 1) if total_students else 0
    
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
    }
    return render(request, 'school_management/peer_evaluation_results.html', context)
