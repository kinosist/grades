from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required
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
        if evaluation.first_place_group:
            group_name = f"グループ{evaluation.first_place_group.group_number}"
            if group_name not in group_votes:
                group_votes[group_name] = {'first': 0, 'second': 0}
            group_votes[group_name]['first'] += 1
            
        if evaluation.second_place_group:
            group_name = f"グループ{evaluation.second_place_group.group_number}"
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
        first_place_votes = evaluations.filter(first_place_group=group).count()
        # このグループが2位に選ばれた回数
        second_place_votes = evaluations.filter(second_place_group=group).count()
        # このグループが評価した回数
        evaluations_given = evaluations.filter(evaluator_group=group).count()
        
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
    
    context = {
        'lesson_session': session,  # テンプレートとの整合性を保つためにキー名を変更
        'evaluations': evaluations,
        'group_votes': group_votes,
        'avg_contribution_scores': avg_contribution_scores,
        'group_stats': sorted_groups,  # 新テンプレート用
        'total_evaluations': evaluations.count(),  # 新テンプレート用
        'total_groups': groups.count(),  # 新テンプレート用
    }
    return render(request, 'school_management/peer_evaluation_results.html', context)

