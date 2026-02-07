import uuid
import json
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from ...models import LessonSession, Group, GroupMember, PeerEvaluation, ContributionEvaluation

# ---------------------------------------------------------
# 作成・リンク管理
# ---------------------------------------------------------

@login_required
def improved_peer_evaluation_create(request, session_id):
    """改善されたピア評価作成"""
    lesson_session = get_object_or_404(LessonSession, id=session_id, classroom__teachers=request.user)
    groups = Group.objects.filter(lesson_session=lesson_session)
    
    if not groups.exists():
        messages.error(request, 'ピア評価を作成する前に、まずグループを設定してください。')
        return redirect('school_management:group_management', session_id=session_id)
    
    if request.method == 'POST':
        # 各グループに対してトークンを生成
        for group in groups:
            token = str(uuid.uuid4())
            PeerEvaluation.objects.create(
                lesson_session=lesson_session,
                evaluator_token=token,
                evaluator_group=group,
                first_place_group=groups.first(), # 仮の値（後でフォームで更新）
                second_place_group=groups.first() # 仮の値
            )
        messages.success(request, 'ピア評価フォームを作成しました。')
        return redirect('school_management:peer_evaluation_links', session_id=session_id)
    
    context = {
        'lesson_session': lesson_session,
        'groups': groups,
        'students': lesson_session.classroom.students.all(),
    }
    return render(request, 'school_management/improved_peer_evaluation_create.html', context)

@login_required
def peer_evaluation_links(request, session_id):
    """ピア評価リンク一覧"""
    lesson_session = get_object_or_404(LessonSession, id=session_id, classroom__teachers=request.user)
    evaluations = PeerEvaluation.objects.filter(
        lesson_session=lesson_session, 
        evaluator_group__isnull=False
    ).select_related('evaluator_group')
    
    context = {
        'lesson_session': lesson_session,
        'evaluations': evaluations,
    }
    return render(request, 'school_management/peer_evaluation_links.html', context)

# ---------------------------------------------------------
# 回答フォーム（学生用・共通）
# ---------------------------------------------------------

def peer_evaluation_common_form(request, session_id):
    """共通ピア評価フォーム"""
    lesson_session = get_object_or_404(LessonSession, id=session_id)
    groups = Group.objects.filter(lesson_session=lesson_session).prefetch_related('groupmember_set__student')
    is_closed = lesson_session.peer_evaluation_closed
    
    if request.method == 'POST' and not is_closed:
        evaluator_group_id = request.POST.get('evaluator_group')
        participant_count = int(request.POST.get('participant_count', 0))
        first_place_id = request.POST.get('first_place_group')
        second_place_id = request.POST.get('second_place_group')
        
        if evaluator_group_id and first_place_id and second_place_id:
            evaluator_group = get_object_or_404(Group, id=evaluator_group_id)
            first_place = get_object_or_404(Group, id=first_place_id)
            second_place = get_object_or_404(Group, id=second_place_id)
            
            PeerEvaluation.objects.create(
                lesson_session=lesson_session,
                evaluator_token=str(uuid.uuid4()),
                evaluator_group=evaluator_group,
                first_place_group=first_place,
                second_place_group=second_place,
                first_place_reason=request.POST.get('first_place_reason', ''),
                second_place_reason=request.POST.get('second_place_reason', ''),
                general_comment=request.POST.get('general_comment', '')
            )
            # 必要であればここに貢献度評価の保存処理を追加
            
            return render(request, 'school_management/peer_evaluation_thanks.html', {
                'lesson_session': lesson_session,
                'first_place_group': first_place,
                'second_place_group': second_place,
                'show_evaluation_preview': True
            })

    # JSONデータ準備
    groups_data = []
    for group in groups:
        members_data = [{'id': m.student.id, 'name': m.student.full_name} for m in group.groupmember_set.all()]
        groups_data.append({
            'id': group.id, 
            'name': group.group_name or f'{group.group_number}グループ', 
            'members': members_data
        })
    
    context = {
        'lesson_session': lesson_session,
        'groups': groups,
        'groups_json': json.dumps(groups_data),
        'is_closed': is_closed,
    }
    return render(request, 'school_management/improved_peer_evaluation_form.html', context)

