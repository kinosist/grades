from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect
from .teacher_dashboard import teacher_dashboard
from .student_dashboard import student_dashboard

@login_required
def dashboard_view(request):
    """メインダッシュボード（役割に応じて振り分け）"""
    if request.user.role == 'admin':
        return redirect('school_management:admin_teacher_management')
    elif request.user.is_teacher:
        return teacher_dashboard(request)
    elif request.user.is_student:
        return student_dashboard(request)
    else:
        return redirect('school_management:login')
