from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from ...models import ClassRoom, LessonSession

@login_required
def session_create_view(request, class_id):
    """授業回作成"""
    classroom = get_object_or_404(ClassRoom, id=class_id, teachers=request.user)
    
    if request.method == 'POST':
        session_number = request.POST.get('session_number')
        date = request.POST.get('date')
        topic = request.POST.get('topic')
        
        if session_number and date:
            try:
                session = LessonSession.objects.create(
                    classroom=classroom,
                    session_number=int(session_number),
                    date=date,
                    topic=topic or ''
                )
                messages.success(request, f'第{session_number}回授業を作成しました。')
                return redirect('school_management:session_detail', session_id=session.id)
            except (ValueError, Exception) as e:
                messages.error(request, f'作成に失敗しました: {str(e)}')
        else:
            messages.error(request, '授業回と日付は必須です。')
    
    # 次の授業回番号を提案
    last_session = LessonSession.objects.filter(classroom=classroom).order_by('-session_number').first()
    next_session_number = (last_session.session_number + 1) if last_session else 1
    
    context = {
        'classroom': classroom,
        'next_session_number': next_session_number,
    }
    return render(request, 'school_management/session_create.html', context)