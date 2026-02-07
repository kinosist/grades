from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from ...models import Quiz, QuizScore

@login_required
def quiz_grading_view(request, quiz_id):
    """小テスト採点"""
    quiz = get_object_or_404(Quiz, id=quiz_id, lesson_session__classroom__teachers=request.user)
    students = quiz.lesson_session.classroom.students.all()
    
    # 採点結果を学生IDをキーにして辞書作成
    score_objects = QuizScore.objects.filter(quiz=quiz, is_cancelled=False).select_related('student')
    scores = {score.student.student_number: score for score in score_objects}
    
    # 学生リストに採点情報を追加
    students_with_scores = []
    for student in students:
        student_data = {
            'student': student,
            'score': scores.get(student.student_number),
            'is_graded': student.student_number in scores
        }
        students_with_scores.append(student_data)
    
    if request.method == 'POST':
        action = request.POST.get('action')
        
        if action == 'save_scores':
            # 採点結果保存
            teacher = request.user  # 現在のユーザーを採点者として使用
            
            for student in students:
                score_value = request.POST.get(f'score_{student.student_number}')
                if score_value and score_value.strip():
                    try:
                        score = int(score_value)
                        if 0 <= score <= quiz.max_score:
                            # 既存の採点結果があれば削除
                            QuizScore.objects.filter(quiz=quiz, student=student, is_cancelled=False).update(is_cancelled=True)
                            # 新しい採点結果を作成
                            QuizScore.objects.create(
                                quiz=quiz,
                                student=student,
                                score=score,
                                graded_by=teacher
                            )
                    except ValueError:
                        pass  # 無効な値は無視
            
            messages.success(request, '採点結果を保存しました。')
            return redirect('school_management:quiz_grading', quiz_id=quiz_id)
    
    context = {
        'quiz': quiz,
        'students_with_scores': students_with_scores,
        'students': students,
        'graded_count': len(scores),
        'quick_buttons': quiz.quick_buttons or {},
    }
    return render(request, 'school_management/quiz_grading.html', context)

@login_required
def quiz_results_view(request, quiz_id):
    """小テスト結果表示"""
    quiz = get_object_or_404(Quiz, id=quiz_id, lesson_session__classroom__teachers=request.user)
    scores = QuizScore.objects.filter(quiz=quiz, is_cancelled=False).select_related('student').order_by('student__student_number')
    
    # 統計情報計算
    score_values = [score.score for score in scores]
    stats = {}
    if score_values:
        stats = {
            'count': len(score_values),
            'average': sum(score_values) / len(score_values),
            'max': max(score_values),
            'min': min(score_values),
            'total_students': quiz.lesson_session.classroom.students.count(),
            'graded_students': len(score_values),
        }
    
    context = {
        'quiz': quiz,
        'scores': scores,
        'stats': stats,
    }
    return render(request, 'school_management/quiz_results.html', context)
