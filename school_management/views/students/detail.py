from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Avg
from ...models import (
    CustomUser, ClassRoom, LessonSession, QuizScore, 
    Attendance, GroupMember, PeerEvaluation, StudentClassPoints,
    StudentGoal, SelfEvaluation, LessonReport
)

@login_required
def student_detail_view(request, student_number):
    """学生詳細"""
    if not request.user.is_teacher:
        messages.error(request, 'この機能にアクセスする権限がありません。')
        return redirect('school_management:dashboard')

    student = get_object_or_404(CustomUser, student_number=student_number, role='student')

    # 削除処理
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'delete_student':
            try:
                student_name = student.full_name
                student.delete()
                messages.success(request, f'{student_name}さんを削除しました。')
                return redirect('school_management:student_list')
            except Exception as e:
                messages.error(request, f'削除中にエラーが発生しました: {str(e)}')
                return redirect('school_management:student_detail', student_number=student_number)
    
    # 所属クラス一覧とそれぞれのクラスポイントを取得（担当クラスのみ）
    classes = student.classroom_set.filter(teachers=request.user)
    
    # 担当クラスに所属していない場合は、すべてのクラスを表示（アクセス制御を緩和）
    if not classes.exists():
        classes = student.classroom_set.all()
    
    class_data = []
    for classroom in classes:
        try:
            class_points_obj = StudentClassPoints.objects.get(student=student, classroom=classroom)
            class_points = class_points_obj.class_points
        except StudentClassPoints.DoesNotExist:
            class_points = 0
        
        class_data.append({
            'classroom': classroom,
            'points': class_points
        })
    
    # 統計情報を計算 (全クラス合計)
    # 1. 小テスト統計 (重複除外)
    all_quiz_scores = QuizScore.objects.filter(
        student=student,
        is_cancelled=False
    ).order_by('graded_at')
    
    unique_scores = {qs.quiz_id: qs.score for qs in all_quiz_scores}
    total_quizzes = len(unique_scores)
    avg_score = round(sum(unique_scores.values()) / total_quizzes, 1) if total_quizzes > 0 else 0
    
    # 2. ピア評価回数 (評価した回数)
    student_groups = GroupMember.objects.filter(student=student).values_list('group', flat=True)
    peer_eval_count = PeerEvaluation.objects.filter(
        evaluator_group__in=student_groups
    ).count()
    
    context = {
        'student': student,
        'classes': classes,
        'class_data': class_data,
        'stats': {
            'total_quizzes': total_quizzes,
            'avg_score': avg_score,
            'peer_eval_count': peer_eval_count,
        }
    }
    return render(request, 'school_management/student_detail.html', context)

@login_required
def class_student_detail_view(request, class_id, student_number):
    """クラス内の学生詳細"""
    # 担当教師のチェックを追加
    classroom = get_object_or_404(ClassRoom, id=class_id, teachers=request.user)
    student = get_object_or_404(CustomUser, student_number=student_number, role='student')
    
    # 学生がこのクラスに所属しているかチェック
    if not classroom.students.filter(student_number=student_number).exists():
        messages.error(request, 'この学生は指定されたクラスに所属していません。')
        return redirect('school_management:class_detail', class_id=class_id)
    
    # クラス内での学生の成績やアクティビティを取得
    class_sessions = LessonSession.objects.filter(classroom=classroom).order_by('-date')
    
    # このクラスでのクイズ成績を取得
    # 授業日が新しい順、かつ採点日時が新しい順に取得（キャンセル済みは除外）
    all_quiz_scores = QuizScore.objects.filter(
        student=student,
        quiz__lesson_session__classroom=classroom,
        is_cancelled=False
    ).select_related('quiz', 'quiz__lesson_session').order_by('-quiz__lesson_session__date', '-graded_at')
    
    # 重複排除: 同じクイズIDなら最新の1件のみをリストに追加
    quiz_scores = []
    seen_quiz_ids = set()
    for score in all_quiz_scores:
        if score.quiz.id not in seen_quiz_ids:
            quiz_scores.append(score)
            seen_quiz_ids.add(score.quiz.id)
            if len(quiz_scores) >= 10:  # 最新10件集まったら終了
                break
    
    # このクラスでの出席記録を取得
    attendance_records = Attendance.objects.filter(
        student=student,
        lesson_session__classroom=classroom
    ).select_related('lesson_session').order_by('-lesson_session__date')
    
    # このクラスでのピア評価を取得（学生が所属するグループによる評価）
    # まず学生が所属するグループを取得
    student_groups = GroupMember.objects.filter(student=student).values_list('group', flat=True)
    
    peer_evaluations = PeerEvaluation.objects.filter(
        evaluator_group__in=student_groups,
        lesson_session__classroom=classroom
    ).select_related('lesson_session').order_by('-created_at')
    
    # 統計情報を計算
    # 重複排除した全スコアで計算（quiz_scoresはリスト化されているためQuerySetメソッドは使えない）
    unique_scores_map = {}
    for score in all_quiz_scores:
        if score.quiz.id not in unique_scores_map:
            unique_scores_map[score.quiz.id] = score.score
            
    total_quizzes = len(unique_scores_map)
    avg_score = sum(unique_scores_map.values()) / total_quizzes if total_quizzes > 0 else 0
    
    attendance_count = attendance_records.filter(status='present').count()
    total_sessions = class_sessions.count()
    attendance_rate = (attendance_count / total_sessions * 100) if total_sessions > 0 else 0
    
    # 目標・自己評価の取得
    goal = StudentGoal.objects.filter(student=student, classroom=classroom).first()
    self_eval = SelfEvaluation.objects.filter(student=student, classroom=classroom).first()

    # このクラスでの日報一覧（授業回日付順）
    lesson_reports = LessonReport.objects.filter(
        student=student,
        lesson_session__classroom=classroom
    ).select_related('lesson_session').order_by('lesson_session__date')

    context = {
        'classroom': classroom,
        'student': student,
        'class_sessions': class_sessions[:5],  # 最新5セッション
        'quiz_scores': quiz_scores,  # 重複排除済みのリスト（最大10件）
        'attendance_records': attendance_records[:10],  # 最新10件の出席記録
        'peer_evaluations': peer_evaluations[:10],  # 最新10件のピア評価
        'goal': goal,
        'self_eval': self_eval,
        'lesson_reports': lesson_reports,
        'stats': {
            'total_quizzes': total_quizzes,
            'avg_score': round(avg_score, 1),
            'attendance_count': attendance_count,
            'total_sessions': total_sessions,
            'attendance_rate': round(attendance_rate, 1),
        }
    }
    return render(request, 'school_management/class_student_detail.html', context)