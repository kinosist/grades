from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from ...models import LessonSession

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
    
    # 結果集計
    group_votes = {}
    contribution_scores = {}
    
    for evaluation in evaluations:
        # グループ投票集計
        # 1位: FKまたは番号からグループ番号を取得
        f_num = None
        if evaluation.first_place_group:
            f_num = evaluation.first_place_group.group_number
        elif evaluation.first_place_group_number:
            f_num = evaluation.first_place_group_number
            
        if f_num:
            group_name = f"グループ{f_num}"
            if group_name not in group_votes:
                group_votes[group_name] = {'first': 0, 'second': 0}
            group_votes[group_name]['first'] += 1
            
        # 2位
        s_num = None
        if evaluation.second_place_group:
            s_num = evaluation.second_place_group.group_number
        elif evaluation.second_place_group_number:
            s_num = evaluation.second_place_group_number
            
        if s_num:
            group_name = f"グループ{s_num}"
            if group_name not in group_votes:
                group_votes[group_name] = {'first': 0, 'second': 0}
            group_votes[group_name]['second'] += 1
        
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

    # グループ別集計（新テンプレート用）
    groups = session.group_set.all()
    group_stats = {}
    
    for group in groups:
        # このグループが1位に選ばれた回数
        first_place_votes = evaluations.filter(
            Q(first_place_group=group) | 
            Q(first_place_group_number=group.group_number)
        ).distinct().count()
        
        # このグループが2位に選ばれた回数
        second_place_votes = evaluations.filter(
            Q(second_place_group=group) | 
            Q(second_place_group_number=group.group_number)
        ).distinct().count()
        
        # このグループが評価した回数
        evaluations_given = evaluations.filter(
            Q(evaluator_group=group) |
            Q(evaluator_group_number=group.group_number)
        ).distinct().count()
        
        group_stats[group.id] = {
            'group': group,
            'first_place_votes': first_place_votes,
            'second_place_votes': second_place_votes,
            'total_votes': first_place_votes + second_place_votes,
            'evaluations_given': evaluations_given,
            'score': first_place_votes * 2 + second_place_votes  # 1位=2点、2位=1点でスコア計算
        }
    
    # スコア順でソート
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
        'lesson_session': session,  # テンプレートとの整合性を保つためにキー名を変更
        'evaluations': evaluations,
        'group_votes': group_votes,
        'avg_contribution_scores': avg_contribution_scores,
        'group_stats': sorted_groups,  # 新テンプレート用
        'total_evaluations': evaluations.count(),  # 新テンプレート用
        'total_groups': groups.count(),  # 新テンプレート用
        'submission_rows': submission_rows,
        'submitted_count': submitted_count,
        'total_students': total_students,
        'submission_rate': submission_rate,
    }
    return render(request, 'school_management/peer_evaluation_results.html', context)
