from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required
from ...models import LessonSession, Quiz

@login_required
def lesson_session_detail(request, session_id):
    """授業回詳細"""
    session = get_object_or_404(LessonSession, id=session_id, classroom__teachers=request.user)
    quizzes = Quiz.objects.filter(lesson_session=session)
    
    context = {
        'session': session,
        'quizzes': quizzes,
    }
    return render(request, 'school_management/session_detail.html', context)
