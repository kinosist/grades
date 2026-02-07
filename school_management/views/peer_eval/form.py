import hashlib
from django.shortcuts import render, redirect
from django.contrib import messages
from ...models import LessonSession, PeerEvaluation, Student, ContributionEvaluation

def peer_evaluation_form_view(request, token):
    """匿名ピア評価フォーム（学生用）"""
    # トークンからセッション情報を取得（簡易実装)
    
    try:
        # トークンの検証とセッション取得
        for session in LessonSession.objects.filter(has_peer_evaluation=True):
            session_token = hashlib.md5(f"peer_{session.id}".encode()).hexdigest()
            if session_token == token:
                target_session = session
                break
        else:
            messages.error(request, '無効なリンクです。')
            return redirect('school_management:login')
            
        # グループ取得
        groups = target_session.group_set.all()
        
        if request.method == 'POST':
            # フォームデータの処理
            evaluator_group_name = request.POST.get('evaluator_group')
            first_place_group = request.POST.get('first_place_group')
            second_place_group = request.POST.get('second_place_group')
            first_place_reason = request.POST.get('first_place_reason')
            second_place_reason = request.POST.get('second_place_reason')
            general_comment = request.POST.get('general_comment')
            
            # メンバー評価の処理
            member_evaluations = []
            for i in range(1, 8):  # 最大7名のメンバー
                member_name = request.POST.get(f'member_{i}_name')
                member_score = request.POST.get(f'member_{i}_score')
                
                if member_name and member_score:
                    member_evaluations.append({
                        'name': member_name,
                        'score': int(member_score)
                    })
            
            # 評価グループを特定
            try:
                evaluator_group_obj = groups.filter(group_number=int(evaluator_group_name.replace('グループ', ''))).first()
            except:
                evaluator_group_obj = None
            
            # 1位グループを特定
            try:
                first_group_obj = groups.filter(group_number=int(first_place_group.replace('グループ', ''))).first()
            except:
                first_group_obj = None
                
            # 2位グループを特定  
            try:
                second_group_obj = groups.filter(group_number=int(second_place_group.replace('グループ', ''))).first()
            except:
                second_group_obj = None
            
            # ピア評価を保存
            evaluation = PeerEvaluation.objects.create(
                lesson_session=target_session,
                evaluator_group=evaluator_group_obj,
                first_place_group=first_group_obj,
                second_place_group=second_group_obj,
                first_place_reason=first_place_reason,
                second_place_reason=second_place_reason,
                general_comment=general_comment
            )
            
            # メンバー評価を保存
            if evaluator_group_obj:
                for member_eval in member_evaluations:
                    # 学生を名前で検索（簡易実装）
                    try:
                        student = Student.objects.filter(full_name__icontains=member_eval['name']).first()
                        if student:
                            ContributionEvaluation.objects.create(
                                peer_evaluation=evaluation,
                                evaluatee=student,
                                contribution_score=member_eval['score']
                            )
                    except:
                        pass
            
            return render(request, 'school_management/peer_evaluation_success.html', {
                'session': target_session
            })
        
        context = {
            'session': target_session,
            'groups': groups,
            'token': token,
        }
        return render(request, 'school_management/peer_evaluation_form.html', context)
        
    except Exception as e:
        messages.error(request, 'エラーが発生しました。')
        return redirect('school_management:login')