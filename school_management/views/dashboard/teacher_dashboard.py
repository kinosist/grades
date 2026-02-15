from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from datetime import datetime, timedelta
from ...models import ClassRoom, LessonSession, Student

@login_required
def teacher_dashboard(request):
    """教員用ダッシュボード"""
    
    # --- 日付ナビゲーション処理 ---
    # URLのパラメータ(?date=2026-02-14)から日付を取得。なければ今日。
    date_str = request.GET.get('date')
    if date_str:
        try:
            current_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            current_date = datetime.now().date()
    else:
        current_date = datetime.now().date()

    # 前の日と次の日を計算
    prev_date = current_date - timedelta(days=1)
    next_date = current_date + timedelta(days=1)
    
    # --- データ取得 ---

    # 担当クラス数
    user_classes = ClassRoom.objects.filter(teachers=request.user)
    total_classes = user_classes.count()
    
    # 担当クラスの学生数
    total_students = Student.objects.filter(classroom__teachers=request.user).distinct().count()
    
    # 今週の授業回数（統計用）
    today = datetime.now().date()
    week_start = today - timedelta(days=today.weekday())
    week_end = week_start + timedelta(days=6)
    
    this_week_sessions = LessonSession.objects.filter(
        classroom__teachers=request.user,
        date__range=[week_start, week_end]
    ).count()
    
    # ★修正: periodが存在しないため、session_number（回数）順に並び替え
    daily_sessions = LessonSession.objects.filter(
        classroom__teachers=request.user,
        date=current_date
    ).order_by('session_number') 
    
    # テンプレートに渡すデータ
    context = {
        'total_classes': total_classes,
        'total_students': total_students,
        'this_week_sessions': this_week_sessions,
        'daily_sessions': daily_sessions,
        'classes': user_classes,
        # カレンダー用データ
        'current_date': current_date,
        'prev_date': prev_date,
        'next_date': next_date,
        'is_today': current_date == today,
    }
    
    return render(request, 'school_management/dashboard.html', context)