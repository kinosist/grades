from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Avg
from ...models import (
    CustomUser, ClassRoom, LessonSession, QuizScore, 
    Attendance, GroupMember, PeerEvaluation, StudentClassPoints
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
            class_points = class_points_obj.points
        except StudentClassPoints.DoesNotExist:
            class_points = 0
        
        class_data.append({
            'classroom': classroom,
            'points': class_points
        })
    
    context = {
        'student': student,
        'classes': classes,
        'class_data': class_data,
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
    quiz_scores = QuizScore.objects.filter(
        student=student,
        quiz__lesson_session__classroom=classroom
    ).select_related('quiz', 'quiz__lesson_session').order_by('-quiz__lesson_session__date')
    
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
    total_quizzes = quiz_scores.count()
    avg_score = quiz_scores.aggregate(avg=Avg('score'))['avg'] or 0
    attendance_count = attendance_records.filter(status='present').count()
    total_sessions = class_sessions.count()
    attendance_rate = (attendance_count / total_sessions * 100) if total_sessions > 0 else 0
    
    context = {
        'classroom': classroom,
        'student': student,
        'class_sessions': class_sessions[:5],  # 最新5セッション
        'quiz_scores': quiz_scores[:10],  # 最新10件のクイズ成績
        'attendance_records': attendance_records[:10],  # 最新10件の出席記録
        'peer_evaluations': peer_evaluations[:10],  # 最新10件のピア評価
        'stats': {
            'total_quizzes': total_quizzes,
            'avg_score': round(avg_score, 1),
            'attendance_count': attendance_count,
            'total_sessions': total_sessions,
            'attendance_rate': round(attendance_rate, 1),
        }
    }
    return render(request, 'school_management/class_student_detail.html', context)