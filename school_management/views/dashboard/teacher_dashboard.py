from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from ...models import ClassRoom, LessonSession, Student

@login_required
def teacher_dashboard(request):
    """教員用ダッシュボード"""
    # 担当クラス数
    user_classes = ClassRoom.objects.filter(teachers=request.user)
    total_classes = user_classes.count()
    
    # 担当クラスの学生数
    total_students = Student.objects.filter(classroom__teachers=request.user).distinct().count()
    
    # 今週の授業回数
    from datetime import datetime, timedelta
    today = datetime.now().date()
    week_start = today - timedelta(days=today.weekday())
    week_end = week_start + timedelta(days=6)
    
    this_week_sessions = LessonSession.objects.filter(
        classroom__teachers=request.user,
        date__range=[week_start, week_end]
    ).count()
    
    # 最近の授業回
    recent_sessions = LessonSession.objects.filter(
        classroom__teachers=request.user
    ).order_by('-date')[:5]
    
    context = {
        'total_classes': total_classes,
        'total_students': total_students,
        'this_week_sessions': this_week_sessions,
        'recent_sessions': recent_sessions,
        'classes': user_classes,
    }
    
    return render(request, 'school_management/dashboard.html', context)