from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from ...models import ClassRoom, LessonSession

# 授業セッション管理
@login_required          
def lesson_session_create(request, class_id):
    """授業回作成"""
    classroom = get_object_or_404(ClassRoom, id=class_id, teachers=request.user)
    
    if request.method == 'POST':
        session_number = request.POST.get('session_number')
        date = request.POST.get('date')
        topic = request.POST.get('topic', '')
        has_quiz = request.POST.get('has_quiz') == 'on'
        has_peer_evaluation = request.POST.get('has_peer_evaluation') == 'on'
        
        # 授業回作成
        LessonSession.objects.create(
            classroom=classroom,
            session_number=session_number,
            date=date,
            topic=topic,
            has_quiz=has_quiz,
            has_peer_evaluation=has_peer_evaluation
        )
        
        messages.success(request, f'第{session_number}回の授業を作成しました。 {request.POST.get("has_quiz")}')
        return redirect('school_management:class_detail', class_id=class_id)
    
    # 次の回数を自動設定
    last_session = LessonSession.objects.filter(classroom=classroom).order_by('-session_number').first()
    next_session_number = (last_session.session_number + 1) if last_session else 1
    
    context = {
        'classroom': classroom,
        'next_session_number': next_session_number,
    }
    return render(request, 'school_management/lesson_session_create.html', context)

@login_required
def lesson_session_detail(request, session_id):
    """授業回詳細"""
    lesson_session = get_object_or_404(LessonSession, id=session_id, classroom__teachers=request.user)
    
    context = {
        'lesson_session': lesson_session,
    }
    return render(request, 'school_management/lesson_session_detail.html', context)

@login_required
def lesson_session_delete(request, session_id):
    """授業回削除"""
    session = get_object_or_404(LessonSession, id=session_id, classroom__teachers=request.user)
    
    if request.method == 'POST':
        classroom_id = session.classroom.id
        session.delete()
        messages.success(request, '授業回を削除しました。')
        return redirect('school_management:class_detail', class_id=classroom_id)
    
    return render(request, 'school_management/session_delete.html', {'session': session})