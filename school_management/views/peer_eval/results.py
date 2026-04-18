from collections import defaultdict
from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required
from ...models import LessonSession, PeerEvaluationSettings

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
            gid = entry.get('group_id')
            rank = entry.get('rank')
            if gid and rank:
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
            if rank - 1 < len(group_score_list):
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
