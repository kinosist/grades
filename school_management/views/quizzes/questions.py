from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Max
from ...models import Quiz, Question, QuestionChoice

@login_required
def question_create_view(request, quiz_id):
    """小テスト問題作成"""
    quiz = get_object_or_404(Quiz, id=quiz_id)
    
    # 小テストの所属する授業回の教員かどうか確認
    if not quiz.lesson_session.classroom.teachers.filter(id=request.user.id).exists():
        return redirect('school_management:dashboard')
    
    if request.method == 'POST':
        question_text = request.POST.get('question_text')
        question_type = request.POST.get('question_type')
        points = int(request.POST.get('points', 1))
        
        # 問題の順番を決定
        last_order = Question.objects.filter(quiz=quiz).aggregate(
            max_order=Max('order')
        )['max_order'] or 0
        
        question = Question.objects.create(
            quiz=quiz,
            question_text=question_text,
            question_type=question_type,
            points=points,
            order=last_order + 1
        )
        
        # 選択問題または正誤問題の場合、選択肢を作成
        if question_type in ['multiple_choice', 'true_false']:
            if question_type == 'true_false':
                # 正誤問題の場合、True/Falseの選択肢を自動作成
                QuestionChoice.objects.create(
                    question=question,
                    choice_text='正しい',
                    is_correct=request.POST.get('correct_answer') == 'true',
                    order=1
                )
                QuestionChoice.objects.create(
                    question=question,
                    choice_text='間違い',
                    is_correct=request.POST.get('correct_answer') == 'false',
                    order=2
                )
            else:
                # 選択問題の場合、入力された選択肢を作成
                choice_texts = request.POST.getlist('choice_text')
                correct_choice_index = int(request.POST.get('correct_choice', 0))
                
                for i, choice_text in enumerate(choice_texts):
                    if choice_text.strip():  # 空でない選択肢のみ作成
                        QuestionChoice.objects.create(
                            question=question,
                            choice_text=choice_text.strip(),
                            is_correct=(i == correct_choice_index),
                            order=i + 1
                        )
        
        # 記述問題の場合、正解を保存
        elif question_type == 'short_answer':
            question.correct_answer = request.POST.get('correct_answer', '')
            question.save()
        
        messages.success(request, f'問題「{question_text[:30]}...」を作成しました。')
        return redirect('school_management:question_manage', quiz_id=quiz.id)
    
    # 既存の問題一覧を取得
    questions = Question.objects.filter(quiz=quiz).prefetch_related('choices')
    
    context = {
        'quiz': quiz,
        'questions': questions,
    }
    return render(request, 'school_management/question_create.html', context)


@login_required
def question_manage_view(request, quiz_id):
    """小テスト問題管理"""
    quiz = get_object_or_404(Quiz, id=quiz_id)
    
    # 小テストの所属する授業回の教員かどうか確認
    if not quiz.lesson_session.classroom.teachers.filter(id=request.user.id).exists():
        return redirect('school_management:dashboard')
    
    questions = Question.objects.filter(quiz=quiz).prefetch_related('choices')
    
    # 合計配点を計算
    total_points = sum(question.points for question in questions)
    
    context = {
        'quiz': quiz,
        'questions': questions,
        'total_points': total_points,
    }
    return render(request, 'school_management/question_manage.html', context)
