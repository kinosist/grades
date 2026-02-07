from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from ...models import LessonSession, Quiz

@login_required
def quiz_list_view(request, session_id):
    """小テスト一覧"""
    session = get_object_or_404(LessonSession, id=session_id, classroom__teachers=request.user)
    quizzes = Quiz.objects.filter(lesson_session=session).order_by('created_at')
    
    context = {
        'session': session,
        'quizzes': quizzes,
    }
    return render(request, 'school_management/quiz_list.html', context)

@login_required
def quiz_create_view(request, session_id):
    """小テスト作成"""
    session = get_object_or_404(LessonSession, id=session_id, classroom__teachers=request.user)
    
    if request.method == 'POST':
        quiz_name = request.POST.get('quiz_name')
        max_score = request.POST.get('max_score')
        grading_method = request.POST.get('grading_method')
        
        if quiz_name and max_score and grading_method:
            try:
                quiz = Quiz.objects.create(
                    lesson_session=session,
                    quiz_name=quiz_name,
                    max_score=int(max_score),
                    grading_method=grading_method
                )
                # セッションの小テストフラグを更新
                session.has_quiz = True
                session.save()
                
                messages.success(request, f'小テスト「{quiz_name}」を作成しました。')
                return redirect('school_management:quiz_grading', quiz_id=quiz.id)
            except ValueError:
                messages.error(request, '満点は数値で入力してください。')
        else:
            messages.error(request, 'すべての項目を入力してください。')
    
    context = {
        'session': session,
        'grading_methods': Quiz.GRADING_METHOD_CHOICES,
    }
    return render(request, 'school_management/quiz_create.html', context)