def improved_peer_evaluation_form(request, token):
    """改善されたピア評価フォーム（学生用・個別トークン）"""
    try:
        evaluator_token = uuid.UUID(token)
        peer_evaluation = get_object_or_404(PeerEvaluation, evaluator_token=evaluator_token)
        lesson_session = peer_evaluation.lesson_session
        evaluator_group = peer_evaluation.evaluator_group
        other_groups = Group.objects.filter(lesson_session=lesson_session).exclude(id=evaluator_group.id)
        group_members = GroupMember.objects.filter(group=evaluator_group)
        
        if request.method == 'POST':
            first_place_id = request.POST.get('first_place_group')
            second_place_id = request.POST.get('second_place_group')
            
            if first_place_id and second_place_id:
                peer_evaluation.first_place_group_id = first_place_id
                peer_evaluation.second_place_group_id = second_place_id
                peer_evaluation.first_place_reason = request.POST.get('first_place_reason', '')
                peer_evaluation.second_place_reason = request.POST.get('second_place_reason', '')
                peer_evaluation.general_comment = request.POST.get('general_comment', '')
                peer_evaluation.save()
                
                # 貢献度評価
                for member in group_members:
                    score = request.POST.get(f'contribution_{member.id}')
                    if score:
                        ContributionEvaluation.objects.update_or_create(
                            peer_evaluation=peer_evaluation,
                            evaluatee=member.student,
                            defaults={'contribution_score': int(score)}
                        )
                
                messages.success(request, 'ピア評価を送信しました。')
                return render(request, 'school_management/peer_evaluation_thanks.html', {'lesson_session': lesson_session})
            else:
                messages.error(request, '必須項目を入力してください。')
        
        context = {
            'lesson_session': lesson_session,
            'evaluator_group': evaluator_group,
            'other_groups': other_groups,
            'group_members': group_members,
            'peer_evaluation': peer_evaluation,
        }
        return render(request, 'school_management/improved_peer_evaluation_form.html', context)
        
    except (ValueError, PeerEvaluation.DoesNotExist):
        return render(request, 'school_management/peer_evaluation_error.html', {'error_message': '無効なリンクです。'})

# ---------------------------------------------------------
# 管理・集計（先生用）
# ---------------------------------------------------------

@login_required
def close_peer_evaluation(request, session_id):
    """ピア評価を締め切る"""
    lesson_session = get_object_or_404(LessonSession, id=session_id)
    
    # 教員権限チェック
    if request.user.role not in ['teacher', 'admin']:
        return redirect('school_management:dashboard')
    
    if request.method == 'POST':
        lesson_session.peer_evaluation_closed = True
        lesson_session.save()
        messages.success(request, 'ピア評価を締め切りました。')
    
    return redirect('school_management:improved_peer_evaluation_create', session_id=session_id)

@login_required
def reopen_peer_evaluation(request, session_id):
    """ピア評価を再開する"""
    lesson_session = get_object_or_404(LessonSession, id=session_id)
    
    # 教員権限チェック
    if request.user.role not in ['teacher', 'admin']:
        return redirect('school_management:dashboard')
    
    if request.method == 'POST':
        lesson_session.peer_evaluation_closed = False
        lesson_session.save()
        messages.success(request, 'ピア評価を再開しました。')
    
    return redirect('school_management:improved_peer_evaluation_create', session_id=session_id)

@login_required
def peer_evaluation_results(request, session_id):
    """ピア評価結果表示"""
    lesson_session = get_object_or_404(LessonSession, id=session_id)
    
    # 教員権限チェック
    if request.user.role not in ['teacher', 'admin']:
        return redirect('school_management:dashboard')
    
    # ピア評価データを取得
    evaluations = PeerEvaluation.objects.filter(lesson_session=lesson_session).select_related(
        'evaluator_group', 'first_place_group', 'second_place_group'
    )
    
    # グループ別集計
    groups = Group.objects.filter(lesson_session=lesson_session)
    group_stats = {}
    
    for group in groups:
        first_place_votes = evaluations.filter(first_place_group=group).count()
        second_place_votes = evaluations.filter(second_place_group=group).count()
        evaluations_given = evaluations.filter(evaluator_group=group).count()
        
        group_stats[group.id] = {
            'group': group,
            'first_place_votes': first_place_votes,
            'second_place_votes': second_place_votes,
            'total_votes': first_place_votes + second_place_votes,
            'evaluations_given': evaluations_given,
            'score': first_place_votes * 2 + second_place_votes  # 1位=2点、2位=1点
        }
    
    sorted_groups = sorted(group_stats.values(), key=lambda x: x['score'], reverse=True)
    
    context = {
        'lesson_session': lesson_session,
        'evaluations': evaluations,
        'group_stats': sorted_groups,
        'total_evaluations': evaluations.count(),
        'total_groups': groups.count(),
    }
    
    return render(request, 'school_management/peer_evaluation_results.html', context)