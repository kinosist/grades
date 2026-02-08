from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from ...models import StudentLessonPoints, StudentClassPoints, ClassRoom, LessonSession

@login_required
def student_dashboard(request):
    # 学生が所属するクラスを取得
    student_classrooms = ClassRoom.objects.filter(students=request.user)
    
    # 最近の授業回
    recent_sessions = LessonSession.objects.filter(
        classroom__in=student_classrooms
    ).order_by('-date')[:10]
    
    # ピア評価が必要な授業回
    pending_evaluations = LessonSession.objects.filter(
        classroom__in=student_classrooms,
        has_peer_evaluation=True
    ).order_by('-date')
    
    # 学生の授業ごとのポイントを取得
    lesson_points = StudentLessonPoints.objects.filter(
        student=request.user
    ).select_related('lesson_session').order_by('-lesson_session__date')
    
    # クラスごとのポイントを取得
    class_points_list = []
    for classroom in student_classrooms:
        try:
            class_points_obj = StudentClassPoints.objects.get(student=request.user, classroom=classroom)
            class_points = class_points_obj.points
        except StudentClassPoints.DoesNotExist:
            class_points = 0
        
        class_points_list.append({
            'classroom': classroom,
            'points': class_points
        })
    
    context = {
        'student_classrooms': student_classrooms,
        'recent_sessions': recent_sessions,
        'pending_evaluations': pending_evaluations,
        'total_classes': student_classrooms.count(),
        'lesson_points': lesson_points,
        'class_points_list': class_points_list,
    }
    return render(request, 'school_management/student_dashboard.html', context)
